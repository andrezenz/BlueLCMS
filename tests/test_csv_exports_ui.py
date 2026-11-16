import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.external import OpenRequest
from bluelcms.folders import cached_path
from test_csv_exports import write_spectrum, write_tic


def settle(window, app):
    for _ in range(8):
        window.pool.waitForDone(); app.processEvents()
    window.timer.stop()
    window.calculate_region()
    for _ in range(3):
        window.pool.waitForDone(); app.processEvents()


def test_mass_only_csv_hides_chromatogram_and_retains_exact_peaks_when_zoomed(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: prefs)
    folder = tmp_path / "remote"; folder.mkdir()
    source = write_spectrum(folder / "sample_spectrum.csv")
    settings.set_data_folders([folder]); settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        settle(window, app)
        assert window.files.count() == 1
        window.files.setCurrentRow(0); settle(window, app)
        assert window.uv.isHidden()
        assert not window.uv.exported_interval_highlights
        assert not window.positive.isHidden() and window.negative.isHidden()
        assert window.positive.data
        assert "fixed CSV export" in window.positive.plotItem.titleLabel.text
        np.testing.assert_array_equal(window.positive.snap_data[0][0], [400.000010001, 400.000020002, 501.123456789])
        window.positive.setXRange(400, 400.00004, padding=0)
        window.draw_histograms()
        np.testing.assert_array_equal(window.positive.data[0][0], [400.000010001, 400.000020002, 501.123456789])
        bars = [item for item in window.positive.items() if isinstance(item, pg.BarGraphItem)]
        assert sum(len(item.opts["x"]) for item in bars) == 2
    finally:
        window.close(); app.processEvents()


def test_paired_tic_and_offline_cache_restore_layout(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: prefs)
    folder = tmp_path / "remote"; folder.mkdir()
    source = write_spectrum(folder / "sample_spectrum.csv", polarity="-")
    write_tic(folder / "sample_TIC.csv")
    settings.set_data_folders([folder]); settings.set_cache_folder(tmp_path / "cache")
    for offline in (False, True):
        window = MainWindow()
        try:
            settle(window, app)
            assert window.files.count() == 1
            assert window.files.item(0).text() == "sample — HR-ESI (-), 2.10–2.60 min"
            window.files.setCurrentRow(0); settle(window, app)
            assert not window.uv.isHidden()
            assert window.positive.isHidden() and not window.negative.isHidden()
            assert window.run_data.chromatograms[0].name == "TIC"
            assert len(window.uv.plotItem.listDataItems()) == 1
            assert "TIC" in window.uv.plotItem.titleLabel.text
            assert window.uv.getAxis("left").labelText == "Total ion signal"
            assert window.uv.getAxis("bottom").labelUnits == "min"
            band, = window.uv.exported_interval_highlights
            assert band.getRegion() == (2.1, 2.6)
            assert window.uv.region.getRegion() == (2.1, 2.6)
            assert not band.movable
            assert band.acceptedMouseButtons() == Qt.MouseButton.NoButton
            assert "64 scans" in window.uv.exported_interval_labels[0].toPlainText()
            assert "sample_TIC.csv" in window.files.item(0).toolTip()
            assert "sample_spectrum.csv" in window.files.item(0).toolTip()
            before = window.negative.snap_data[0][0].copy()
            window.uv.region.setRegion((4, 5)); settle(window, app)
            np.testing.assert_array_equal(window.negative.snap_data[0][0], before)
            assert "does not re-extract" in window.statusBar().currentMessage()
            window.draw_uv()
            assert window.uv.region.getRegion() == (4, 5)
            assert len(window.uv.exported_interval_highlights) == 1
            assert window.uv.exported_interval_highlights[0].getRegion() == (2.1, 2.6)
            window.show_integrations_action.trigger()
            assert window.uv.exported_interval_highlights[0].getRegion() == (2.1, 2.6)
        finally:
            window.close(); app.processEvents()
        if not offline:
            folder.rename(tmp_path / "unmounted")


def test_cached_standalone_tic_is_grouped_when_spectrum_arrives_and_offline(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: prefs)
    settings.set_alert_new_measurements(False)
    folder = tmp_path / "remote"; folder.mkdir()
    tic = write_tic(folder / "sample_TIC.csv")
    source = folder / "sample_spectrum.csv"
    settings.set_data_folders([folder]); settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        settle(window, app)
        window.files.setCurrentRow(0); settle(window, app)
        assert cached_path(tic, settings.cache_folder()).is_file()
        write_spectrum(source)
        window.refresh_files(background=True); settle(window, app)
        assert window.files.count() == 1
        assert window.files.item(0).data(Qt.ItemDataRole.UserRole) == source
        assert window.files.item(0).isSelected()
        assert window.run_data.exported_spectra
        assert cached_path(source, settings.cache_folder()).is_file()
        window.open_external(OpenRequest(str(tic))); settle(window, app)
        assert window.files.count() == 1
        assert list(window.runs) == [source]
    finally:
        window.close(); app.processEvents()
    folder.rename(tmp_path / "unmounted")
    offline = MainWindow()
    try:
        settle(offline, app)
        assert offline.files.count() == 1
        assert offline.files.item(0).text() == "sample — HR-ESI (+), 2.10–2.60 min"
        offline.files.setCurrentRow(0); settle(offline, app)
        assert len(offline.uv.exported_interval_highlights) == 1
        assert offline.run_data.chromatograms[0].name == "TIC"
        # Hiding a duplicate leaf must not delete a reusable standalone cache.
        assert cached_path(tic, settings.cache_folder()).is_file()
    finally:
        offline.close(); app.processEvents()


def test_standalone_tic_has_explicit_axes_without_a_fabricated_interval(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    prefs = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: prefs)
    folder = tmp_path / "remote"; folder.mkdir()
    write_tic(folder / "sample_TIC.csv")
    settings.set_data_folders([folder])
    window = MainWindow()
    try:
        settle(window, app)
        assert window.files.item(0).text() == "sample — TIC"
        window.files.setCurrentRow(0); settle(window, app)
        assert "Total ion chromatogram (TIC)" in window.uv.plotItem.titleLabel.text
        assert window.uv.getAxis("left").labelText == "Total ion signal"
        assert not window.uv.exported_interval_highlights
        assert window.mass_splitter.isHidden()
    finally:
        window.close(); app.processEvents()
