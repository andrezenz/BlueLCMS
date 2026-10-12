import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from bluelcms.sidebar import MeasurementItem as QListWidgetItem

from bluelcms.app import MainWindow
from bluelcms import settings
from bluelcms.vendor import MeasurementKey, VendorMeasurement
from bluelcms.views import pixel_buckets, positive_zoom_range
from test_mzml import write_mzml
from test_vendor import write_agilent_sirslt, write_datx


def test_offline_cache_survives_refresh_and_restart(tmp_path, monkeypatch):
    from bluelcms.app import cache_metadata
    from bluelcms.mzml import load_run, write_compact_cache
    from bluelcms.folders import cached_path

    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    remote = tmp_path / "remote"
    remote.mkdir()
    source = write_mzml(remote / "sample.mzML")
    cache_folder = tmp_path / "cache"
    settings.set_cache_folder(cache_folder)
    settings.set_data_folders([remote])
    write_compact_cache(load_run(source), cached_path(source, cache_folder), cache_metadata(source))
    online = MainWindow()
    try:
        online.pool.waitForDone(); app.processEvents()
        assert online.files.count() == 1
        assert online.files.item(0).data(Qt.ItemDataRole.UserRole + 1) == "source-cached"
    finally:
        online.close()
    source.unlink()
    remote.rmdir()
    for _ in range(2):
        window = MainWindow()
        try:
            window.pool.waitForDone(); app.processEvents()
            assert window.files.count() == 1
            item = window.files.item(0)
            assert item.text() == "sample.mzML"
            assert item.data(Qt.ItemDataRole.UserRole) == source
            assert item.data(Qt.ItemDataRole.UserRole + 1) == "cache-only"
            assert window.cache_expiry.value() == 0
            window.files.setCurrentRow(0)
            window.pool.waitForDone(); app.processEvents()
            assert window.run_data is not None
            assert window.run_data.scans
            assert not window.loading_timer.isActive()
        finally:
            window.close()


def test_packaged_update_uses_release_selector_and_installer(tmp_path, monkeypatch):
    from bluelcms import app as app_module, package_updater, releases

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(app_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(MainWindow, "check_packaged_release", lambda *args: None)
    window = MainWindow()
    try:
        update_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "Update")
        assert [action.text() for action in update_menu.actions()] == ["Update version…"]
        submitted = []
        monkeypatch.setattr(window, "submit", lambda *args: submitted.append(args))
        window.select_release()
        assert submitted[-1][1] is releases.published_versions
        monkeypatch.setattr(app_module.QInputDialog, "getItem", lambda *args: ("v1.0.1", True))
        window.release_options_ready(0, {"v1.0.1": "refs/tags/v1.0.1"}, "")
        assert submitted[-1][1] is package_updater.install
        assert submitted[-1][-1] == "refs/tags/v1.0.1"
    finally:
        application.processEvents()
        window.close()


def test_background_refresh_preserves_selection_and_toggle(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    folder = tmp_path / "remote"
    folder.mkdir()
    source = write_mzml(folder / "first.mzML")
    settings.set_data_folders([folder])
    window = MainWindow()
    try:
        window.pool.waitForDone(); application.processEvents()
        assert window.source_refresh_timer.isActive()
        assert window.source_refresh_timer.interval() == 60000
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); application.processEvents()
        run = window.run_data
        window.uv.region.setBounds((0, 2))
        window.uv.region.setRegion((0.6, 0.9))
        added = write_mzml(folder / "second.mzML")
        window.refresh_files(background=True)
        window.pool.waitForDone(); application.processEvents()
        assert window.files.count() == 2
        assert {item.data(Qt.ItemDataRole.UserRole) for item in window.files.selectedItems()} == {source}
        assert window.run_data is run
        np.testing.assert_allclose(window.uv.region.getRegion(), [0.6, 0.9])
        assert added in {window.files.item(index).data(Qt.ItemDataRole.UserRole) for index in range(2)}
        window.auto_refresh_sources.setChecked(False)
        assert not window.source_refresh_timer.isActive()
        assert not settings.auto_refresh_sources()
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert not reopened.auto_refresh_sources.isChecked()
        assert not reopened.source_refresh_timer.isActive()
    finally:
        reopened.close()


def test_sidebar_groups_nested_measurements_and_preserves_collapsed_folders(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    root = tmp_path / "remote"
    nested = root / "batch" / "day"
    nested.mkdir(parents=True)
    source = write_mzml(nested / "first.mzML")
    settings.set_data_folders([root])
    window = MainWindow()
    try:
        window.pool.waitForDone(); application.processEvents()
        leaf = window.files.item(0)
        day = leaf.parent()
        assert day.text() == "day"
        assert day.parent().text() == "batch"
        assert day.parent().parent().text() == "remote"
        assert window.files.topLevelItemCount() == 1
        assert not day.flags() & Qt.ItemFlag.ItemIsSelectable
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); application.processEvents()
        original_run = window.run_data
        assert original_run is not None
        day.setExpanded(False)
        write_mzml(nested / "second.mzML")
        window.refresh_files(background=True)
        window.pool.waitForDone(); application.processEvents()
        assert window.files.count() == 2
        assert leaf.parent() is day
        assert not day.isExpanded()
        assert window.run_data is original_run
        assert window.files.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == source
    finally:
        window.close()


def test_cached_only_measurement_keeps_original_folder_hierarchy(tmp_path, monkeypatch):
    import shutil
    from bluelcms.app import cache_metadata
    from bluelcms.folders import cached_path
    from bluelcms.mzml import load_run, write_compact_cache

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    root = tmp_path / "remote"
    nested = root / "batch" / "day"
    nested.mkdir(parents=True)
    source = write_mzml(nested / "sample.mzML")
    cache = tmp_path / "cache"
    settings.set_data_folders([root])
    settings.set_cache_folder(cache)
    write_compact_cache(load_run(source), cached_path(source, cache), cache_metadata(source))
    shutil.rmtree(root)
    window = MainWindow()
    try:
        window.pool.waitForDone(); application.processEvents()
        assert window.files.count() == 1
        leaf = window.files.item(0)
        assert leaf.parent().text() == "day"
        assert leaf.parent().parent().text() == "batch"
        assert leaf.parent().parent().parent().text() == "remote"
        assert leaf.data(Qt.ItemDataRole.UserRole + 1) == "cache-only"
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); application.processEvents()
        assert window.run_data is not None
    finally:
        window.close()


def test_startup_prompts_for_missing_cache_folder(tmp_path, monkeypatch):
    from bluelcms import app as app_module
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    calls = []
    monkeypatch.setattr(window, "check_packaged_release", lambda: calls.append("stable check"))
    monkeypatch.setattr(window, "choose_cache_folder", lambda: calls.append("choose cache"))
    monkeypatch.setattr(app_module.QMessageBox, "question", lambda *args: app_module.QMessageBox.StandardButton.Yes)
    try:
        window.startup_checks()
        assert calls == ["stable check", "choose cache"]
        calls.clear()
        settings.set_cache_folder(tmp_path / "cache")
        window.startup_checks()
        assert calls == ["stable check"]
    finally:
        window.close()


class FakePausableLoad:
    def __init__(self):
        self.paused = False
        self.resumed = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.resumed = True


def test_load_job_retains_parser_state_while_paused(monkeypatch, tmp_path):
    from threading import Event, Thread
    from bluelcms import app as app_module
    from bluelcms.mzml import DADScan, Run

    observed = []
    calls = []
    paused = Event()
    job = app_module.LoadJob(1, tmp_path / "remote.mzML", 254)
    def parse(path, progress, dad_callback, scan_callback):
        calls.append(path)
        scans = []
        for index in range(3):
            scan = DADScan(index, np.array([254]), np.array([index]))
            dad_callback(scan)
            scans.append(scan)
            observed.append(index)
            if index == 0:
                job.pause()
                paused.set()
        return Run(tuple(scans), ())
    monkeypatch.setattr(app_module, "load_run", parse)
    worker = Thread(target=job.run)
    worker.start()
    try:
        assert paused.wait(2)
        assert observed == [0]
        assert worker.is_alive()
        job.resume()
        worker.join(2)
        assert not worker.is_alive()
        assert observed == [0, 1, 2]
        assert len(calls) == 1
    finally:
        job.resume()
        worker.join(2)


@pytest.mark.parametrize("first_fails", [False, True])
def test_ctrl_selection_queues_without_restarting_active_load(tmp_path, monkeypatch, first_fails):
    from bluelcms.mzml import Run
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    first = write_mzml(tmp_path / "first.mzML")
    second = write_mzml(tmp_path / "second.mzML")
    settings.set_data_folders([tmp_path])
    window = MainWindow()
    started = []
    def submit(token, path, source, label, callback):
        started.append((token, path))
        window.load_jobs[path] = FakePausableLoad()
    monkeypatch.setattr(window, "submit_load", submit)
    try:
        window.pool.waitForDone(); application.processEvents()
        window.files.item(0).setSelected(True)
        first_token = window.load_token
        window.streamed_uv_points(first_token, first, [(1, 42, 254)])
        window.files.item(1).setSelected(True)
        assert started == [(first_token, first)]
        assert window.load_queue == [second]
        assert window.stream_uv[first] == [(1, 42, 254)]
        assert "[1/2]" in window.progress.format()
        window.loaded(first_token, first, Run((), ()), "remote disconnected" if first_fails else "")
        assert len(started) == 2
        assert started[-1][1] == second
        assert "[2/2]" in window.progress.format()
        window.loaded(window.load_token, second, Run((), ()), "")
        assert window.active_load is None
        assert set(window.runs) == ({second} if first_fails else {first, second})
        assert not window.loading_timer.isActive()
    finally:
        window.close()


def test_single_selection_preempts_then_caches_previous_without_display(tmp_path, monkeypatch):
    from bluelcms.mzml import Run, write_compact_cache
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    first = write_mzml(tmp_path / "first.mzML")
    second = write_mzml(tmp_path / "second.mzML")
    settings.set_data_folders([tmp_path])
    window = MainWindow()
    started = []
    cache_requests = []
    def submit(token, path, source, label, callback):
        started.append((token, path))
        window.load_jobs[path] = FakePausableLoad()
    monkeypatch.setattr(window, "submit_load", submit)
    try:
        window.pool.waitForDone(); application.processEvents()
        settings.set_cache_folder(tmp_path / "cache")
        monkeypatch.setattr(window, "submit", lambda *args: cache_requests.append(args))
        window.files.setCurrentRow(0)
        first_token = window.load_token
        first_job = window.load_jobs[first]
        window.files.setCurrentRow(1)
        second_token = window.load_token
        assert first_job.paused
        assert window.active_load == second
        assert [path for _, path in started] == [first, second]
        foreground = Run((), ())
        window.loaded(second_token, second, foreground, "")
        assert first_job.resumed, "resume background reading as soon as foreground data is ready"
        request = cache_requests.pop(0)
        cache = write_compact_cache(*request[3:])
        window.cached(second_token, second, cache, "")
        assert first_job.resumed
        assert window.active_load == first
        assert window.run_data is foreground
        window.loaded(first_token, first, Run((), ()), "")
        request = cache_requests.pop(0)
        cache = write_compact_cache(*request[3:])
        window.cached(first_token, first, cache, "")
        assert window.active_load is None
        assert set(window.runs) == {second}
        assert window.run_data is foreground
        assert window.cache_for(first).is_file()
        assert len(started) == 2, "resume must not start another download"
    finally:
        window.close()


def test_vendor_cache_keeps_uv_tic_and_spectra_offline(tmp_path, monkeypatch):
    import shutil
    from bluelcms.app import cache_metadata
    from bluelcms.mzml import write_compact_cache
    from bluelcms.vendor import load_vendor_measurement
    from bluelcms.folders import cached_path

    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    source_root = tmp_path / "remote"
    measurement = vendor_measurement(source_root)
    original = load_vendor_measurement(measurement)
    cache_folder = tmp_path / "cache"
    settings.set_cache_folder(cache_folder)
    settings.set_data_folders([source_root])
    write_compact_cache(original, cached_path(measurement.agilent, cache_folder), cache_metadata(measurement))
    shutil.rmtree(source_root)
    window = MainWindow()
    try:
        window.pool.waitForDone(); app.processEvents()
        assert window.files.count() == 1
        assert window.files.item(0).data(Qt.ItemDataRole.UserRole + 1) == "cache-only"
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); app.processEvents()
        assert len(window.run_data.scans) == len(original.scans)
        assert window.run_data.tic == original.tic
        assert window.run_data.auxiliary[0].name == "UV Scan"
        np.testing.assert_array_equal(window.run_data.auxiliary[0].values, original.auxiliary[0].values)
        assert window.wavelength.value() == 250
    finally:
        window.close()


def vendor_measurement(tmp_path, spectra=True, name="ANZ254R4"):
    """Build a synthetic Agilent run plus its two Advion polarities."""
    agilent = write_agilent_sirslt(tmp_path / "Agilent" / f"2026_10_06_{name}.sirslt", count=40)
    folder = tmp_path / "expression" / f"2026_10_6_11_19_59_{name}_1"
    folder.mkdir(parents=True, exist_ok=True)
    positive, negative = folder / f"{name}_Scan1_is1.datx", folder / f"{name}_Scan2_is2.datx"
    write_datx(positive, negative=False, count=4)
    write_datx(negative, negative=True, count=4)
    if spectra:
        for source in (positive, negative):
            raw = source.parent / f"{source.stem}/{source.stem}.raw"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(np.arange(4 * 3, dtype="<f4").tobytes())
    return VendorMeasurement(MeasurementKey("2026_10_06", name.upper()), agilent, positive, negative)


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
        assert "Th display bins" in window.statusBar().currentMessage()
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
        assert "could not be read" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_matched_vendor_measurement_is_one_sidebar_entry(tmp_path, monkeypatch):
    """One Agilent run plus two Advion acquisitions must display as one measurement."""
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    measurement = vendor_measurement(tmp_path, spectra=True)
    settings.set_data_folders([tmp_path])
    window = MainWindow()
    window.show()
    try:
        window.pool.waitForDone(); app.processEvents()
        assert window.files.count() == 1
        item = window.files.item(0)
        source = item.data(Qt.ItemDataRole.UserRole)
        assert source == measurement
        assert "Agilent + Advion" in item.text()
        assert measurement.agilent.name in item.toolTip()
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); app.processEvents()
        assert window.run_data is not None
        # Agilent exports a single 250 nm channel, so the control must follow it.
        assert window.wavelength.value() == 250
        assert len(window.run_data.scans) == 8
        window.region_timer.stop()
        window.calculate_region()
        window.pool.waitForDone(); app.processEvents()
        bars = [item for item in window.positive.items() if isinstance(item, pg.BarGraphItem)]
        assert bars
    finally:
        window.close()


def test_vendor_measurement_without_raw_shows_chromatograms_only(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    measurement = vendor_measurement(tmp_path, spectra=False)
    settings.set_data_folders([tmp_path])
    window = MainWindow()
    window.show()
    try:
        window.pool.waitForDone(); app.processEvents()
        assert window.files.count() == 1
        assert "Chromatograms only" in window.files.item(0).toolTip()
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); app.processEvents()
        assert window.run_data is not None
        assert window.run_data.scans == ()
        assert window.run_data.tic, "declared TIC must still be plotted"
        window.region_timer.stop()
        window.calculate_region()
        window.pool.waitForDone(); app.processEvents()
        bars = [item for item in window.positive.items() if isinstance(item, pg.BarGraphItem)]
        assert not bars
        assert "no MS1 data" in window.positive.plotItem.titleLabel.text
    finally:
        window.close()


def test_multiple_mzml_locations_feed_one_sidebar(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    write_mzml(first / "first.mzML"); write_mzml(second / "second.mzML")
    settings.set_data_folders([first, second])
    window = MainWindow()
    try:
        window.pool.waitForDone(); app.processEvents()
        assert {window.files.item(index).data(Qt.ItemDataRole.UserRole) for index in range(window.files.count())} == {first / "first.mzML", second / "second.mzML"}
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
        assert item.data(Qt.ItemDataRole.UserRole + 1) == "source-only"
        cache = window.cache_for(remote)
        cache.parent.mkdir(); cache.touch()
        window.refresh_cache_indicators()
        assert item.data(Qt.ItemDataRole.UserRole + 1) == "source-cached"
        remote.unlink()
        window.refresh_cache_indicators()
        assert item.data(Qt.ItemDataRole.UserRole + 1) == "cache-only"
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
        window.load_progress(7, Path(__file__), "original local mzML", 50, 100)
        app.processEvents()
        assert window.progress.isVisible()
        assert window.progress.value() == 50
        assert window.progress.format() == "Loading original local mzML 50%"
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
        window.stream_tic = {path: []}
        window.streamed_uv_points(9, path, [(1.5, 42, 254)])
        window.streamed_tic_points(9, path, [(1.5, 120, "+"), (1.5, 80, "-")])
        QTest.qWait(100)
        app.processEvents()
        assert window.stream_uv[path] == [(1.5, 42, 254)]
        assert window.stream_tic[path] == [(1.5, 120, "+"), (1.5, 80, "-")]
        assert "streaming" in window.uv.plotItem.titleLabel.text.lower()
        assert "MS TIC" in window.uv.plotItem.titleLabel.text
        assert len(window.uv.tic_view.addedItems) == 2
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


def test_integration_table_calculates_percentages(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.integrations = [
            {"start_min": 1, "stop_min": 2, "wavelength_nm": 254, "absolute_integral": 2},
            {"start_min": 3, "stop_min": 4, "wavelength_nm": 280, "absolute_integral": 6},
        ]
        window.refresh_integration_table()
        assert window.integration_table.item(0, 4).text() == "25.00%"
        assert window.integration_table.item(1, 4).text() == "75.00%"
        assert window.uv.integration_enabled is False
    finally:
        window.close()
