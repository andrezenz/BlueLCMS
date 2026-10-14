import os
import tomllib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.help import DocumentDialog, document_text


def test_changelog_matches_declared_version_and_help_contains_actual_options():
    root = Path(__file__).parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert f"## {version}" in document_text("CHANGELOG.md")
    help_text = document_text("EXTERNAL_COMMANDS.md")
    for option in ("--open", "--start", "--end", "--time", "--polarity", "--wavelength"):
        assert option in help_text
    assert "PowerShell" in help_text
    assert "subprocess.Popen" in help_text


def test_about_actions_display_offline_documents(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    shown = []
    def open_dialog(dialog):
        shown.append((dialog.windowTitle(), dialog.browser.toPlainText()))
        return 0
    monkeypatch.setattr(DocumentDialog, "exec", open_dialog)
    window = MainWindow()
    try:
        menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "About")
        actions = {action.text(): action for action in menu.actions()}
        actions["Changelog…"].trigger()
        actions["External program commands…"].trigger()
        assert shown[0][0] == "BlueLCMS changelog"
        assert "vertical cursor guideline" in shown[0][1]
        assert shown[1][0] == "BlueLCMS external program commands"
        assert "--open" in shown[1][1]
    finally:
        application.processEvents()
        window.close()
