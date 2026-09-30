"""Standalone Qt desktop entry point."""

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QSplitter,
    QSpinBox, QVBoxLayout, QWidget)

from . import settings
from .folders import remote_mount_roots
from .mzml import discover_files, load_run, mass_histograms
from .views import MassPlot, UVPlot, loading_overlay, pixel_buckets

COLORS = ("#48a9ef", "#f3ae57", "#c17fe8", "#61c98b", "#ed6f8c", "#e3cf4f")


class JobSignals(QObject):
    done = Signal(int, object, str)


class Job(QRunnable):
    def __init__(self, token, function, *args):
        super().__init__()
        self.signals, self.token, self.function, self.args = JobSignals(), token, function, args

    def run(self):
        try: self.signals.done.emit(self.token, self.function(*self.args), "")
        except Exception as error: self.signals.done.emit(self.token, None, str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlueLCMS")
        self.resize(1250, 850)
        self.folder = None
        self.runs, self.histograms, self.run_data = {}, {}, None
        self.load_token = self.region_token = self.folder_token = 0
        self.jobs, self.pool = set(), QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.loading_phase = 0; self.loading_timer = QTimer(self); self.loading_timer.setInterval(250); self.loading_timer.timeout.connect(self.animate_loading)
        menu = self.menuBar().addMenu("Settings")
        for text, slot in (("Choose mzML folder…", self.choose_folder),
                           ("Choose mounted remote folder…", self.choose_remote_folder),
                           ("Refresh file list", self.refresh_files)):
            action = QAction(text, self); action.triggered.connect(slot); menu.addAction(action)
        self.files, self.folder_label = QListWidget(), QLabel("Choose a data folder in Settings")
        self.files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.files.itemSelectionChanged.connect(self.select_files)
        self.folder_label.setWordWrap(True)
        self.wavelength = QSpinBox(); self.wavelength.setRange(1, 2000); self.wavelength.setValue(254); self.wavelength.setSuffix(" nm")
        self.wavelength.valueChanged.connect(self.draw_uv)
        self.mode = QComboBox(); self.mode.addItems(("UV traces", "DAD heatmap")); self.mode.currentIndexChanged.connect(self.draw_uv)
        controls = QWidget(); controls_layout = QVBoxLayout(controls); controls_layout.addWidget(QLabel("Wavelength")); controls_layout.addWidget(self.wavelength); controls_layout.addWidget(self.mode); controls_layout.addWidget(self.folder_label); controls_layout.addWidget(self.files)
        self.uv, self.positive, self.negative = UVPlot(), MassPlot("Positive ions"), MassPlot("Negative ions")
        self.negative.setXLink(self.positive); self.positive.changed.connect(self.draw_histograms); self.negative.changed.connect(self.draw_histograms)
        masses = QSplitter(Qt.Orientation.Vertical); masses.addWidget(self.positive); masses.addWidget(self.negative)
        plots = QSplitter(Qt.Orientation.Vertical); plots.addWidget(self.uv); plots.addWidget(masses); plots.setSizes([410, 360])
        root = QSplitter(Qt.Orientation.Horizontal); root.addWidget(controls); root.addWidget(plots); root.setStretchFactor(1, 1); root.setSizes([250, 1000]); self.setCentralWidget(root)
        self.timer = QTimer(self); self.region_timer = self.timer; self.timer.setSingleShot(True); self.timer.setInterval(120); self.timer.timeout.connect(self.calculate_region)
        self.uv.region.sigRegionChanged.connect(lambda: self.timer.start())
        self.statusBar().showMessage("Choose an mzML folder from Settings.")
        if saved := settings.data_folder(): self.folder = saved; self.refresh_files()

    def submit(self, token, function, callback, *args):
        job = Job(token, function, *args); self.jobs.add(job); job.signals.done.connect(callback); job.signals.done.connect(lambda *_: self.jobs.discard(job)); self.pool.start(job)

    def choose_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Choose mzML folder", str(self.folder or Path.home())):
            self.folder = Path(folder); settings.set_data_folder(self.folder); self.refresh_files()

    def choose_remote_folder(self):
        roots = remote_mount_roots()
        if not roots:
            QMessageBox.information(self, "Mounted remote folders", "Mount the AFP share in your system file manager first, then use this action. For /mnt or /media mounts, use the normal folder chooser.")
            return
        dialog = QFileDialog(self, "Choose a mounted remote folder"); dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True); dialog.setFileMode(QFileDialog.FileMode.Directory); dialog.setSidebarUrls([QUrl.fromLocalFile(str(x)) for x in [Path.home(), *roots]]); dialog.setDirectory(str(roots[0]))
        if dialog.exec() and dialog.selectedFiles(): self.folder = Path(dialog.selectedFiles()[0]); settings.set_data_folder(self.folder); self.refresh_files()

    def refresh_files(self):
        if not self.folder: return
        self.files.clear(); self.runs.clear(); self.histograms.clear(); self.run_data = None; self.uv.region.hide(); self.folder_label.setText(str(self.folder)); self.folder_token += 1; self.set_loading(True); self.submit(self.folder_token, discover_files, self.files_listed, self.folder)

    def files_listed(self, token, paths, error):
        if token != self.folder_token: return
        self.set_loading(False)
        if error: self.statusBar().showMessage(f"Cannot read folder: {error}. Reconnect remote shares, then refresh."); return
        for path in paths:
            item = QListWidgetItem(path.name); item.setData(Qt.ItemDataRole.UserRole, path); self.files.addItem(item)
        self.statusBar().showMessage(f"{len(paths)} mzML files found. Select one or more files." if paths else "No mzML files found in this folder.")

    def select_files(self):
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        self.load_token += 1; token = self.load_token; self.runs = {p: r for p, r in self.runs.items() if p in paths}; self.histograms.clear()
        missing = [p for p in paths if p not in self.runs]
        if missing: self.set_loading(True)
        for path in missing: self.submit(token, load_run, lambda t, r, e, p=path: self.loaded(t, p, r, e), path)
        self.draw_uv(); self.timer.start()

    def loaded(self, token, path, run, error):
        if token != self.load_token: return
        if error: self.statusBar().showMessage(f"Unable to load {path.name}: {error}"); return
        self.runs[path] = run
        self.run_data = run
        if len(self.runs) == len(self.files.selectedItems()): self.set_loading(False); self.draw_uv(); self.timer.start()

    def set_loading(self, visible):
        for plot in (self.uv, self.positive, self.negative): loading_overlay(plot, visible)
        if visible: self.loading_timer.start(); self.statusBar().showMessage("Loading mzML data…")
        else: self.loading_timer.stop()

    def animate_loading(self):
        self.loading_phase = (self.loading_phase + 1) % 4
        for plot in (self.uv, self.positive, self.negative):
            if hasattr(plot, "loading") and plot.loading.isVisible(): plot.loading.setText("Loading" + "." * self.loading_phase)

    def draw_uv(self):
        self.uv.clear(); self.uv.addItem(self.uv.region); self.uv.region.hide()
        if not self.runs: self.uv.setTitle("UV / DAD — select one or more mzML files"); return
        target = self.wavelength.value()
        if self.mode.currentText() == "DAD heatmap":
            run = next(iter(self.runs.values())); times, waves, matrix = run.heatmap()
            if len(times):
                image = pg.ImageItem(matrix.T); image.setRect(QRectF(times.min(), waves.min(), np.ptp(times) or 1, np.ptp(waves) or 1)); self.uv.addItem(image); self.uv.setLabel("left", "Wavelength", units="nm"); self.uv.setTitle("DAD heatmap (first selected file)")
            return
        all_times = []
        for index, (path, run) in enumerate(self.runs.items()):
            times, signal, used = run.uv_trace(target)
            if len(times): self.uv.plot(times, signal, pen=pg.mkPen(COLORS[index % len(COLORS)], width=2), name=path.name); all_times.extend(times)
        self.uv.setLabel("left", "UV signal"); self.uv.setTitle(f"UV / DAD — target {target} nm; drag to select time")
        if all_times:
            bounds = (min(all_times), max(all_times)); self.uv.region.setBounds(bounds); self.uv.region.setRegion(bounds); self.uv.region.show(); self.uv.enableAutoRange()

    def calculate_region(self):
        if not self.runs or not self.uv.region.isVisible(): return
        self.region_token += 1; self.set_loading(True); start, end = self.uv.region.getRegion(); pending = len(self.runs); collected = {}
        def done(token, result, error, path):
            nonlocal pending
            if token != self.region_token: return
            pending -= 1
            if not error: collected[path] = result
            if not pending:
                self.histograms = collected; self.set_loading(False); self.draw_histograms()
                start, end = self.uv.region.getRegion()
                self.statusBar().showMessage(f"{start:.3f}–{end:.3f} min | MS1 intensity sums | 0.1 Th bins before pixel aggregation")
        for path, run in self.runs.items(): self.submit(self.region_token, mass_histograms, lambda t, r, e, p=path: done(t, r, e, p), run, start, end)

    def draw_histograms(self):
        for polarity, plot, title in (("+", self.positive, "Positive ions"), ("-", self.negative, "Negative ions")):
            plot.clear(); plot.data = []; plot.setTitle(title)
            low, high = plot.getViewBox().viewRange()[0]; pixels = max(1, int(plot.getViewBox().width()))
            full_x = [result[polarity][0] for result in self.histograms.values() if len(result[polarity][0])]
            if full_x and (high < min(x.min() for x in full_x) or low > max(x.max() for x in full_x)):
                plot.setXRange(min(x.min() for x in full_x), max(x.max() for x in full_x), padding=.03)
                low, high = plot.getViewBox().viewRange()[0]
            for index, result in enumerate(self.histograms.values()):
                x, y = result[polarity]; bx, by, width = pixel_buckets(x, y, low, high, pixels); plot.data.append((x, y))
                if len(bx): plot.addItem(pg.BarGraphItem(x=bx, height=by, width=width, brush=COLORS[index % len(COLORS)], pen=None))
            if not plot.data: plot.setTitle(f"{title} — no MS1 data in selection")
        self.label_peaks()

    def label_peaks(self):
        for plot in (self.positive, self.negative):
            bars = [item for item in plot.items() if isinstance(item, pg.BarGraphItem)]
            peaks = sorted(((float(y), float(x)) for bar in bars for x, y in zip(bar.opts["x"], bar.opts["height"])), reverse=True)[:5]
            used = []
            for value, x in peaks:
                if all(abs(x - previous) > (plot.viewRange()[0][1] - plot.viewRange()[0][0]) / 12 for previous in used):
                    label = pg.TextItem(f"{x:.2f}", color="#e8e8e8", anchor=(.5, 1)); label.setPos(x, value); plot.addItem(label); used.append(x)

    def closeEvent(self, event): self.pool.clear(); self.pool.waitForDone(); super().closeEvent(event)


def main():
    app = QApplication(sys.argv); app.setApplicationName("BlueLCMS"); app.setApplicationVersion("0.3.0"); window = MainWindow(); window.show(); return app.exec()
