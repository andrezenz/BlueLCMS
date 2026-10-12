import os
import subprocess
import sys
import time
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.external import OpenRequest, OpenRequestServer, parse_request
from test_mzml import write_mzml


def test_parse_external_request_normalizes_path_and_options(tmp_path):
    request = parse_request(["--open", str(tmp_path / "sample.mzML"), "--start", "1", "--end", "2", "--polarity", "positive", "--wavelength", "254"])
    assert request.polarity == "+"
    assert request.start == 1 and request.end == 2
    assert OpenRequest.decode(request.encode()) == request


@pytest.mark.parametrize("options", [["--start", "1"], ["--start", "nan", "--end", "2"], ["--start", "2", "--end", "1"], ["--time", "1", "--start", "1", "--end", "2"]])
def test_invalid_external_intervals_are_rejected(tmp_path, options):
    with pytest.raises(SystemExit):
        parse_request(["--open", str(tmp_path / "sample.mzML"), *options])


def test_running_instance_receives_request_from_another_process(tmp_path):
    application = QApplication.instance() or QApplication([])
    server = OpenRequestServer()
    name = "BlueLCMS-test-" + uuid.uuid4().hex
    received = []
    server.requested.connect(received.append)
    assert server.listen(name)
    source = tmp_path / "sample.mzML"
    code = "from bluelcms.external import OpenRequest, forward_request; from PySide6.QtCore import QCoreApplication; import sys; app = QCoreApplication([]); sys.exit(0 if forward_request(OpenRequest(sys.argv[1]), sys.argv[2], 5000) else 1)"
    process = subprocess.Popen([sys.executable, "-c", code, str(source), name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while process.poll() is None and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert process.poll() == 0, process.communicate(timeout=1)
        assert received == [OpenRequest(str(source))]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
        server.close()


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No, QMessageBox.StandardButton.Cancel])
def test_open_outside_sources_prompts_and_applies_cache_choice(tmp_path, monkeypatch, answer):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    cache = tmp_path / "cache"
    settings.set_cache_folder(cache)
    source = write_mzml(tmp_path / "external.mzML")
    window = MainWindow()
    prompts = []
    def question(*args):
        prompts.append(args)
        return answer
    monkeypatch.setattr(QMessageBox, "question", question)
    try:
        window.pool.waitForDone(); application.processEvents()
        request = OpenRequest(str(source), time=1, polarity="+")
        window.open_external(request)
        for _ in range(4):
            window.pool.waitForDone(); application.processEvents()
        assert len(prompts) == 1
        if answer == QMessageBox.StandardButton.Cancel:
            assert window.files.count() == 0
            assert window.run_data is None
        else:
            assert window.files.selectedItems()[0].data(Qt.ItemDataRole.UserRole) == source
            assert window.run_data is not None
            assert window.uv.region.getRegion() == (1, 1)
            assert window.cache_for(source).is_file() == (answer == QMessageBox.StandardButton.Yes)
            window.refresh_files(background=True)
            window.pool.waitForDone(); application.processEvents()
            assert window.files.count() == 1
    finally:
        window.close()


def test_external_open_uses_existing_cache_without_prompt(tmp_path, monkeypatch):
    from bluelcms.app import cache_metadata
    from bluelcms.folders import cached_path
    from bluelcms.mzml import load_run, write_compact_cache

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    cache = tmp_path / "cache"
    settings.set_cache_folder(cache)
    source = write_mzml(tmp_path / "external.mzML")
    write_compact_cache(load_run(source), cached_path(source, cache), cache_metadata(source))
    source.unlink()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Cached files must not prompt again"))
    window = MainWindow()
    try:
        window.pool.waitForDone(); application.processEvents()
        window.open_external(OpenRequest(str(source)))
        for _ in range(3):
            window.pool.waitForDone(); application.processEvents()
        assert window.run_data is not None
        assert window.files.count() == 1
    finally:
        window.close()


@pytest.mark.parametrize("choose_folder", [True, False])
def test_external_cache_choice_requires_a_folder_before_opening(tmp_path, monkeypatch, choose_folder):
    from bluelcms import app as app_module

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    source = write_mzml(tmp_path / "external.mzML")
    cache = tmp_path / "cache"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(app_module.QFileDialog, "getExistingDirectory", lambda *args: str(cache) if choose_folder else "")
    window = MainWindow()
    try:
        window.open_external(OpenRequest(str(source)))
        for _ in range(4):
            window.pool.waitForDone(); application.processEvents()
        if choose_folder:
            assert settings.cache_folder() == cache
            assert window.cache_for(source).is_file()
            assert window.run_data is not None
        else:
            assert settings.cache_folder() is None
            assert window.files.count() == 0
            assert window.run_data is None
    finally:
        window.close()
