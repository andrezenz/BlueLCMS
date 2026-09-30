import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem

from bluelcms.app import MainWindow
from bluelcms import settings
from bluelcms.views import pixel_buckets, positive_zoom_range
from test_mzml import write_mzml


def test_folder_load_and_region_histograms(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    path = write_mzml(tmp_path / "sample.mzML")
    window = MainWindow()
    window.show()
    try:
        assert window.windowTitle() == "⌊Blue⌋ LCMS"
        settings.set_data_folder(tmp_path)
        assert settings.data_folder() == tmp_path
        window.folder = tmp_path
        window.refresh_files()
        window.pool.waitForDone()
        app.processEvents()
        assert window.files.count() == 1
        window.files.setCurrentRow(0)
        window.pool.waitForDone()
        app.processEvents()
        assert window.run_data is not None
        assert window.uv.region.isVisible()
        window.region_timer.stop()
        window.calculate_region()
        window.pool.waitForDone()
        app.processEvents()
        positive_bars = [item for item in window.positive.items() if isinstance(item, pg.BarGraphItem)]
        negative_bars = [item for item in window.negative.items() if isinstance(item, pg.BarGraphItem)]
        np.testing.assert_equal(positive_bars[0].opts["height"], [2, 4, 6])
        # The shared x range follows positive data; off-screen negative bins are
        # not drawn until panned into view, but no visible bin is dropped.
        np.testing.assert_equal(negative_bars[0].opts["height"], [3, 5])
        assert "0.1 Th bins" in window.statusBar().currentMessage()
        # A stale load must never overwrite a newer file selection.
        window.loaded(window.load_token - 1, path, None, "stale failure")
        assert window.run_data is not None
        path.unlink()
        window.refresh_files()
        window.pool.waitForDone()
        app.processEvents()
        assert window.run_data is None
        assert window.files.count() == 0
        assert not window.uv.region.isVisible()
        # Slow responses from an older remote folder cannot replace this list.
        window.files_listed(window.folder_token - 1, [path], "")
        assert window.files.count() == 0
        window.files_listed(window.folder_token, None, "Share disconnected")
        assert "Reconnect" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_drag_inside_full_selection_creates_new_interval():
    from bluelcms.views import UVPlot

    app = QApplication.instance() or QApplication([])
    plot = UVPlot()
    plot.resize(800, 400)
    plot.show()
    try:
        plot.trace.setData([0, 5, 10], [0, 1, 0])
        plot.region.setBounds((0, 10))
        plot.region.setRegion((0, 10))
        plot.region.show()
        plot.setXRange(0, 10, padding=0)
        plot.setYRange(0, 1, padding=0)
        app.processEvents()
        def point(x):
            return plot.mapFromScene(plot.getViewBox().mapViewToScene(QPointF(x, 0.5)))

        QTest.mouseMove(plot.viewport(), point(2))
        QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, pos=point(2))
        # Offscreen QTest.mouseMove does not preserve pressed buttons on all Qt
        # platforms; deliver realistic move events with explicit button state.
        for x in (4, 6):
            QTest.qWait(30)
            position = QPointF(point(x))
            move = QMouseEvent(QEvent.Type.MouseMove, position,
                               QPointF(plot.viewport().mapToGlobal(point(x))),
                               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(plot.viewport(), move)
        QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, pos=point(6))
        app.processEvents()
        np.testing.assert_allclose(plot.region.getRegion(), [2, 6], atol=0.05)
    finally:
        plot.close()


def test_pixel_bucket_aggregation_preserves_hidden_mass_signal():
    x, y, width = pixel_buckets([500.05, 501.05, 502.05, 504.05], [2, 3, 5, 7], 500, 506, 2)
    np.testing.assert_allclose(x, [501.5, 504.5])
    np.testing.assert_equal(y, [10, 7])
    assert width == 3


def test_histogram_intensity_zoom_keeps_zero_fixed():
    assert positive_zoom_range(100, True) == (0, 90)
    assert positive_zoom_range(90, False) == (0, 100)


def test_cached_item_is_marked(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    remote = tmp_path / "gvfs" / "afp-volume:host=lab,volume=LC" / "sample.mzML"
    remote.parent.mkdir(parents=True)
    remote.touch()
    settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        item = QListWidgetItem(remote.name)
        item.setData(Qt.ItemDataRole.UserRole, remote)
        window.files.addItem(item)
        window.refresh_cache_indicators()
        assert item.toolTip() == "Remote source"
        cache = window.cache_for(remote)
        cache.parent.mkdir(); cache.touch()
        window.refresh_cache_indicators()
        assert item.toolTip() == "Cached locally"
        window.set_download_state(remote, True)
        assert item.toolTip() == "Downloading remote source…"
    finally:
        window.close()


def test_peak_labels_name_source_bins_not_pixel_bucket(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.histograms = {"run": {"+": (np.array([500.05, 501.05, 502.05]), np.array([2, 99, 3])), "-": (np.array([]), np.array([]))}}
        window.positive.setXRange(500, 503, padding=0)
        window.draw_histograms()
        labels = [item.toPlainText() for item in window.positive.items() if isinstance(item, pg.TextItem)]
        assert "501.05" in labels
    finally:
        window.close()


def test_byte_progress_and_loading_overlay_are_visible():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.load_token = 7
        window.load_progress(7, Path(__file__), 50, 100)
        app.processEvents()
        assert window.progress.isVisible()
        assert window.progress.value() == 50
        assert window.progress.format() == "Loading 50%"
        window.set_loading(True)
        assert not window.uv.isEnabled()
        assert "#6a6a6a" in window.uv.styleSheet()
        window.set_loading(False)
        assert window.uv.isEnabled()
    finally:
        window.close()


def test_streamed_uv_points_draw_before_run_completion(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        path = tmp_path / "remote.mzML"
        item = QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        window.files.addItem(item)
        item.setSelected(True)
        window.load_token = 9
        window.stream_uv = {path: []}
        window.streamed_uv_points(9, path, [(1.5, 42, 254)])
        QTest.qWait(100)
        app.processEvents()
        assert window.stream_uv[path] == [(1.5, 42, 254)]
        assert "streaming" in window.uv.plotItem.titleLabel.text.lower()
    finally:
        window.close()


def test_preview_cursor_uses_full_streamed_uv_range(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        path = tmp_path / "remote.mzML"
        item = QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        window.files.addItem(item)
        item.setSelected(True)
        window.load_token = 11
        window.stream_uv = {path: [(1, 5, 254), (4, 6, 254)]}
        window.uv_preview_ready(11)
        np.testing.assert_allclose(window.uv.region.getRegion(), [1, 4])
        assert window.loading_cursor.isVisible()
        window.streamed_ms_time(11, 3)
        assert window.loading_cursor.value() == 3
    finally:
        window.close()


def test_multi_measurement_bins_stack_instead_of_overdrawing():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.histograms = {
            "first": {"+": (np.array([500.05]), np.array([2.])), "-": (np.array([]), np.array([]))},
            "second": {"+": (np.array([500.05]), np.array([3.])), "-": (np.array([]), np.array([]))},
        }
        window.positive.setXRange(500, 501, padding=0)
        window.draw_histograms()
        bars = [item for item in window.positive.items() if isinstance(item, pg.BarGraphItem)]
        assert len(bars) == 2
        stacked = sorted((float(item.opts["y0"][0]), float(item.opts["height"][0])) for item in bars)
        assert stacked == [(0, 2), (2, 3)]
    finally:
        window.close()
