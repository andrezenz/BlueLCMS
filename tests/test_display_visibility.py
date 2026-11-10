import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.mzml import DADScan, Run, Scan


@pytest.mark.parametrize("mode", ("UV traces", "DAD heatmap"))
def test_uv_selection_respects_spectrum_toggle(tmp_path, monkeypatch, mode):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    settings.set_uv_spectrum_at_cursor(False)
    window = MainWindow()
    try:
        run = Run(tuple(DADScan(time, np.array([250., 254., 260.]), np.array([1., 2., 3.]))
                        for time in (0., 1., 2.)),
                  tuple(Scan(1., polarity, np.array([500.]), np.array([100.])) for polarity in ("+", "-")))
        window.runs = {tmp_path / "sample.mzML": run}
        window.mode.setCurrentText(mode)
        window.uv.region.setBounds((0., 2.))
        window.uv.region.show()
        selected = []
        monkeypatch.setattr(window, "calculate_region", lambda: selected.append(window.uv.region.getRegion()))
        click = window.select_uv_trace_time if mode == "UV traces" else window.select_dad_heatmap_time
        click(1.)
        assert selected[-1] == (1., 1.)
        assert window.uv_spectrum_dock.isHidden()
        # Dragging/selecting an interval must also leave the disabled dock hidden.
        window.uv.region.setRegion((.5, 1.5))
        window.timer.stop()
        window.calculate_region()
        assert window.uv_spectrum_dock.isHidden()
        window.show()
        window.set_uv_spectrum_at_cursor(True)
        click(1.)
        assert not window.uv_spectrum_dock.isHidden()
        np.testing.assert_array_equal(window.uv_spectrum_curve.getData()[1], [1., 2., 3.])
        window.set_uv_spectrum_at_cursor(False)
        assert not window.uv_spectrum_action.isChecked()
        click(1.)
        assert window.uv_spectrum_dock.isHidden()
    finally:
        window.close()
        app.processEvents()


def test_mass_spectrum_display_actions_persist_independently(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        display = next(action.menu() for action in window.menuBar().actions() if action.text() == "Display")
        assert all(action in display.actions() for action in window.mass_spectrum_actions.values())
        assert all(action.isChecked() for action in window.mass_spectrum_actions.values())
        window.mass_spectrum_actions["+"].setChecked(False)
        assert window.positive.isHidden()
        assert not window.negative.isHidden()
        assert not window.mass_splitter.isHidden()
        window.mass_spectrum_actions["-"].setChecked(False)
        assert window.mass_splitter.isHidden()
        window.mass_spectrum_actions["+"].setChecked(True)
        assert not window.mass_splitter.isHidden()
        assert not window.positive.isHidden()
        assert window.negative.isHidden()
    finally:
        window.close()
        app.processEvents()
    restarted = MainWindow()
    try:
        assert restarted.mass_spectrum_actions["+"].isChecked()
        assert not restarted.mass_spectrum_actions["-"].isChecked()
        assert not restarted.positive.isHidden()
        assert restarted.negative.isHidden()
        restarted.mass_spectrum_actions["-"].setChecked(True)
        assert not restarted.negative.isHidden()
    finally:
        restarted.close()
        app.processEvents()
