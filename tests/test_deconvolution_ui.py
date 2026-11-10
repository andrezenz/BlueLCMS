import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.deconvolution import DeconvolutionSettings, PROTON_MASS
from bluelcms.deconvolution_dialog import DeconvolutionDialog


def test_settings_roundtrip_and_validation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    options = DeconvolutionSettings(minimum_mass=5000, maximum_mass=12000, maximum_charge=20,
                                    maximum_highlighted_species=4)
    settings.set_deconvolution_options(options)
    assert settings.deconvolution_options() == options
    dialog = DeconvolutionDialog(options)
    assert dialog.selected_options() == options
    assert dialog.fields["maximum_highlighted_species"].value() == 4
    dialog.close()
    preferences.setValue("deconvolution_options", '{"minimum_mass": 5000}')
    assert settings.deconvolution_options().maximum_highlighted_species == 7
    preferences.setValue("deconvolution_options", '{"minimum_charge": 0}')
    assert settings.deconvolution_options() == DeconvolutionSettings()
    app.processEvents()


def test_results_annotations_signal_conservation_and_disable(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        x = np.sort(6200 / np.arange(4, 10) - PROTON_MASS)
        y = np.full(len(x), 100.0)
        empty = (np.array([]), np.array([]))
        window.histograms = {tmp_path / "sample.mzML": {"-": (x, y), "+": empty}}
        window.negative.setXRange(500, 1700, padding=0)
        monkeypatch.setattr(window, "submit", lambda token, fn, callback, *args: callback(token, fn(*args), ""))
        window.deconvolution_button.setChecked(True)
        window.request_deconvolution()
        assert window.deconvolution_table.rowCount() == 1
        assert "6200.00" == window.deconvolution_table.item(0, 3).text()
        labels = [item for item in window.negative.items() if isinstance(item, pg.TextItem)]
        assert {f"{charge}-" for charge in range(4, 10)} <= {label.toPlainText() for label in labels}
        bars = [item for item in window.negative.items() if isinstance(item, pg.BarGraphItem)]
        assert sum(np.sum(bar.opts["height"]) for bar in bars) == y.sum()
        window.deconvolution_table.selectRow(0)
        assert window.deconvolution_highlight is not None
        # Zooming redraws annotations without running a different analysis.
        previous = window.deconvolution_results
        window.draw_histograms()
        assert window.deconvolution_results is previous
        window.deconvolution_button.setChecked(False)
        assert not window.deconvolution_results
        labels = [item.toPlainText() for item in window.negative.items() if isinstance(item, pg.TextItem)]
        assert not any(label.endswith("-") for label in labels)
    finally:
        window.close()
        app.processEvents()


def test_species_highlighting_cap_preserves_results_and_signal(tmp_path, monkeypatch):
    from dataclasses import replace
    from bluelcms.deconvolution import ChargeAssignment, Species

    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        path = tmp_path / "mixture.mzML"
        x = np.arange(500., 1300., 100.)
        y = np.arange(1., 9.) * 100
        empty = (np.array([]), np.array([]))
        window.histograms = {path: {"-": (x, y), "+": empty}}
        window.negative.setXRange(400, 1400, padding=0)
        window.deconvolution_button.setChecked(True)
        species = tuple(Species(6000 + i * 100, "-", (ChargeAssignment(mz, height, i + 2, (i,)),),
                                height, height / y.sum() * 100, 100)
                        for i, (mz, height) in enumerate(zip(x, y)))
        window.deconvolution_results = {path: {"-": species, "+": ()}}
        window.populate_deconvolution()

        def charge_labels():
            return {item.toPlainText() for item in window.negative.items()
                    if isinstance(item, pg.TextItem) and item.toPlainText().endswith("-")}

        def signal():
            return sum(np.sum(item.opts["height"]) for item in window.negative.items()
                       if isinstance(item, pg.BarGraphItem))

        window.draw_histograms()
        assert charge_labels() == {f"{charge}-" for charge in range(3, 10)}
        assert window.deconvolution_table.rowCount() == 8
        assert signal() == y.sum()
        settings.set_deconvolution_options(replace(settings.deconvolution_options(), maximum_highlighted_species=2))
        window.draw_histograms()
        assert charge_labels() == {"8-", "9-"}
        window.deconvolution_table.selectRow(0)
        assert charge_labels() == {"2-", "9-"}
        settings.set_deconvolution_options(replace(settings.deconvolution_options(), maximum_highlighted_species=0))
        window.draw_histograms()
        assert not charge_labels()
        assert window.deconvolution_table.rowCount() == 8
        assert signal() == y.sum()
    finally:
        window.close()
        app.processEvents()


def test_stale_results_ignored_and_requests_coalesced(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        submitted = []
        monkeypatch.setattr(window, "submit", lambda *args: submitted.append(args))
        window.deconvolution_button.setChecked(True)
        window.request_deconvolution()
        window.request_deconvolution()
        window.request_deconvolution()
        assert len(submitted) == 1
        token, _, callback, *_ = submitted[0]
        callback(token, {"stale": {}}, "")
        assert window.deconvolution_results == {}
        assert len(submitted) == 2
        window.deconvolution_button.setChecked(False)
        token, _, callback, *_ = submitted[-1]
        callback(token, {"disabled": {}}, "")
        assert window.deconvolution_results == {}
    finally:
        window.close()
        app.processEvents()


def test_selected_interval_drives_background_results(tmp_path, monkeypatch):
    from bluelcms.mzml import Run, Scan

    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    window = MainWindow()
    try:
        charges = np.arange(4, 10)
        run = Run((), tuple(Scan(time, "-", np.array([mass / charge - PROTON_MASS]), np.array([100.0]))
                            for time, mass in ((1.0, 6200), (2.0, 9530)) for charge in charges))
        path = tmp_path / "sample.mzML"
        window.runs = {path: run}
        window.uv.region.setBounds((0, 3))
        window.uv.region.setRegion((.9, 1.1))
        window.uv.region.show()
        window.timer.stop()
        window.deconvolution_button.setChecked(True)
        for _ in range(4):
            window.pool.waitForDone(); app.processEvents()
        assert window.deconvolution_table.rowCount() == 1
        assert abs(float(window.deconvolution_table.item(0, 3).text()) - 6200) < .5
        window.uv.region.setRegion((1.9, 2.1))
        window.timer.stop()
        window.calculate_region()
        for _ in range(4):
            window.pool.waitForDone(); app.processEvents()
        assert window.deconvolution_table.rowCount() == 1
        assert abs(float(window.deconvolution_table.item(0, 3).text()) - 9530) < .5
    finally:
        window.close()
        app.processEvents()
