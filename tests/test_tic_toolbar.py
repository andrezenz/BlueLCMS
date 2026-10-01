import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow


def test_tic_toolbar_preference_is_overridden_while_streaming(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        window.show_tic.setChecked(False)
        assert not window.show_tic.isChecked()
        assert settings.show_tic() is False
        window.stream_tic = {tmp_path / "remote.mzML": [(1, 10, "+")]}
        window.draw_uv()
        assert window.uv.getAxis("right").isVisible()
        window.stream_tic = {}
        window.draw_uv()
        assert not window.uv.getAxis("right").isVisible()
    finally:
        window.close()
