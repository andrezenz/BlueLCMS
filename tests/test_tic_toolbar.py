import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.mzml import Run
from bluelcms.sidebar import MeasurementItem
from PySide6.QtCore import Qt


def test_tic_buttons_are_independent_persistent_and_respected_while_streaming(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        path = tmp_path / "remote.mzML"
        item = MeasurementItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        window.files.addItem(item)
        window.files.blockSignals(True)
        item.setSelected(True)
        window.files.blockSignals(False)
        window.runs[path] = Run((), (), tic=((1, 10, "+"), (1, 20, "-")))
        window.draw_uv()
        assert {curve.name() for curve in window.uv.tic_view.addedItems} == {"MS TIC (+)", "MS TIC (-)"}
        window.show_tic_positive.setChecked(False)
        assert settings.show_tic("+") is False
        assert settings.show_tic("-") is True
        assert {curve.name() for curve in window.uv.tic_view.addedItems} == {"MS TIC (-)"}
        window.runs.clear()
        window.stream_uv = {path: []}
        window.stream_tic = {path: [(1, 10, "+"), (1, 20, "-")]}
        window.draw_uv()
        assert window.uv.getAxis("right").isVisible()
        assert {curve.name() for curve in window.uv.tic_view.addedItems} == {"MS TIC (-)"}
        window.show_tic_negative.setChecked(False)
        assert not window.uv.getAxis("right").isVisible()
        assert not window.uv.tic_view.addedItems
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert not reopened.show_tic_positive.isChecked()
        assert not reopened.show_tic_negative.isChecked()
    finally:
        reopened.close()


def test_old_tic_preference_initializes_both_buttons(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    settings.set_show_tic(False)
    window = MainWindow()
    try:
        assert not window.show_tic_positive.isChecked()
        assert not window.show_tic_negative.isChecked()
    finally:
        window.close()
