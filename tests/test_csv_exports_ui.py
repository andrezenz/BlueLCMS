import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
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
            window.files.setCurrentRow(0); settle(window, app)
            assert not window.uv.isHidden()
            assert window.positive.isHidden() and not window.negative.isHidden()
            assert window.run_data.chromatograms[0].name == "TIC"
            assert len(window.uv.plotItem.listDataItems()) == 1
            before = window.negative.snap_data[0][0].copy()
            window.uv.region.setRegion((4, 5)); settle(window, app)
            np.testing.assert_array_equal(window.negative.snap_data[0][0], before)
            assert "does not re-extract" in window.statusBar().currentMessage()
        finally:
            window.close(); app.processEvents()
        if not offline:
            folder.rename(tmp_path / "unmounted")
