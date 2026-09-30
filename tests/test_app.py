import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bluelcms.app import MainWindow
from bluelcms import settings
from bluelcms.views import pixel_buckets
from test_mzml import write_mzml


def test_folder_load_and_region_histograms(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    path = write_mzml(tmp_path / "sample.mzML")
    window = MainWindow()
    window.show()
    try:
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
