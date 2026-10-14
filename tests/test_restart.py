import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from bluelcms import app as app_module, settings
from bluelcms.app import LoadJob, MainWindow


@pytest.mark.parametrize("kind", ["source", "package", "installer"])
def test_update_restart_explicitly_closes_original_window(tmp_path, monkeypatch, kind):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    events = []
    monkeypatch.setattr(QApplication, "quit", lambda: events.append("quit"))
    monkeypatch.setattr(app_module, "start_packaged_process", lambda executable, args: events.append((executable, args)) or True)
    monkeypatch.setattr(app_module.QProcess, "startDetached", lambda executable, args: events.append((executable, args)) or (True, 123))
    monkeypatch.setattr(app_module.updater, "repository_root", lambda: tmp_path)
    class Broker:
        def close(self):
            events.append("release IPC")
        def listen(self):
            events.append("restore IPC")
    window = MainWindow()
    window.open_request_server = Broker()
    window.show()
    try:
        if kind == "source":
            window.updated(0, {"branch": "dev", "commit": "new"}, "")
        else:
            result = {"version": "v1.0.2-dev.8", "executable": str(tmp_path / "BlueLCMS")}
            if kind == "installer":
                result["helper"] = str(tmp_path / "install.ps1")
            window.package_updated(0, result, "")
        assert events[0] == "release IPC"
        assert isinstance(events[1], tuple), "launch after releasing the old IPC endpoint"
        assert events[-1] == "quit"
        assert window.closing
        assert not window.isVisible()
        assert not window.source_refresh_timer.isActive()
        assert not window.stream_timer.isActive()
        assert not window.loading_timer.isActive()
        assert not window.timer.isActive()
        assert not window.histogram_redraw.isActive()
    finally:
        window.close()


def test_failed_restart_preserves_current_session_and_restores_ipc(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(app_module.QProcess, "startDetached", lambda *args: (False, 0))
    events = []
    class Broker:
        def close(self):
            events.append("close")
        def listen(self):
            events.append("listen")
    window = MainWindow()
    window.open_request_server = Broker()
    window.show()
    try:
        assert not window.restart_application("missing-executable", [])
        assert not window.closing
        assert window.isVisible()
        assert window.source_refresh_timer.isActive()
        assert events == ["close", "listen"]
    finally:
        window.close()


def test_shutdown_cancels_paused_loader_instead_of_waiting_forever(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    path = tmp_path / "remote.mzML"
    job = LoadJob(1, path, 254)
    entered = Event()
    def paused_reader(path, progress, **kwargs):
        job.pause()
        entered.set()
        progress(1, 2)
        pytest.fail("The cancelled reader must not continue parsing")
    monkeypatch.setattr(app_module, "load_run", paused_reader)
    window.load_jobs[path] = job
    window.jobs.add(job)
    window.pool.start(job)
    try:
        assert entered.wait(2)
        window.close()
        assert job.cancelled.is_set()
        assert window.pool.activeThreadCount() == 0
        assert window.closing
        window.loaded(window.load_token, path, None, "Loading cancelled")
        assert path not in window.failed_loads
    finally:
        job.cancel()
        window.close()
