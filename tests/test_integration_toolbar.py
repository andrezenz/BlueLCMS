import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow, cache_metadata
from bluelcms.folders import cached_path
from bluelcms.mzml import DADScan, Run, write_compact_cache
from test_aia import make_aia


def settle(window, app):
    for _ in range(6):
        window.pool.waitForDone(); app.processEvents()


def test_integration_toolbar_aia_channel_interval_and_record_actions(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    source = make_aia(tmp_path / "remote" / "sample.AIA")
    settings.set_data_folders([source]); settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        settle(window, app)
        assert window.toolBarBreak(window.integration_toolbar)
        assert window.toolBarArea(window.integration_toolbar) == Qt.ToolBarArea.TopToolBarArea
        assert not window.integrate_action.isEnabled()
        assert not window.remove_integration_action.isEnabled()
        assert not window.clear_integrations_action.isEnabled()
        window.files.setCurrentRow(0)
        settle(window, app)
        assert not window.integrate_action.isEnabled()  # B/C must not be mixed.
        window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData("DAD1B"))
        window.uv.region.setRegion((.55, .75))
        assert window.integrate_action.isEnabled()
        assert "DAD1B" in window.integration_selection_label.text()
        window.integrate_action.trigger()
        assert len(window.integrations) == 1
        assert window.integrations[0]["absolute_integral"] == pytest.approx(.225)
        assert window.integrations[0]["baseline"] == "midpoint"
        assert window.integrations[0]["baseline_start"] == pytest.approx(1)
        assert window.integrations[0]["baseline_end"] == pytest.approx(1)
        assert window.integrations[0]["channel"] == "DAD1B"
        window.uv.region.setRegion((.5, .6))
        window.integrate_action.trigger()
        assert len(window.integrations) == 2
        assert window.clear_integrations_action.isEnabled()
        window.integration_table.selectRow(0)
        assert window.remove_integration_action.isEnabled()
        window.remove_integration_action.trigger()
        assert len(window.integrations) == 1
        window.clear_integrations_action.trigger()
        assert not window.integrations
        assert not window.clear_integrations_action.isEnabled()
        assert not window.remove_integration_action.isEnabled()
        window.uv.region.setRegion((.6, .6))
        assert not window.integrate_action.isEnabled()
        window.show()
        window.integration_dock.hide()
        window.show_integrations_action.trigger()
        assert not window.integration_dock.isHidden()
        window.integration_dock.close()
        assert not window.show_integrations_action.isChecked()
        assert len(list((tmp_path / "integrations").glob("*.json"))) == 1
    finally:
        window.close(); app.processEvents()


def test_toolbar_native_uv_wavelength_heatmap_and_selection_state(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    settings.set_cache_folder(tmp_path / "cache")
    source = tmp_path / "offline.mzML"
    run = Run(tuple(DADScan(time, np.array([254.]), np.array([value]))
                    for time, value in ((0., 0.), (1., 2.), (2., 0.))), ())
    write_compact_cache(run, cached_path(source, settings.cache_folder()), cache_metadata(source))
    window = MainWindow()
    try:
        settle(window, app)
        window.files.setCurrentRow(0)
        settle(window, app)
        window.uv.region.setRegion((.5, 1.5))
        assert window.integrate_action.isEnabled()
        window.integrate_action.trigger()
        assert window.integrations[0]["absolute_integral"] == pytest.approx(.5)
        assert window.integrations[0]["wavelength_nm"] == 254
        window.wavelength.setValue(280)
        assert not window.integrate_action.isEnabled()
        window.wavelength.setValue(254)
        assert window.integrate_action.isEnabled()
        window.mode.setCurrentText("DAD heatmap")
        assert not window.integrate_action.isEnabled()
        window.mode.setCurrentText("UV traces")
        assert window.integrate_action.isEnabled()
        window.files.clearSelection()
        assert not window.integrate_action.isEnabled()
    finally:
        window.close(); app.processEvents()


def test_baseline_points_and_limits_can_be_dragged_and_saved(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    settings.set_cache_folder(tmp_path / "cache")
    source = tmp_path / "offline.mzML"
    run = Run(tuple(DADScan(time, np.array([254.]), np.array([value]))
                    for time, value in ((0., 0.), (1., 2.), (2., 0.))), ())
    write_compact_cache(run, cached_path(source, settings.cache_folder()), cache_metadata(source))
    window = MainWindow()
    try:
        settle(window, app); window.files.setCurrentRow(0); settle(window, app)
        window.uv.region.setRegion((.5, 1.5))
        editor = window.uv.baseline_editor
        assert editor.points[0].pos().y() == 1
        assert editor.points[1].pos().y() == 1
        editor.points[0].setPos(.25, 1.25)
        editor.points[1].setPos(1.75, 1.75)
        editor.finish_edit()
        assert window.uv.region.getRegion() == (.25, 1.75)
        window.integrate_action.trigger()
        record = window.integrations[0]
        assert record["baseline"] == "manual"
        assert record["baseline_start"] == 1.25 and record["baseline_end"] == 1.75
        assert record["absolute_integral"] == pytest.approx(.375)
        window.reset_baseline_action.trigger()
        assert editor.points[0].pos().y() == pytest.approx(.5)
        window.uv.region.lines[0].setValue(.5)
        assert editor.points[0].pos().y() == pytest.approx(.75)
    finally:
        window.close(); app.processEvents()
