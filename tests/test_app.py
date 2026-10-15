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


def test_new_file_alerts_once_and_preference_persists(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    folder = tmp_path / "remote"
    folder.mkdir()
    source = write_mzml(folder / "original.mzML")
    settings.set_data_folders([folder])
    alerts = []
    monkeypatch.setattr(MainWindow, "notify_new_measurements", lambda self, paths: alerts.append(set(paths)))
    window = MainWindow()
    def rescan():
        window.refresh_files(background=True)
        window.pool.waitForDone(); application.processEvents()
    try:
        window.pool.waitForDone(); application.processEvents()
        assert window.alert_new_measurements.isChecked()
        assert not alerts, "initial discovery establishes the baseline"
        window.files.setCurrentRow(0)
        window.pool.waitForDone(); application.processEvents()
        original_run = window.run_data
        nested = folder / "batch"
        nested.mkdir()
        added = write_mzml(nested / "new.mzML")
        rescan()
        assert alerts == [{added}]
        assert window.run_data is original_run
        assert window.files.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == source
        rescan()
        assert alerts == [{added}], "unchanged files must not alert again"
        added.unlink()
        rescan()
        write_mzml(added)
        rescan()
        assert alerts == [{added}], "a returning known file must not alert again"
        window.alert_new_measurements.setChecked(False)
        write_mzml(folder / "silent.mzML")
        rescan()
        assert alerts == [{added}]
        assert not settings.alert_new_measurements()
        window.alert_new_measurements.setChecked(True)
        rescan()
        assert alerts == [{added}], "re-enabling alerts must not announce old arrivals"
        window.alert_new_measurements.setChecked(False)
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert not reopened.alert_new_measurements.isChecked()
    finally:
        reopened.close()


def test_new_measurement_notification_restores_and_requests_focus_on_non_linux(tmp_path, monkeypatch):
    from bluelcms import app as app_module
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    called = []
    monkeypatch.setattr(window, "isMinimized", lambda: True)
    monkeypatch.setattr(window, "showNormal", lambda: called.append("restore"))
    monkeypatch.setattr(window, "raise_", lambda: called.append("raise"))
    monkeypatch.setattr(window, "activateWindow", lambda: called.append("activate"))
    monkeypatch.setattr(QApplication, "alert", lambda widget, duration: called.append((widget, duration)))
    try:
        window.notify_new_measurements({tmp_path / "new.mzML"})
        assert called == ["restore", "raise", "activate", (window, 5000)]
        assert "new.mzML" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_notification_failure_does_not_request_linux_window_focus(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    class Notifier:
        activated = type("SignalStub", (), {"connect": lambda self, callback: None})()
        failed = type("SignalStub", (), {"connect": lambda self, callback: None})()
        def show(self, *args):
            return False
        def close(self):
            pass
    monkeypatch.setattr(window, "focus_new_results", lambda: pytest.fail("Linux notification failure must not trigger the generic ready alert"))
    monkeypatch.setattr("bluelcms.app.DesktopNotifications", lambda parent: Notifier())
    try:
        window.notify_new_measurements({tmp_path / "sample.mzML"})
        assert "New measurement found" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_remote_reconnect_announces_only_genuinely_new_files(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    remote = tmp_path / "remote"
    remote.mkdir()
    write_mzml(remote / "original.mzML")
    settings.set_data_folders([remote])
    alerts = []
    monkeypatch.setattr(MainWindow, "notify_new_measurements", lambda self, paths: alerts.append(set(paths)))
    window = MainWindow()
    try:
        window.pool.waitForDone(); application.processEvents()
        disconnected = tmp_path / "disconnected"
        remote.rename(disconnected)
        window.refresh_files(background=True)
        window.pool.waitForDone(); application.processEvents()
        assert not alerts
        disconnected.rename(remote)
        added = write_mzml(remote / "added-while-disconnected.mzML")
        window.refresh_files(background=True)
        window.pool.waitForDone(); application.processEvents()
        assert alerts == [{added}]
    finally:
        window.close()


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


def test_measurements_within_each_folder_sort_newest_date_first(tmp_path):
    from bluelcms.sidebar import MeasurementTree

    app = QApplication.instance() or QApplication([])
    root = tmp_path / "remote"
    folder = root / "batch"
    folder.mkdir(parents=True)
    tree = MeasurementTree()
    tree.set_roots([root])
    for filename in ("2026_01_03_new.mzML", "2026_10_14_latest.mzML", "2025_12_31_old.mzML", "undated.mzML"):
        item = QListWidgetItem(filename)
        item.setData(Qt.ItemDataRole.UserRole, folder / filename)
        tree.addItem(item)
    parent = tree.item(0).parent()
    assert [parent.child(index).text() for index in range(parent.childCount())] == [
        "2026_10_14_latest.mzML", "2026_01_03_new.mzML", "2025_12_31_old.mzML", "undated.mzML"]


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
    settings.set_last_changelog_version(QApplication.applicationVersion())
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


def test_startup_shows_changelog_once_for_each_new_app_version(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    shown = []
    monkeypatch.setattr(window, "show_changelog", lambda: shown.append(QApplication.applicationVersion()))
    try:
        application.setApplicationVersion("1.0.2.dev21")
        assert window.show_changelog_for_new_version()
        assert not window.show_changelog_for_new_version()
        application.setApplicationVersion("1.0.2.dev22")
        assert window.show_changelog_for_new_version()
        assert shown == ["1.0.2.dev21", "1.0.2.dev22"]
    finally:
        window.close()


def test_dad_heatmap_sensitivity_palette_and_persistence(tmp_path, monkeypatch):
    from bluelcms.mzml import DADScan, Run
    from bluelcms.views import heatmap_levels

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    matrix = np.array([[0., 1.], [2., 100.]])
    assert heatmap_levels(matrix, 75) == pytest.approx((0.0, 26.5))
    window = MainWindow()
    try:
        window.runs["heatmap"] = Run((
            DADScan(0., np.array([250., 254.]), np.array([0., 1.])),
            DADScan(1., np.array([250., 254.]), np.array([2., 100.])),
        ), ())
        window.mode.setCurrentText("DAD heatmap")
        assert not window.heatmap_sensitivity.isHidden()
        assert not window.heatmap_palette.isHidden()
        window.heatmap_sensitivity.setValue(75)
        window.heatmap_palette.setCurrentIndex(window.heatmap_palette.findData("inferno"))
        image = next(item for item in window.uv.items() if isinstance(item, pg.ImageItem))
        assert image.getLevels()[1] == pytest.approx(26.5)
        assert settings.dad_heatmap_palette() == "inferno"
        window.heatmap_palette.setCurrentIndex(window.heatmap_palette.findData("grey"))
        image = next(item for item in window.uv.items() if isinstance(item, pg.ImageItem))
        assert np.asarray(image.lut).shape[1] == 3
        window.close()
        reopened = MainWindow()
        assert reopened.heatmap_sensitivity.value() == 75
        assert reopened.heatmap_palette.currentData() == "grey"
        reopened.close()
    finally:
        if window.isVisible():
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

    def cancel(self):
        self.resume()


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


def test_mass_x_axis_wheel_zoom_anchors_cursor_and_leaves_intensity_unchanged():
    from PySide6.QtWidgets import QGraphicsSceneWheelEvent
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.setXRange(100, 200, padding=0)
        plot.setYRange(0, 100, padding=0)
        application.processEvents()
        axis = plot.getAxis("bottom")
        scene_x = plot.view.mapViewToScene(QPointF(125, 50)).x()
        scene_y = plot.view.sceneBoundingRect().bottom() + 10
        wheel = QGraphicsSceneWheelEvent()
        wheel.setScenePos(QPointF(scene_x, scene_y))
        wheel.setDelta(120)
        axis.wheelEvent(wheel)
        np.testing.assert_allclose(plot.view.viewRange()[0], [102.5, 192.5])
        np.testing.assert_allclose(plot.view.viewRange()[1], [0, 100])
        wheel.setDelta(-120)
        axis.wheelEvent(wheel)
        np.testing.assert_allclose(plot.view.viewRange()[0], [100, 200])
        wheel.setScenePos(plot.view.mapViewToScene(QPointF(125, 50)))
        plot.view.wheelEvent(wheel)
        np.testing.assert_allclose(plot.view.viewRange()[0], [100, 200])
        np.testing.assert_allclose(plot.view.viewRange()[1], [0, 100 / .9])
    finally:
        plot.close()


def test_mass_hover_guideline_survives_redraw_without_changing_ranges():
    from PySide6.QtCore import QPointF, QEvent
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.setXRange(690, 710, padding=0)
        plot.setYRange(0, 100, padding=0)
        application.processEvents()
        plot.scene().sigMouseMoved.emit(plot.view.mapViewToScene(QPointF(698.3912, 50)))
        assert plot.cursor_line.isVisible()
        assert plot.cursor_line.value() == pytest.approx(698.3912)
        assert plot.cursor_line.label.toPlainText() == "m/z 698.3912"
        before = np.asarray(plot.view.viewRange())
        plot.clear()
        assert plot.cursor_line in plot.items()
        plot.scene().sigMouseMoved.emit(plot.view.mapViewToScene(QPointF(702.1, 50)))
        assert plot.cursor_line.value() == pytest.approx(702.1)
        np.testing.assert_allclose(plot.view.viewRange(), before)
        plot.scene().sigMouseMoved.emit(QPointF(-10, -10))
        assert not plot.cursor_line.isVisible()
        plot.scene().sigMouseMoved.emit(plot.view.mapViewToScene(QPointF(702.1, 50)))
        QApplication.sendEvent(plot, QEvent(QEvent.Type.Leave))
        assert not plot.cursor_line.isVisible()
    finally:
        plot.close()


def test_mass_click_pins_exact_loss_guidelines_with_contrast_tiers():
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.setXRange(650, 720, padding=0)
        plot.setYRange(0, 100, padding=0)
        application.processEvents()
        before = np.asarray(plot.view.viewRange())
        position = plot.mapFromScene(plot.view.mapViewToScene(QPointF(700, 50)))
        QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
        application.processEvents()
        assert plot.reference_mass == pytest.approx(700, abs=.1)
        offsets = [0, 17.026549101, 22.989220702, 34.053098202, 45.978441404, 40.015769803,
                   -17.026549101, -22.989220702, -34.053098202, -45.978441404, -40.015769803]
        np.testing.assert_allclose([plot.reference_mass - line.value() for line in plot.reference_lines], offsets)
        alpha = [line.pen.color().alpha() for line in plot.reference_lines]
        assert plot.cursor_line.pen.color().alpha() > alpha[1] == alpha[2] > alpha[3] == alpha[4] == alpha[5]
        assert all(not line.label.isVisible() for line in plot.reference_lines)
        reference = plot.reference_mass
        plot.update_reference_hover(plot.view.mapViewToScene(QPointF(700, 50)))
        assert plot.reference_lines[0].label.isVisible()
        assert all(not line.label.isVisible() for line in plot.reference_lines[1:])
        plot.update_reference_hover(plot.view.mapViewToScene(QPointF(700 - plot.NH3_MASS, 50)))
        assert plot.reference_lines[1].label.isVisible()
        assert not plot.reference_lines[0].label.isVisible()
        assert "−NH₃" in plot.reference_lines[1].label.toPlainText()
        plot.update_reference_hover(plot.view.mapViewToScene(QPointF(698, 50)))
        assert all(not line.label.isVisible() for line in plot.reference_lines)
        plot.update_reference_hover(plot.view.mapViewToScene(QPointF(700 + plot.NH3_MASS, 50)))
        assert plot.reference_lines[6].label.isVisible()
        assert "+NH₃" in plot.reference_lines[6].label.toPlainText()
        plot.move_cursor(plot.view.mapViewToScene(QPointF(690, 50)))
        assert plot.reference_mass == reference
        plot.clear()
        assert all(line in plot.items() for line in plot.reference_lines)
        np.testing.assert_allclose(plot.view.viewRange(), before)
        plot.set_mass_reference(710)
        assert len(plot.reference_lines) == 11
        assert plot.reference_lines[0].value() == 710
    finally:
        plot.close()


def test_mass_drag_previews_horizontal_zoom_range():
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.setXRange(100, 200, padding=0)
        plot.setYRange(0, 100, padding=0)
        application.processEvents()
        def point(mass):
            return plot.mapFromScene(plot.view.mapViewToScene(QPointF(mass, 50)))
        QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, pos=point(120))
        for mass in (140, 160):
            QTest.qWait(30)
            position = QPointF(point(mass))
            event = QMouseEvent(QEvent.Type.MouseMove, position,
                QPointF(plot.viewport().mapToGlobal(point(mass))),
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(plot.viewport(), event)
            application.processEvents()
        assert plot.zoom_region.isVisible()
        np.testing.assert_allclose(plot.zoom_region.getRegion(), [120, 160], atol=.2)
        np.testing.assert_allclose(plot.view.viewRange()[0], [100, 200])
        plot.clear()
        assert plot.zoom_region in plot.items()
        QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, pos=point(160))
        application.processEvents()
        assert not plot.zoom_region.isVisible()
        assert plot.reference_mass is None
        np.testing.assert_allclose(plot.view.viewRange()[0], [120, 160], atol=.2)
        np.testing.assert_allclose(plot.view.viewRange()[1], [0, 100])
    finally:
        plot.close()


def test_mass_snapping_uses_combined_histogram_peaks_and_configured_radius():
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.setXRange(690, 720, padding=0)
        plot.setYRange(0, 100, padding=0)
        application.processEvents()
        plot.data = [(np.array([700.]), np.array([1e8]))]
        plot.snap_data = [(np.array([698.4, 701, 708]), np.array([8, 15, 1e6])),
                          (np.array([698.4, 702]), np.array([8, 1]))]
        plot.set_cursor_snapping(True, 5)
        assert plot.snapped_mass(700) == pytest.approx(698.4)
        plot.move_cursor(plot.view.mapViewToScene(QPointF(700, 50)))
        assert plot.cursor_line.value() == pytest.approx(698.4)
        plot.view.mass_clicked.emit(700)
        assert plot.reference_mass == pytest.approx(698.4)
        assert plot.snapped_mass(715) == 715
        plot.set_cursor_snapping(True, .25)
        assert plot.snapped_mass(700) == 700
        assert plot.snapped_mass(701.1) == 701
        plot.set_cursor_snapping(False, 5)
        assert plot.snapped_mass(700) == 700
    finally:
        plot.close()


def test_pixel_snap_window_narrows_in_mz_when_zooming_in():
    from bluelcms.views import MassPlot

    application = QApplication.instance() or QApplication([])
    plot = MassPlot("Positive ions")
    plot.resize(800, 400)
    plot.show()
    try:
        plot.snap_data = [(np.array([699.8]), np.array([100.]))]
        plot.set_cursor_snapping(True, 10, "pixels")
        plot.setXRange(690, 710, padding=0)
        application.processEvents()
        wide_radius = plot.snap_radius_in_mz()
        assert wide_radius > .2
        assert plot.snapped_mass(700) == pytest.approx(699.8)
        plot.setXRange(699, 701, padding=0)
        application.processEvents()
        narrow_radius = plot.snap_radius_in_mz()
        assert narrow_radius < .4
        assert narrow_radius < wide_radius
        assert plot.snapped_mass(700) == 700
    finally:
        plot.close()


def test_mass_cursor_snapping_preferences_persist(tmp_path, monkeypatch):
    from bluelcms.app import MassCursorSnapDialog
    from PySide6.QtWidgets import QDialog

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        assert settings.mass_cursor_snap_unit() == "pixels"
        assert settings.mass_cursor_snap_range() == 10
        window.snap_mass_cursor.setChecked(True)
        assert window.positive.snap_enabled and window.negative.snap_enabled
        dialogs = []
        def accept(dialog):
            dialogs.append(dialog)
            dialog.units.setCurrentIndex(dialog.units.findData("mz"))
            dialog.range.setValue(1.5)
            dialog.units.setCurrentIndex(dialog.units.findData("pixels"))
            dialog.range.setValue(12)
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(MassCursorSnapDialog, "exec", accept)
        window.configure_mass_cursor_snapping()
        assert dialogs[0].units.currentData() == "pixels"
        assert window.positive.snap_range == window.negative.snap_range == 12
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert reopened.snap_mass_cursor.isChecked()
        assert reopened.positive.snap_enabled and reopened.negative.snap_enabled
        assert reopened.positive.snap_range == reopened.negative.snap_range == 12
        assert reopened.positive.snap_unit == reopened.negative.snap_unit == "pixels"
        assert settings.mass_cursor_snap_range("mz") == 1.5
        menu = next(action.menu() for action in reopened.menuBar().actions() if action.text() == "Settings")
        menu_texts = [action.text() for action in menu.actions()]
        assert "Choose mounted remote folder…" not in menu_texts
        assert "Mass cursor snapping…" in menu_texts
        assert "Mass cursor snap units…" not in menu_texts
    finally:
        reopened.close()


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


def test_streamed_uv_points_draw_before_run_completion(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
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
