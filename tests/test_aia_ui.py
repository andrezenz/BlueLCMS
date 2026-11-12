import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.external import parse_request
from bluelcms.folders import cached_path
from test_aia import make_aia, write_aia_cdf


def settle(window, app):
    for _ in range(8):
        window.pool.waitForDone(); app.processEvents()


def test_multichannel_display_integration_and_offline_reopen(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    monkeypatch.setattr(settings, "integration_folder", lambda: tmp_path / "integrations")
    root = tmp_path / "remote"
    source = make_aia(root / "ANZ" / "ANZ260" / "2026_10_29_ANZ260P1.AIA")
    settings.set_data_folders([root]); settings.set_cache_folder(tmp_path / "cache")
    original = {path.name: path.read_bytes() for path in source.iterdir()}
    window = MainWindow()
    try:
        settle(window, app)
        assert window.files.count() == 1
        assert window.files.item(0).parent().text() == "ANZ260"
        window.files.setCurrentRow(0)
        settle(window, app)
        assert len(window.run_data.chromatograms) == 2
        assert not window.run_data.dad and not window.run_data.scans
        assert window.mass_splitter.isHidden()
        assert len(window.uv.plotItem.listDataItems()) == 2
        assert all("DAD1" in curve.name() for curve in window.uv.plotItem.listDataItems())
        assert window.uv.getAxis("left").labelUnits == "mAU"
        assert not window.wavelength.isEnabled() and not window.mode.isEnabled()
        assert not window.uv.integration_enabled
        window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData("DAD1B"))
        assert window.uv.integration_enabled
        curves = window.uv.plotItem.listDataItems()
        assert len(curves) == 1
        np.testing.assert_array_equal(curves[0].yData, [-2, 1, 4, 1])
        window.uv.region.setRegion((.55, .75))
        window.integrate_region()
        assert window.integrations[0]["channel"] == "DAD1B"
        assert window.integrations[0]["wavelength_nm"] is None
        assert window.integrations[0]["unit"] == "mAU"
        window.chromatogram_channel.setCurrentIndex(window.chromatogram_channel.findData("DAD1C"))
        window.integrate_region()
        assert [row["channel"] for row in window.integrations] == ["DAD1B", "DAD1C"]
        assert window.integration_table.item(0, 4).text() == ""
        assert window.integration_table.item(1, 4).text() == ""
        assert (tmp_path / "integrations").is_dir()
        assert {path.name: path.read_bytes() for path in source.iterdir()} == original
        settle(window, app)
        assert cached_path(source, settings.cache_folder()).is_file()
    finally:
        window.close(); app.processEvents()
    source.rename(tmp_path / "disconnected")
    offline = MainWindow()
    try:
        settle(offline, app)
        assert offline.files.count() == 1
        item = offline.files.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == source
        assert item.data(Qt.ItemDataRole.UserRole + 1) == "cache-only"
        offline.files.setCurrentRow(0)
        settle(offline, app)
        assert len(offline.run_data.chromatograms) == 2
        assert offline.mass_splitter.isHidden()
        assert len(offline.integrations) == 2
        assert offline.integration_table.item(0, 2).text() == "DAD1B"
    finally:
        offline.close(); app.processEvents()


def test_external_aia_interval_and_reexport_refreshes_existing_cache(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    source = make_aia(tmp_path / "remote" / "sample.AIA")
    settings.set_data_folders([source])  # Selecting the AIA itself must work too.
    settings.set_cache_folder(tmp_path / "cache")
    for iteration in range(2):
        window = MainWindow()
        try:
            settle(window, app)
            request = parse_request(["--open", str(source), "--start", ".55", "--end", ".75"])
            window.open_external(request)
            settle(window, app)
            assert window.uv.region.getRegion() == (.55, .75)
            if iteration:
                np.testing.assert_array_equal(window.run_data.chromatograms[0].values, [10, 20, 30, 40])
        finally:
            window.close(); app.processEvents()
        if not iteration:
            write_aia_cdf(source / "sample_sample_DAD1B.cdf", values=(10, 20, 30, 40))
    standalone = parse_request(["--open", str(source / "sample_sample_DAD1B.cdf")])
    assert standalone.path.endswith(".cdf")
