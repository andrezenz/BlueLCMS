"""Reaction-monitoring collection editor, chromatogram overlays and progress plots."""

from dataclasses import replace
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
                              QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                              QListWidget, QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                              QVBoxLayout, QWidget)

from .reaction_collections import (COLORS, IndividualIntegration, ReactionTarget, evaluate,
                                   integration_curve, save_collection)
from .views import BaselineEditor, IntegrationAreaItem


class ReactionCollectionDialog(QDialog):
    def __init__(self, collection, parent=None, path=None):
        super().__init__(parent)
        self.collection = collection
        self.path = Path(path) if path else None
        self.dirty = path is None
        self.updating = True
        self.results = []
        self.progress_windows = set()
        self.pending_windows = {}
        self.pending_baselines = {}
        self.baseline_requests = set()
        self.resize(1450, 950)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Collection"))
        self.name = QLineEdit(collection.name)
        self.name.textChanged.connect(self.changed)
        controls.addWidget(self.name)
        self.save_button = QPushButton("Save collection…")
        self.save_button.clicked.connect(self.save)
        controls.addWidget(self.save_button)
        save_as = QPushButton("Save as…"); save_as.clicked.connect(self.save_as)
        controls.addWidget(save_as)
        export_csv = QPushButton("Export CSV copy…")
        export_csv.setToolTip("Save a portable collection copy with additional time/signal CSVs for every chromatogram (larger file).")
        export_csv.clicked.connect(self.export_csv_copy)
        controls.addWidget(export_csv)
        self.plot_progress_button = QPushButton("Plot progress…")
        self.plot_progress_button.clicked.connect(self.open_progress_plot)
        controls.addWidget(self.plot_progress_button)
        layout.addLayout(controls)
        self.note = QLabel("Assign elapsed reaction times in minutes; acquisition timestamps are not used as reaction times.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Measurements — edit reaction times (minutes); duplicate times retain replicates"))
        self.samples_table = QTableWidget(len(collection.samples), 3)
        self.samples_table.setHorizontalHeaderLabels(("Measurement", "Reaction time (min)", "Original source"))
        self.samples_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.samples_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        for row, sample in enumerate(collection.samples):
            for column, value in enumerate((sample.name, "" if sample.time_min is None else f"{sample.time_min:.17g}", sample.source)):
                item = QTableWidgetItem(value)
                if column != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(sample.provenance if column != 1 else "Elapsed reaction time in minutes; leave blank if unknown.")
                self.samples_table.setItem(row, column, item)
        self.samples_table.cellChanged.connect(self.changed)
        self.samples_table.itemSelectionChanged.connect(self.selection_changed)
        self.samples_table.resizeColumnsToContents()
        left_layout.addWidget(self.samples_table)
        self.individual_mode = QCheckBox("Integrate measurements individually")
        self.individual_mode.setChecked(collection.integration_mode == "individual")
        self.individual_mode.toggled.connect(self.mode_changed)
        left_layout.addWidget(self.individual_mode)
        self.individual_controls = QWidget()
        individual_layout = QHBoxLayout(self.individual_controls)
        self.individual_channel = QComboBox()
        self.individual_channel.addItems([c.name for c in collection.samples[0].channels])
        self.individual_channel.currentIndexChanged.connect(self.selection_changed)
        self.compound_name = QComboBox(); self.compound_name.setEditable(True)
        self.compound_name.addItems(list(dict.fromkeys(["A", "B", "C", "D", *[t.name for t in collection.targets]])))
        self.compound_name.activated.connect(self.choose_compound)
        self.compound_name.editTextChanged.connect(self.compound_changed)
        self.individual_baseline = QComboBox()
        for name, value in (("Endpoint line", "endpoints"), ("Horizontal midpoint", "midpoint"), ("Zero", "zero")):
            self.individual_baseline.addItem(name, value)
        self.individual_baseline.currentIndexChanged.connect(self.baseline_mode_changed)
        individual_layout.addWidget(self.individual_channel)
        individual_layout.addWidget(self.compound_name)
        individual_layout.addWidget(self.individual_baseline)
        left_layout.addWidget(self.individual_controls)
        self.integrate_measurement_button = QPushButton("Integrate / update compound in selected measurement")
        self.integrate_measurement_button.clicked.connect(self.integrate_measurement)
        left_layout.addWidget(self.integrate_measurement_button)
        self.targets_label = QLabel("Tracked targets — common retention-time windows (minutes)")
        left_layout.addWidget(self.targets_label)
        self.targets_table = QTableWidget(0, 6)
        self.targets_table.setHorizontalHeaderLabels(("Target", "Channel", "Start", "End", "Baseline", "Color"))
        self.targets_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.targets_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.targets_table.cellChanged.connect(self.changed)
        self.targets_table.itemSelectionChanged.connect(self.selection_changed)
        left_layout.addWidget(self.targets_table)
        actions = QHBoxLayout()
        add = QPushButton("Add target"); add.clicked.connect(self.add_target)
        remove = QPushButton("Remove target"); remove.clicked.connect(self.remove_target)
        actions.addWidget(add); actions.addWidget(remove)
        left_layout.addLayout(actions)
        self.edit_sample_window = QCheckBox("Edit window for selected measurement only")
        self.edit_sample_window.toggled.connect(self.selection_changed)
        left_layout.addWidget(self.edit_sample_window)
        self.reset_window_button = QPushButton("Reset selected measurement to common window")
        self.reset_window_button.clicked.connect(self.reset_window)
        left_layout.addWidget(self.reset_window_button)

        right = QWidget(); right_layout = QVBoxLayout(right)
        selectors = QHBoxLayout()
        self.progress_metric = QComboBox()
        for label, column in (("Integrated area", "area"), ("Area fraction (%)", "area_percent"),
                              ("Ratio to reference", "ratio"), ("Internal-standard normalized", "normalized_area")):
            self.progress_metric.addItem(label, column)
        self.progress_metric.currentIndexChanged.connect(self.draw_plots)
        selectors.addWidget(self.progress_metric)
        self.ratio_reference = QComboBox(); self.internal_standard = QComboBox()
        self.ratio_reference.currentIndexChanged.connect(self.references_changed)
        self.internal_standard.currentIndexChanged.connect(self.references_changed)
        selectors.addWidget(QLabel("Ratio denominator")); selectors.addWidget(self.ratio_reference)
        selectors.addWidget(QLabel("Internal standard")); selectors.addWidget(self.internal_standard)
        right_layout.addLayout(selectors)
        self.overlay = pg.PlotWidget(title="Chromatogram overlays — select a target")
        self.overlay.setLabel("bottom", "Retention time", units="min")
        self.overlay.showGrid(x=True, y=True, alpha=.2); self.overlay.addLegend()
        self.window_region = pg.LinearRegionItem(brush=(72, 169, 239, 35))
        self.window_region.sigRegionChangeFinished.connect(self.window_changed)
        self.baseline_editor = BaselineEditor(self.overlay, self.window_region)
        self.baseline_editor.edited.connect(self.baseline_edited)
        self.progress = pg.PlotWidget(title="Reaction progress")
        self.progress.setLabel("bottom", "Reaction time", units="min")
        self.progress.showGrid(x=True, y=True, alpha=.2); self.progress.addLegend()
        plots = QSplitter(Qt.Orientation.Vertical)
        plots.addWidget(self.overlay); plots.addWidget(self.progress)
        right_layout.addWidget(plots)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left); split.addWidget(right); split.setSizes([500, 900])
        layout.addWidget(split)
        self.results_table = QTableWidget(0, 10)
        self.results_table.setHorizontalHeaderLabels(("Measurement", "Reaction min", "Target", "Window min", "Area", "Area unit", "Area %", "Ratio", "Normalized", "Status"))
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setMaximumHeight(220)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.itemSelectionChanged.connect(self.select_integral)
        layout.addWidget(self.results_table)
        self.render_targets()
        if collection.targets:
            self.targets_table.selectRow(0)
        self.samples_table.selectRow(0)
        self.updating = False
        self.update_mode_controls()
        self.recalculate()
        self.update_title()

    def update_title(self):
        self.setWindowTitle(f"Reaction collection — {self.collection.name}" + (" *" if self.dirty else ""))

    def selected_target(self):
        row = self.targets_table.currentRow()
        return self.collection.targets[row] if 0 <= row < len(self.collection.targets) else None

    def selected_sample(self):
        row = self.samples_table.currentRow()
        return self.collection.samples[row] if 0 <= row < len(self.collection.samples) else None

    def render_targets(self):
        was_updating = self.updating; self.updating = True
        # Qt retires replaced cell widgets with deferred deletion. Silence the
        # old editors before replacing them so their teardown cannot re-enter
        # collection recalculation after the table/dialog has changed.
        for row in range(self.targets_table.rowCount()):
            for column in range(1, self.targets_table.columnCount()):
                widget = self.targets_table.cellWidget(row, column)
                if widget is not None:
                    widget.blockSignals(True)
        self.targets_table.setRowCount(len(self.collection.targets))
        channels = sorted({c.name for sample in self.collection.samples for c in sample.channels})
        for row, target in enumerate(self.collection.targets):
            name = QTableWidgetItem(target.name); name.setForeground(QColor(target.color))
            self.targets_table.setItem(row, 0, name)
            channel = QComboBox(); channel.addItems(channels); channel.setCurrentText(target.channel)
            channel.currentIndexChanged.connect(self.changed)
            self.targets_table.setCellWidget(row, 1, channel)
            for column, value in ((2, target.start_min), (3, target.end_min)):
                field = QDoubleSpinBox(); field.setDecimals(9); field.setRange(0, 1e12); field.setValue(value)
                # Keep imported/archive boundaries exact until the user edits
                # them; display precision must not change saved integrations.
                field.setProperty("original_value", value)
                field.setProperty("shown_value", field.value())
                field.valueChanged.connect(self.changed)
                self.targets_table.setCellWidget(row, column, field)
            baseline = QComboBox()
            baseline.addItem("Endpoint line", "endpoints"); baseline.addItem("Horizontal midpoint", "midpoint"); baseline.addItem("Zero", "zero")
            baseline.setCurrentIndex(baseline.findData(target.baseline)); baseline.currentIndexChanged.connect(self.changed)
            self.targets_table.setCellWidget(row, 4, baseline)
            color = QPushButton(target.color); color.setStyleSheet(f"color: {target.color};")
            color.clicked.connect(lambda checked=False, key=target.id: self.choose_color(key))
            self.targets_table.setCellWidget(row, 5, color)
        for combo, reference in ((self.ratio_reference, self.collection.ratio_reference),
                                 (self.internal_standard, self.collection.internal_standard)):
            combo.clear(); combo.addItem("None", None)
            for target in self.collection.targets:
                combo.addItem(target.name, target.id)
            combo.setCurrentIndex(max(0, combo.findData(reference)))
        self.targets_table.resizeColumnsToContents()
        self.updating = was_updating

    def update_mode_controls(self):
        individual = self.collection.integration_mode == "individual"
        self.individual_controls.setVisible(individual)
        self.integrate_measurement_button.setVisible(individual)
        self.edit_sample_window.setEnabled(not individual)
        self.edit_sample_window.setVisible(not individual)
        self.targets_label.setText("Compounds — assigned to individual measurement integrals" if individual else "Tracked targets — common retention-time windows (minutes)")
        self.reset_window_button.setText("Remove selected compound's integral from this measurement" if individual else "Reset selected measurement to common window")
        for column in (2, 3, 4):
            self.targets_table.setColumnHidden(column, individual)

    def mode_changed(self, enabled):
        if not self.updating:
            self.collection.integration_mode = "individual" if enabled else "common"
            self.update_mode_controls()
            self.changed()

    def sync_model(self):
        name = self.name.text().strip()
        if not name:
            raise ValueError("Enter a collection name.")
        times = []
        for row, sample in enumerate(self.collection.samples):
            text = self.samples_table.item(row, 1).text().strip()
            try:
                time = float(text) if text else None
            except ValueError as error:
                raise ValueError(f"{sample.name}: enter reaction time in minutes.") from error
            if time is not None and (not math.isfinite(time) or time < 0):
                raise ValueError(f"{sample.name}: reaction time must be finite and non-negative.")
            times.append(time)
        targets = []
        for row, target in enumerate(self.collection.targets):
            def boundary(column):
                field = self.targets_table.cellWidget(row, column)
                return field.property("original_value") if field.value() == field.property("shown_value") else field.value()
            targets.append(replace(target, name=self.targets_table.item(row, 0).text().strip(),
                                   channel=self.targets_table.cellWidget(row, 1).currentText(),
                                   start_min=boundary(2), end_min=boundary(3),
                                   baseline=self.targets_table.cellWidget(row, 4).currentData()))
        candidate = replace(self.collection, name=name, targets=targets,
                            samples=[replace(s, time_min=t) for s, t in zip(self.collection.samples, times)])
        candidate.validate()
        self.collection = candidate

    def changed(self, *_):
        if self.updating:
            return
        self.dirty = True
        self.recalculate()

    def recalculate(self):
        try:
            self.sync_model()
            self.results = evaluate(self.collection)
        except (ValueError, TypeError) as error:
            self.results = []
            self.note.setText(str(error)); self.results_table.setRowCount(0); self.progress.clear()
            self.plot_progress_button.setEnabled(False)
            self.update_title()
            return False
        for combo in (self.ratio_reference, self.internal_standard):
            for target in self.collection.targets:
                index = combo.findData(target.id)
                if index >= 0:
                    combo.setItemText(index, target.name)
        missing = sum(sample.time_min is None for sample in self.collection.samples)
        self.note.setText(
            f"{len(self.collection.samples)} measurements; {missing} without reaction times (not plotted). "
            "Areas/ratios are detector-signal trends, not calibrated conversion. "
            + ("Select a measurement, drag limits/baseline points, enter A/B/C/D or a custom name, and integrate. Plot progress opens integral-% curves in a new window."
               if self.collection.integration_mode == "individual" else
               "Drag the overlay window to change a common window or the selected measurement's override."))
        self.display_results = [r for r in self.results if r["assigned"]] if self.collection.integration_mode == "individual" else self.results
        blocked = self.results_table.blockSignals(True)
        self.results_table.setRowCount(len(self.display_results))
        for row, result in enumerate(self.display_results):
            def display(value):
                return "" if value is None else f"{value:.6g}" if isinstance(value, (float, int)) else str(value)
            values = (result["measurement"], result["reaction_time_min"], result["target"],
                      f"{result['start_min']:.4f}–{result['end_min']:.4f}", result["area"],
                      f"{result['signal_unit']}·min", result["area_percent"], result["ratio"],
                      result["normalized_area"], result["status"])
            for column, value in enumerate(values):
                self.results_table.setItem(row, column, QTableWidgetItem(display(value)))
        self.results_table.blockSignals(blocked)
        self.results_table.resizeColumnsToContents()
        plot_ready = any(len({r["reaction_time_min"] for r in self.results if r["target_id"] == target.id
                             and r["reaction_time_min"] is not None and r["area_percent"] is not None}) >= 2
                         for target in self.collection.targets)
        self.plot_progress_button.setEnabled(plot_ready)
        for window in list(self.progress_windows):
            window.set_results(self.collection, self.results)
        self.draw_plots(); self.update_title()
        return True

    def references_changed(self, *_):
        if self.updating:
            return
        self.collection.ratio_reference = self.ratio_reference.currentData()
        self.collection.internal_standard = self.internal_standard.currentData()
        self.changed()

    def add_target(self):
        if not self.recalculate():
            return
        channels = sorted({c.name for s in self.collection.samples for c in s.channels})
        shared = set(channels)
        for sample in self.collection.samples:
            shared &= {c.name for c in sample.channels}
        channel = sorted(shared)[0] if shared else channels[0]
        traces = [c for s in self.collection.samples for c in s.channels if c.name == channel]
        start = max(float(c.times[0]) for c in traces)
        end = min(float(c.times[-1]) for c in traces)
        if start >= end:
            start, end = float(traces[0].times[0]), float(traces[0].times[-1])
        index = 1
        while any(target.id == f"t{index:03d}" for target in self.collection.targets):
            index += 1
        self.collection.targets.append(ReactionTarget(f"t{index:03d}", f"Compound {index}", channel, start, end, color=COLORS[(index - 1) % len(COLORS)]))
        self.dirty = True; self.render_targets()
        self.targets_table.selectRow(len(self.collection.targets) - 1)
        self.recalculate()

    def remove_target(self):
        target = self.selected_target()
        if target is None:
            return
        self.collection.targets = [t for t in self.collection.targets if t.id != target.id]
        self.collection.overrides = {key: window for key, window in self.collection.overrides.items() if key[1] != target.id}
        self.collection.individual_integrations = {key: spec for key, spec in self.collection.individual_integrations.items() if key[1] != target.id}
        if self.collection.ratio_reference == target.id:
            self.collection.ratio_reference = None
        if self.collection.internal_standard == target.id:
            self.collection.internal_standard = None
        self.dirty = True; self.render_targets(); self.recalculate()

    def choose_color(self, target_id):
        target = next(t for t in self.collection.targets if t.id == target_id)
        color = QColorDialog.getColor(QColor(target.color), self, "Target color")
        if color.isValid():
            target.color = color.name()
            self.dirty = True; self.render_targets(); self.recalculate()

    def selection_changed(self, *_):
        if not self.updating:
            self.sync_individual_selection()
            self.draw_plots()

    def sync_individual_selection(self):
        if self.collection.integration_mode != "individual":
            return
        sample, target = self.selected_sample(), self.selected_target()
        if sample is None:
            return
        self.updating = True
        previous = self.individual_channel.currentText()
        self.individual_channel.clear(); self.individual_channel.addItems([c.name for c in sample.channels])
        self.individual_channel.setCurrentText(previous)
        if self.sender() in (self.targets_table, self.samples_table) and target is not None:
            spec = self.collection.individual_integrations.get((sample.id, target.id))
            self.compound_name.setCurrentText(target.name)
            self.individual_channel.setCurrentText(spec.channel if spec is not None else target.channel)
            if spec is not None:
                self.pending_windows[(sample.id, spec.channel)] = (spec.start_min, spec.end_min)
                self.pending_baselines[(sample.id, spec.channel)] = (spec.baseline, spec.baseline_start, spec.baseline_end)
        self.updating = False

    def choose_compound(self, *_):
        name = self.compound_name.currentText().strip()
        for row, target in enumerate(self.collection.targets):
            if target.name == name:
                self.targets_table.selectRow(row)
                self.selection_changed()
                break

    def compound_changed(self, *_):
        if not self.updating:
            sample = self.selected_sample()
            if sample is not None:
                self.baseline_requests.discard((sample.id, self.individual_channel.currentText()))
            self.draw_plots()

    def baseline_mode_changed(self, *_):
        if not self.updating:
            sample = self.selected_sample()
            if sample is not None:
                self.pending_baselines[(sample.id, self.individual_channel.currentText())] = (self.individual_baseline.currentData(), None, None)
            self.draw_plots()

    def integrate_measurement(self):
        if not self.recalculate():
            return
        sample = self.selected_sample()
        name = self.compound_name.currentText().strip()
        if sample is None or not name:
            self.note.setText("Select a measurement and enter a compound name."); return
        channel = self.individual_channel.currentText()
        trace = next((c for c in sample.channels if c.name == channel), None)
        if trace is None:
            return
        start, end = map(float, self.window_region.getRegion())
        key = (sample.id, channel)
        if key not in self.baseline_requests:
            self.baseline_requests.add(key)
            self.pending_baselines[key] = (self.individual_baseline.currentData(), None, None)
            self.draw_plots()
            self.note.setText("Baseline markers are on the selected interval's trace endpoints. Adjust them, then save the compound integral.")
            return
        method, first, last = self.pending_baselines.get(key, ("endpoints", None, None))
        try:
            integration_curve(trace, start, end, method, first, last)
        except ValueError as error:
            self.note.setText(str(error)); return
        target = next((t for t in self.collection.targets if t.name == name), None)
        updating_existing = target is not None and (sample.id, target.id) in self.collection.individual_integrations
        if target is None:
            index = 1
            while any(t.id == f"t{index:03d}" for t in self.collection.targets):
                index += 1
            target = ReactionTarget(f"t{index:03d}", name, channel, start, end, color=COLORS[(index - 1) % len(COLORS)])
            self.collection.targets.append(target)
        self.collection.individual_integrations[(sample.id, target.id)] = IndividualIntegration(channel, start, end, method, first, last)
        self.baseline_requests.discard(key)
        self.dirty = True; self.render_targets()
        self.targets_table.selectRow(self.collection.targets.index(target))
        self.recalculate()
        if updating_existing and self.results_table.selectionModel().selectedRows():
            self.select_integral()

    def select_integral(self):
        if self.updating or self.collection.integration_mode != "individual":
            return
        row = self.results_table.currentRow()
        if not 0 <= row < len(getattr(self, "display_results", [])):
            return
        result = self.display_results[row]
        self.samples_table.selectRow(next(i for i, s in enumerate(self.collection.samples) if s.id == result["sample_id"]))
        self.targets_table.selectRow(next(i for i, t in enumerate(self.collection.targets) if t.id == result["target_id"]))
        sample = self.selected_sample()
        spec = self.collection.individual_integrations[(result["sample_id"], result["target_id"])]
        self.updating = True
        self.individual_channel.setCurrentText(spec.channel)
        self.compound_name.setCurrentText(result["target"])
        self.updating = False
        key = (sample.id, spec.channel)
        self.pending_windows[key] = (spec.start_min, spec.end_min)
        self.pending_baselines[key] = (spec.baseline, spec.baseline_start, spec.baseline_end)
        self.baseline_requests.add(key)
        self.draw_plots()

    def window_changed(self):
        if self.updating:
            return
        start, end = sorted(map(float, self.window_region.getRegion()))
        if start < 0 or start >= end:
            self.note.setText("Select a nonzero, non-negative retention-time window.")
            return
        sample = self.selected_sample()
        if self.collection.integration_mode == "individual":
            if sample is not None:
                self.pending_windows[(sample.id, self.individual_channel.currentText())] = (start, end)
            return
        target = self.selected_target()
        if target is None:
            return
        if self.edit_sample_window.isChecked():
            if sample is None:
                self.note.setText("Select a measurement before adjusting its individual window.")
                return
            self.collection.overrides[(sample.id, target.id)] = (start, end)
            spec = self.collection.individual_integrations.get((sample.id, target.id))
            if spec is not None:
                spec.start_min, spec.end_min = start, end
        else:
            target.start_min, target.end_min = start, end
            row = self.targets_table.currentRow()
            self.updating = True
            for column, value in ((2, start), (3, end)):
                field = self.targets_table.cellWidget(row, column)
                field.setValue(value)
                field.setProperty("original_value", value)
                field.setProperty("shown_value", field.value())
            self.updating = False
        self.dirty = True; self.recalculate()

    def reset_window(self):
        sample, target = self.selected_sample(), self.selected_target()
        if sample is not None and target is not None:
            self.collection.overrides.pop((sample.id, target.id), None)
            self.collection.individual_integrations.pop((sample.id, target.id), None)
            self.baseline_requests = {key for key in self.baseline_requests if key[0] != sample.id}
            self.dirty = True; self.recalculate()

    def baseline_edited(self, start, end, first, last):
        if self.updating:
            return
        sample, target = self.selected_sample(), self.selected_target()
        if sample is None:
            return
        if self.collection.integration_mode == "individual":
            channel = self.individual_channel.currentText()
            self.pending_windows[(sample.id, channel)] = (start, end)
            self.pending_baselines[(sample.id, channel)] = ("manual", first, last)
        elif target is not None:
            self.collection.individual_integrations[(sample.id, target.id)] = IndividualIntegration(target.channel, start, end, "manual", first, last)
            self.updating = True; self.edit_sample_window.setChecked(True); self.updating = False
            self.dirty = True; self.recalculate()

    def open_progress_plot(self):
        if not self.recalculate() or not self.plot_progress_button.isEnabled():
            return None
        dialog = ReactionProgressDialog(self.collection, self.results, self)
        self.progress_windows.add(dialog)
        dialog.destroyed.connect(lambda *_, d=dialog: self.progress_windows.discard(d))
        dialog.show()
        return dialog

    def draw_plots(self, *_):
        if self.updating:
            return
        self.updating = True
        try:
            self.overlay.clear(); self.progress.clear()
            target, selected = self.selected_target(), self.selected_sample()
            self.baseline_editor.set_trace()
            if self.collection.integration_mode == "individual":
                self.draw_individual_overlay()
            elif target is not None:
                units = set()
                for index, sample in enumerate(self.collection.samples):
                    trace = next((c for c in sample.channels if c.name == target.channel), None)
                    if trace is None:
                        continue
                    units.add(trace.unit)
                    color = COLORS[index % len(COLORS)]
                    label = sample.name + (" (time unassigned)" if sample.time_min is None else f" ({sample.time_min:g} min)")
                    self.overlay.plot(trace.times, trace.values, pen=pg.mkPen(color, width=2 if sample is selected else 1), name=label)
                self.overlay.setLabel("left", "Signal", units=next(iter(units)) if len(units) == 1 else "")
                self.overlay.setTitle(f"{target.name} — {target.channel}")
                window = (target.start_min, target.end_min)
                if selected is not None and self.edit_sample_window.isChecked():
                    window = self.collection.overrides.get((selected.id, target.id), window)
                    spec = self.collection.individual_integrations.get((selected.id, target.id))
                    if spec is not None:
                        window = (spec.start_min, spec.end_min)
                self.window_region.setRegion(window)
                self.overlay.addItem(self.window_region)
                if selected is not None:
                    trace = next((c for c in selected.channels if c.name == target.channel), None)
                    if trace is not None:
                        spec = self.collection.individual_integrations.get((selected.id, target.id))
                        self.baseline_editor.set_trace(trace.times, trace.values, spec.baseline if spec else target.baseline,
                                                       (spec.baseline_start, spec.baseline_end) if spec and spec.baseline == "manual" else None)
            column = self.progress_metric.currentData()
            units = {result["signal_unit"] for result in self.results if result["area"] is not None}
            ylabel = {"area": "Integrated area", "area_percent": "Area fraction (%)", "ratio": "Area / reference", "normalized_area": "Area / internal standard"}[column]
            if column == "area" and len(units) == 1:
                ylabel += f" ({next(iter(units))}·min)"
            self.progress.setLabel("left", ylabel)
            self.progress.setTitle("Reaction progress — detector signal, not calibrated conversion")
            for item in self.collection.targets:
                rows = sorted((r for r in self.results if r["target_id"] == item.id and r["reaction_time_min"] is not None), key=lambda r: r["reaction_time_min"])
                if rows and any(r[column] is not None for r in rows):
                    x = [r["reaction_time_min"] for r in rows]
                    y = [np.nan if r[column] is None else r[column] for r in rows]
                    self.progress.plot(x, y, pen=pg.mkPen(item.color, width=2), symbol="o", symbolSize=6,
                                       symbolBrush=item.color, name=item.name, connect="finite")
        finally:
            self.updating = False

    def draw_individual_overlay(self):
        sample = self.selected_sample()
        if sample is None:
            return
        channel = self.individual_channel.currentText()
        trace = next((c for c in sample.channels if c.name == channel), None)
        if trace is None:
            return
        self.overlay.plot(trace.times, trace.values, pen=pg.mkPen("#48a9ef", width=2), name=f"{sample.name} — {channel}")
        self.overlay.setTitle(f"{sample.name} — select limits, adjust baseline, assign compound")
        self.overlay.setLabel("left", "Signal", units=trace.unit)
        target = self.selected_target()
        for (sample_id, target_id), spec in self.collection.individual_integrations.items():
            if sample_id != sample.id or spec.channel != channel:
                continue
            compound = next(t for t in self.collection.targets if t.id == target_id)
            try:
                x, y, base = integration_curve(trace, spec.start_min, spec.end_min, spec.baseline, spec.baseline_start, spec.baseline_end)
            except ValueError:
                continue
            item = IntegrationAreaItem(x, y, base, selected=target is not None and target.id == target_id,
                                       tooltip=compound.name, color=compound.color)
            self.overlay.addItem(item, ignoreBounds=True)
        default_window = (target.start_min, target.end_min) if target is not None and target.channel == channel else (float(trace.times[0]), float(trace.times[-1]))
        window = self.pending_windows.get((sample.id, channel), default_window)
        self.window_region.setRegion(window)
        self.overlay.addItem(self.window_region, ignoreBounds=True)
        method, first, last = self.pending_baselines.get((sample.id, channel), (self.individual_baseline.currentData(), None, None))
        requested = (sample.id, channel) in self.baseline_requests
        self.integrate_measurement_button.setText("Save / update compound integral" if requested else "Integrate compound in selected measurement")
        if requested:
            self.baseline_editor.set_trace(trace.times, trace.values, method, (first, last) if method == "manual" else None)

    def save(self):
        if not self.recalculate():
            return False
        if self.path is None:
            return self.save_as()
        try:
            save_collection(self.collection, self.path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not save collection", str(error))
            return False
        self.dirty = False; self.update_title()
        return True

    def save_as(self):
        if not self.recalculate():
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save reaction collection", str(self.path or Path.home() / "reaction-kinetics.zip"), "Reaction collections (*.zip)")
        if not path:
            return False
        previous = self.path
        self.path = Path(path if path.lower().endswith(".zip") else path + ".zip")
        if self.save():
            return True
        self.path = previous
        return False

    def export_csv_copy(self):
        if not self.recalculate():
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Export collection with chromatogram CSVs", str(Path.home() / "reaction-kinetics-csv.zip"), "Reaction collections (*.zip)")
        if not path:
            return False
        try:
            save_collection(self.collection, Path(path if path.lower().endswith(".zip") else path + ".zip"), include_csv=True)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not export CSV copy", str(error))
            return False
        self.note.setText("Exported a collection copy with all chromatogram CSVs. The active collection's save path is unchanged.")
        return True

    def closeEvent(self, event):
        if self.dirty:
            choice = QMessageBox.question(self, "Unsaved reaction collection", "Save changes to this collection?",
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Save)
            if choice == QMessageBox.StandardButton.Cancel or (choice == QMessageBox.StandardButton.Save and not self.save()):
                event.ignore(); return
        self.updating = True
        self.samples_table.blockSignals(True)
        self.targets_table.blockSignals(True)
        self.results_table.blockSignals(True)
        for row in range(self.targets_table.rowCount()):
            for column in range(1, self.targets_table.columnCount()):
                widget = self.targets_table.cellWidget(row, column)
                if widget is not None:
                    widget.blockSignals(True)
        for window in list(self.progress_windows):
            window.close()
        event.accept()

    def reject(self):
        self.close()  # Escape must honor the same unsaved-collection handling.


class ReactionProgressDialog(QDialog):
    """Independent progress plot with user-selected compound series."""
    def __init__(self, collection, results, parent=None):
        super().__init__(parent)
        self.closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Reaction progress — {collection.name}")
        self.resize(950, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose compounds to plot. Integral % is the fraction of assigned integrals in each channel, not calibrated conversion."))
        self.compounds = QListWidget()
        self.compounds.setMaximumHeight(130)
        self.compounds.itemChanged.connect(self.draw_plot)
        layout.addWidget(self.compounds)
        self.plot = pg.PlotWidget()
        self.plot.addLegend(); self.plot.showGrid(x=True, y=True, alpha=.2)
        self.plot.setLabel("bottom", "Reaction time", units="min")
        self.plot.setLabel("left", "Integral (%)")
        layout.addWidget(self.plot)
        self.set_results(collection, results)

    def set_results(self, collection, results):
        previous = {self.compounds.item(i).data(Qt.ItemDataRole.UserRole): self.compounds.item(i).checkState() for i in range(self.compounds.count())}
        self.targets = [replace(t) for t in collection.targets]
        self.results = [dict(row) for row in results]
        self.compounds.blockSignals(True); self.compounds.clear()
        for target in self.targets:
            item = QListWidgetItem(target.name)
            item.setData(Qt.ItemDataRole.UserRole, target.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(previous.get(target.id, Qt.CheckState.Checked))
            item.setForeground(QColor(target.color))
            self.compounds.addItem(item)
        self.compounds.blockSignals(False)
        self.draw_plot()

    def draw_plot(self, *_):
        if self.closing or not hasattr(self, "plot"):
            return
        self.plot.clear()
        checked = {self.compounds.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.compounds.count())
                   if self.compounds.item(i).checkState() == Qt.CheckState.Checked}
        for target in self.targets:
            if target.id not in checked:
                continue
            rows = sorted((row for row in self.results if row["target_id"] == target.id and row["reaction_time_min"] is not None), key=lambda row: row["reaction_time_min"])
            if rows and any(r["area_percent"] is not None for r in rows):
                self.plot.plot([r["reaction_time_min"] for r in rows],
                               [np.nan if r["area_percent"] is None else r["area_percent"] for r in rows],
                               pen=pg.mkPen(target.color, width=2), symbol="o", symbolBrush=target.color,
                               name=target.name, connect="finite")

    def closeEvent(self, event):
        self.closing = True
        self.compounds.blockSignals(True)
        event.accept()
