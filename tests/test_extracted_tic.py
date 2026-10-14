import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.mzml import Run, Scan, extracted_tic
from bluelcms.sidebar import MeasurementItem


def test_extraction_includes_both_boundaries_and_preserves_polarities():
    shared = np.array([98., 100., 102., 104.])
    run = Run((), (
        Scan(2, "+", shared, np.array([1., 2., 3., 99.])),
        Scan(1, "-", shared, np.array([4., 5., 6., 99.])),
        Scan(3, "+", np.array([99., 103.]), np.array([7., 99.])),
        Scan(4, "?", np.array([100.]), np.array([99.])),
    ))
    assert extracted_tic(run, 100, 2) == ((1, 15., "-"), (2, 6., "+"), (3, 7., "+"))
    assert extracted_tic(run, 500, 2) == ((1, 0., "-"), (2, 0., "+"), (3, 0., "+"))
    assert extracted_tic(Run((), ()), 100, 2) == ()


@pytest.mark.parametrize("mass,radius", [(0, 2), (float("nan"), 2), (100, 0), (100, float("inf"))])
def test_extraction_rejects_invalid_windows(mass, radius):
    with pytest.raises(ValueError):
        extracted_tic(Run((), ()), mass, radius)


def test_enter_creates_overlay_and_right_click_changes_range_or_removes(tmp_path, monkeypatch):
    from bluelcms import app as app_module

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    window.show()
    path = tmp_path / "sample.mzML"
    item = MeasurementItem(path.name)
    item.setData(Qt.ItemDataRole.UserRole, path)
    window.files.addItem(item)
    window.files.blockSignals(True)
    item.setSelected(True)
    window.files.blockSignals(False)
    window.runs[path] = Run((), (
        Scan(1, "+", np.array([100., 200.]), np.array([2., 4.])),
        Scan(1, "-", np.array([100., 150.]), np.array([3., 5.])),
    ))
    def finish_extraction():
        window.pool.waitForDone(); application.processEvents()
        window.draw_uv()
    def right_click(button):
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), button.mapToGlobal(QPoint(5, 5)))
        QApplication.sendEvent(button, event)
    class TestMenu:
        def __init__(self, choice):
            self.choice = choice
            self.items = []
        def addAction(self, text):
            self.items.append(text)
            return text
        def exec(self, position):
            return self.items[self.choice]
    try:
        window.show_tic_positive.setChecked(False)
        window.show_tic_negative.setChecked(False)
        window.xic_input.setText("100")
        QTest.keyClick(window.xic_input, Qt.Key.Key_Return)
        finish_extraction()
        assert window.xic_buttons[100].text() == "100"
        assert window.xic_buttons[100].isChecked()
        assert window.xic_entries[100]["radius"] == 2
        curves = {curve.name(): curve for curve in window.uv.tic_view.addedItems}
        np.testing.assert_equal(curves["Extracted TIC 100 ±2 (+)"].getData()[1], [2])
        np.testing.assert_equal(curves["Extracted TIC 100 ±2 (-)"].getData()[1], [3])
        assert window.uv.getAxis("right").isVisible()
        window.xic_input.setText("100.0")
        QTest.keyClick(window.xic_input, Qt.Key.Key_Return)
        assert len(window.xic_buttons) == 1
        window.xic_buttons[100].setChecked(False)
        assert not window.uv.tic_view.addedItems
        assert not window.uv.getAxis("right").isVisible()
        window.xic_buttons[100].setChecked(True)
        monkeypatch.setattr(app_module, "QMenu", lambda parent: TestMenu(0))
        monkeypatch.setattr(app_module.QInputDialog, "getDouble", lambda *args: (100., True))
        right_click(window.xic_buttons[100])
        finish_extraction()
        curves = {curve.name(): curve for curve in window.uv.tic_view.addedItems}
        np.testing.assert_equal(curves["Extracted TIC 100 ±100 (+)"].getData()[1], [6])
        np.testing.assert_equal(curves["Extracted TIC 100 ±100 (-)"].getData()[1], [8])
        monkeypatch.setattr(app_module, "QMenu", lambda parent: TestMenu(1))
        right_click(window.xic_buttons[100])
        assert not window.xic_buttons and not window.xic_entries
        assert not window.uv.tic_view.addedItems
        assert settings.extracted_tics() == []
    finally:
        window.close()


def test_extracted_tic_buttons_and_ranges_persist(tmp_path, monkeypatch):
    from bluelcms import app as app_module

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    mass = 698.3912
    try:
        window.xic_input.setText(str(mass))
        window.add_xic_from_input()
        assert window.xic_buttons[mass].text() == "698.3912"
        monkeypatch.setattr(app_module.QInputDialog, "getDouble", lambda *args: (.25, True))
        window.change_xic_range(mass)
        window.xic_buttons[mass].setChecked(False)
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert reopened.xic_entries[mass]["radius"] == .25
        assert not reopened.xic_buttons[mass].isChecked()
    finally:
        reopened.close()
