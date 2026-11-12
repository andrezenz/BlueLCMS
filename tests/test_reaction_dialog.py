import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtCore import Qt
from PySide6.QtGui import QPaintDevice
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from bluelcms import settings
from bluelcms.app import MainWindow
from bluelcms.reaction_collections import load_collection
from bluelcms.reaction_dialog import ReactionCollectionDialog
from test_aia import make_aia
from test_reaction_collections import kinetics


def test_editor_preserves_qt_paint_metrics_and_renders(monkeypatch):
    import sys

    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    dialog = ReactionCollectionDialog(kinetics())
    try:
        # QPaintDevice.metric is a virtual method. Shadowing it with a widget
        # breaks Qt's DPI/painting callbacks even if the numeric model works.
        assert callable(dialog.metric)
        assert dialog.metric(QPaintDevice.PaintDeviceMetric.PdmDpiX) > 0
        dialog.show()
        app.processEvents()
        assert not dialog.grab().isNull()
        assert not errors
        dialog.progress_metric.setCurrentIndex(dialog.progress_metric.findData("area_percent"))
        app.processEvents()
        assert len(dialog.progress.plotItem.listDataItems()) == 2
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_editor_time_points_windows_ratios_plots_and_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    collection = kinetics()
    dialog = ReactionCollectionDialog(collection)
    try:
        assert dialog.results_table.rowCount() == 6
        assert len(dialog.progress.plotItem.listDataItems()) == 2
        # Sample-specific windows must not change the shared target bounds.
        dialog.edit_sample_window.setChecked(True)
        dialog.window_region.setRegion((.8, 1.2))
        assert dialog.collection.overrides[("m0", "a")] == (.8, 1.2)
        assert dialog.collection.targets[0].start_min == .5
        assert dialog.results[0]["area"] < 4
        dialog.reset_window()
        assert not dialog.collection.overrides
        dialog.samples_table.item(1, 1).setText("7.5")
        assert dialog.collection.samples[1].time_min == 7.5
        dialog.progress_metric.setCurrentIndex(dialog.progress_metric.findData("ratio"))
        assert len(dialog.progress.plotItem.listDataItems()) == 2
        dialog.ratio_reference.setCurrentIndex(dialog.ratio_reference.findData("a"))
        assert dialog.results[3]["ratio"] == pytest.approx(1)
        dialog.path = tmp_path / "reaction.zip"
        assert dialog.save()
        assert not dialog.dirty
        reopened = load_collection(dialog.path)
        assert reopened.samples[1].time_min == 7.5
        assert reopened.ratio_reference == "a"
        dialog.samples_table.item(0, 1).setText("not a time")
        assert not dialog.recalculate()
        assert dialog.results_table.rowCount() == 0
        assert not dialog.save()
        dialog.samples_table.item(0, 1).setText("")
        assert dialog.recalculate()
        assert dialog.collection.samples[0].time_min is None
        for curve in dialog.progress.plotItem.listDataItems():
            assert len(curve.xData) == 2
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_editor_add_remove_target_and_common_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    collection = kinetics(); collection.targets = []
    collection.ratio_reference = None; collection.internal_standard = None
    dialog = ReactionCollectionDialog(collection)
    try:
        dialog.add_target()
        assert len(dialog.collection.targets) == 1
        dialog.window_region.setRegion((.5, 1.5))
        assert dialog.collection.targets[0].start_min == .5
        np.testing.assert_allclose([r["area"] for r in dialog.results], [4, 2, 0], atol=1e-12)
        dialog.ratio_reference.setCurrentIndex(1)
        assert dialog.collection.ratio_reference == dialog.collection.targets[0].id
        dialog.remove_target()
        assert not dialog.collection.targets
        assert dialog.collection.ratio_reference is None
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_opening_editor_does_not_round_saved_times_or_windows(tmp_path):
    app = QApplication.instance() or QApplication([])
    collection = kinetics()
    collection.samples[0].time_min = 0.12345678901234567
    collection.targets[0].start_min = 0.5123456789123456
    dialog = ReactionCollectionDialog(collection, path=tmp_path / "opened.zip")
    try:
        assert dialog.collection.samples[0].time_min == collection.samples[0].time_min
        assert dialog.collection.targets[0].start_min == collection.targets[0].start_min
        assert not dialog.dirty
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_unsaved_collection_cannot_be_closed_on_cancel_or_failed_save(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = ReactionCollectionDialog(kinetics())
    try:
        dialog.show()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
        assert not dialog.close()
        assert dialog.dirty
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
        monkeypatch.setattr(dialog, "save", lambda: False)
        assert not dialog.close()
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_individual_integrals_named_compounds_baseline_drag_and_separate_plot(tmp_path):
    app = QApplication.instance() or QApplication([])
    collection = kinetics(); collection.integration_mode = "individual"
    collection.targets = []; collection.ratio_reference = None; collection.internal_standard = None
    dialog = ReactionCollectionDialog(collection)
    try:
        assert not dialog.plot_progress_button.isEnabled()
        dialog.window_region.setRegion((.5, 1.5))
        dialog.compound_name.setEditText("A")
        dialog.integrate_measurement()
        assert dialog.results_table.rowCount() == 1
        assert dialog.results[0]["area_percent"] == pytest.approx(100)
        dialog.samples_table.selectRow(1)
        dialog.window_region.setRegion((.5, 1.5))
        dialog.integrate_measurement()
        dialog.compound_name.setEditText("B")
        dialog.window_region.setRegion((2.5, 3.5))
        dialog.integrate_measurement()
        assert dialog.results_table.rowCount() == 3
        assert dialog.plot_progress_button.isEnabled()
        plot = dialog.open_progress_plot()
        assert plot is not None and plot is not dialog
        assert len(plot.plot.plotItem.listDataItems()) == 2
        plot.compounds.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert len(plot.plot.plotItem.listDataItems()) == 1
        dialog.samples_table.item(1, 1).setText("7.5")
        assert 7.5 in plot.plot.plotItem.listDataItems()[0].xData
        editor = dialog.baseline_editor
        assert editor.points[0].pos().y() == pytest.approx(16)
        editor.points[0].setPos(2.5, 15.)
        editor.points[1].setPos(3.5, 15.)
        editor.finish_edit()
        dialog.integrate_measurement()
        target_b = next(t for t in dialog.collection.targets if t.name == "B")
        spec = dialog.collection.individual_integrations[("m1", target_b.id)]
        assert spec.baseline == "manual" and spec.baseline_start == 15.
        row = next(r for r in dialog.results if r["sample_id"] == "m1" and r["target"] == "B")
        assert row["area_percent"] == pytest.approx(60)
        dialog.path = tmp_path / "reaction-individual.zip"
        assert dialog.save()
        assert load_collection(dialog.path).individual_integrations[("m1", target_b.id)].baseline_end == 15.
    finally:
        dialog.dirty = False; dialog.close(); app.processEvents()


def test_toolbar_creates_selected_collection_and_reopens_archive(tmp_path, monkeypatch):
    from test_aia_ui import settle

    app = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    remote = tmp_path / "remote"
    make_aia(remote / "2026_01_01_A.AIA")
    make_aia(remote / "2026_01_02_B.AIA")
    settings.set_data_folders([remote]); settings.set_cache_folder(tmp_path / "cache")
    window = MainWindow()
    try:
        settle(window, app)
        assert not window.create_collection_action.isEnabled()
        window.files.selectAll()
        settle(window, app)
        assert window.create_collection_action.isEnabled()
        window.create_collection_action.trigger()
        settle(window, app)
        assert len(window.reaction_windows) == 1
        dialog = next(iter(window.reaction_windows))
        assert len(dialog.collection.samples) == 2
        assert all(sample.time_min is None for sample in dialog.collection.samples)
        assert all(len(sample.channels) == 2 for sample in dialog.collection.samples)
        dialog.samples_table.item(0, 1).setText("0")
        dialog.samples_table.item(1, 1).setText("10")
        dialog.add_target()
        path = tmp_path / "saved.zip"
        dialog.path = path
        assert dialog.save()
        # Opening is independent of both sidebar selection and source presence.
        remote.rename(tmp_path / "unmounted")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
        window.open_collection_action.trigger()
        settle(window, app)
        assert len(window.reaction_windows) == 2
        opened = next(d for d in window.reaction_windows if d is not dialog)
        assert opened.collection.samples[1].time_min == 10
        assert opened.path == path
        assert len(opened.collection.samples[0].originals) == 2
    finally:
        for dialog in list(window.reaction_windows):
            dialog.dirty = False
        window.close(); app.processEvents()
