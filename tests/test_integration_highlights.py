import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow, cache_metadata
from bluelcms.folders import cached_path
from bluelcms.mzml import DADScan, Run, write_compact_cache
from bluelcms.views import IntegrationAreaItem
from test_aia import make_aia
from test_aia_ui import settle


def test_saved_uv_windows_visibility_selection_redraw_and_wavelength(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    settings.set_cache_folder(tmp_path / "cache")
    source = tmp_path / "offline.mzML"
    run = Run(tuple(DADScan(float(time), np.array([254., 280.]), np.array([value, 2 * value]))
                    for time, value in ((0, 0), (1, 2), (2, 3), (3, 0))), ())
    write_compact_cache(run, cached_path(source, settings.cache_folder()), cache_metadata(source))
    window = MainWindow()
    try:
        window.show(); settle(window, app)
        window.files.setCurrentRow(0); settle(window, app)
        window.integrations = [
            {"start_min": .25, "stop_min": .75, "wavelength_nm": 254, "absolute_integral": 1},
            {"start_min": 1.25, "stop_min": 1.75, "wavelength_nm": 254, "absolute_integral": 2},
            {"start_min": 2.25, "stop_min": 2.75, "wavelength_nm": 280, "absolute_integral": 3},
        ]
        window.refresh_integration_table()
        assert not window.uv.integration_highlights
        window.show_integrations_action.trigger()
        items = window.uv.integration_highlights
        assert [item.getRegion() for item in items] == [(.25, .75), (1.25, 1.75)]
        muted_alpha = items[0].brush().color().alpha()
        assert muted_alpha >= 60
        assert all(item.acceptedMouseButtons() == Qt.MouseButton.NoButton for item in items)
        window.uv.region.setRegion((.1, 2.9))
        region, token = window.uv.region.getRegion(), window.region_token
        window.integration_table.selectRow(1)
        items = window.uv.integration_highlights
        assert items[1].brush().color().alpha() > muted_alpha
        assert items[1].zValue() > items[0].zValue()
        assert window.uv.region.getRegion() == (1.25, 1.75)
        assert window.uv.baseline_editor.points[0].isVisible()
        assert window.editing_integration_row == 1
        assert window.integrate_action.text() == "Update integral"
        window.draw_uv()
        assert len(window.uv.integration_highlights) == 2
        assert len([item for item in window.uv.plotItem.items if isinstance(item, IntegrationAreaItem)]) == 2
        window.wavelength.setValue(280)
        assert [item.getRegion() for item in window.uv.integration_highlights] == [(2.25, 2.75)]
        window.mode.setCurrentText("DAD heatmap")
        assert not window.uv.integration_highlights
        window.mode.setCurrentText("UV traces")
        assert len(window.uv.integration_highlights) == 1
        window.integration_dock.close()
        assert not window.show_integrations_action.isChecked()
        assert not window.uv.integration_highlights
        assert len(window.integrations) == 3
    finally:
        window.close(); app.processEvents()


def test_aia_highlights_channel_filtering_add_remove_clear_and_deselect(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    source = make_aia(tmp_path / "sample.AIA")
    settings.set_data_folders([source]); settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        window.show(); settle(window, app)
        window.files.setCurrentRow(0); settle(window, app)
        for channel in ("DAD1B", "DAD1C"):
            window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData(channel))
            window.uv.region.setRegion((.55, .75))
            window.integrate_action.trigger()
            window.integrate_action.trigger()
        assert window.show_integrations_action.isChecked()
        assert len(window.uv.integration_highlights) == 1
        window.chromatogram_channel.setCurrentIndex(0)
        assert len(window.uv.integration_highlights) == 2
        window.integration_table.selectRow(1)
        assert window.uv.integration_highlights[1].brush().color().alpha() > window.uv.integration_highlights[0].brush().color().alpha()
        window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData("DAD1B"))
        assert len(window.uv.integration_highlights) == 1
        assert window.uv.integration_highlights[0].zValue() == -10
        window.chromatogram_channel.setCurrentIndex(0)
        window.remove_integration_action.trigger()
        assert len(window.integrations) == 1
        assert len(window.uv.integration_highlights) == 1
        window.clear_integrations_action.trigger()
        assert not window.uv.integration_highlights
        assert not window.integrations
        window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData("DAD1B"))
        window.uv.region.setRegion((.55, .75))
        window.integrate_action.trigger()
        window.integrate_action.trigger()
        assert len(window.uv.integration_highlights) == 1
        window.files.clearSelection()
        assert not window.uv.integration_highlights
    finally:
        window.close(); app.processEvents()


def test_highlight_fills_only_positive_baseline_to_trace_area():
    app = QApplication.instance() or QApplication([])
    item = IntegrationAreaItem(np.array([0., 1., 2.]), np.array([0., 2., 0.]), np.array([1., 1., 1.]))
    assert item.path().contains(QPointF(1., 1.5))
    assert not item.path().contains(QPointF(1., .5))
    assert not item.path().contains(QPointF(1., 2.5))
    assert not item.path().contains(QPointF(.25, 1.1))
    assert item.getRegion() == (0., 2.)
