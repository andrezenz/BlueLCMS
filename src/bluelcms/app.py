"""Standalone Qt desktop entry point."""

import shutil
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QProcess, QRectF, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QSplitter,
    QProgressBar, QSpinBox, QStyle, QVBoxLayout, QWidget)

from . import settings
from .folders import cached_path, copy_to_cache, is_afp_path, remote_mount_roots
from .mzml import discover_files, file_display_name, load_run, mass_histograms
from .views import MassPlot, UVPlot, loading_overlay, pixel_buckets

COLORS = ("#48a9ef", "#f3ae57", "#c17fe8", "#61c98b", "#ed6f8c", "#e3cf4f")


def downloading_icon():
    style = QApplication.style()
    canvas = QPixmap(24, 24); canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload).paint(painter, 0, 0, 18, 18)
    style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown).paint(painter, 8, 8, 16, 16)
    painter.end()
    return QIcon(canvas)


class JobSignals(QObject):
    done = Signal(int, object, str)
    progress = Signal(int, int, int)
    uv_points = Signal(int, object)
    tic_points = Signal(int, object)


class Job(QRunnable):
    def __init__(self, token, function, *args):
        super().__init__()
        self.signals, self.token, self.function, self.args = JobSignals(), token, function, args

    def run(self):
        try: self.signals.done.emit(self.token, self.function(*self.args), "")
        except Exception as error: self.signals.done.emit(self.token, None, str(error))


class CopyJob(Job):
    def run(self):
        try:
            result = copy_to_cache(self.args[0], self.args[1],
                                   lambda copied, total: self.signals.progress.emit(self.token, copied, total))
        except Exception as error:
            self.signals.done.emit(self.token, None, str(error))
        else:
            self.signals.done.emit(self.token, result, "")


class LoadJob(Job):
    def __init__(self, token, path, wavelength):
        super().__init__(token, load_run, path)
        self.wavelength = wavelength

    def run(self):
        points = []
        tic = []

        def flush():
            nonlocal points, tic
            if points:
                self.signals.uv_points.emit(self.token, points)
                points = []
            if tic:
                self.signals.tic_points.emit(self.token, tic)
                tic = []

        def stream(scan):
            if len(scan.wavelength) and scan.wavelength.min() <= self.wavelength <= scan.wavelength.max():
                index = int(np.argmin(np.abs(scan.wavelength - self.wavelength)))
                points.append((scan.time, scan.intensity[index], scan.wavelength[index]))
                if len(points) >= 64:
                    flush()
        def stream_ms(scan):
            tic.append((scan.time, float(scan.intensity.sum()), scan.polarity))
            if len(tic) >= 64:
                flush()
        try:
            result = load_run(self.args[0], progress=lambda copied, total: self.signals.progress.emit(self.token, copied, total), dad_callback=stream, scan_callback=stream_ms)
            flush()
        except Exception as error:
            self.signals.done.emit(self.token, None, str(error))
        else:
            self.signals.done.emit(self.token, result, "")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⌊Blue⌋ LCMS")
        self.resize(1250, 850)
        self.folder = None
        self.runs, self.histograms, self.stream_uv, self.stream_tic, self.run_data = {}, {}, {}, {}, None
        self.load_token = self.region_token = self.folder_token = 0
        self.jobs, self.pool = set(), QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.loading_phase = 0; self.loading_timer = QTimer(self); self.loading_timer.setInterval(250); self.loading_timer.timeout.connect(self.animate_loading)
        self.stream_timer = QTimer(self); self.stream_timer.setSingleShot(True); self.stream_timer.setInterval(75); self.stream_timer.timeout.connect(self.draw_uv)
        self.progress = QProgressBar(); self.progress.setFixedWidth(260); self.progress.setTextVisible(True); self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        menu = self.menuBar().addMenu("Settings")
        for text, slot in (("Choose mzML folder…", self.choose_folder),
                           ("Choose mounted remote folder…", self.choose_remote_folder),
                           ("Choose local cache folder…", self.choose_cache_folder),
                           ("Open debug terminal…", self.open_debug_terminal),
                           ("Refresh file list", self.refresh_files)):
            action = QAction(text, self); action.triggered.connect(slot); menu.addAction(action)
        self.show_date_prefix = QAction("Show date prefix in file list", self)
        self.show_date_prefix.setCheckable(True)
        self.show_date_prefix.setChecked(settings.show_date_prefix())
        self.show_date_prefix.toggled.connect(self.set_show_date_prefix)
        menu.addAction(self.show_date_prefix)
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

    def submit_copy(self, token, source, cache):
        job = CopyJob(token, copy_to_cache, source, cache)
        self.jobs.add(job)
        job.signals.progress.connect(lambda t, copied, total, p=source: self.cache_progress(t, p, copied, total))
        job.signals.done.connect(lambda t, result, error, p=source: self.cached(t, p, result, error))
        job.signals.done.connect(lambda *_: self.jobs.discard(job))
        self.pool.start(job)

    def submit_load(self, token, path, source, callback):
        job = LoadJob(token, source, self.wavelength.value())
        self.jobs.add(job)
        job.signals.progress.connect(lambda t, copied, total, p=source: self.load_progress(t, p, copied, total))
        job.signals.uv_points.connect(lambda t, points, p=path: self.streamed_uv_points(t, p, points))
        job.signals.tic_points.connect(lambda t, points, p=path: self.streamed_tic_points(t, p, points))
        job.signals.done.connect(callback)
        job.signals.done.connect(lambda *_: self.jobs.discard(job))
        self.pool.start(job)

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

    def choose_cache_folder(self):
        initial = settings.cache_folder() or Path.home()
        if folder := QFileDialog.getExistingDirectory(self, "Choose local AFP mzML cache folder", str(initial)):
            settings.set_cache_folder(Path(folder))
            self.refresh_cache_indicators()
            self.statusBar().showMessage(f"AFP cache folder: {folder}")

    def set_show_date_prefix(self, show):
        settings.set_show_date_prefix(show)
        for index in range(self.files.count()):
            item = self.files.item(index)
            item.setText(file_display_name(item.data(Qt.ItemDataRole.UserRole), show))

    def open_debug_terminal(self):
        terminal = shutil.which("x-terminal-emulator")
        if not terminal:
            QMessageBox.warning(self, "No terminal found", "Install an x-terminal-emulator, then try again.")
            return
        root = Path(__file__).resolve().parents[2]
        if not QProcess.startDetached(terminal, ["-e", sys.executable, str(root / "debug_launch.py")]):
            QMessageBox.warning(self, "Debug terminal failed", "The system terminal could not be started.")

    def cache_for(self, source):
        return cached_path(source, settings.cache_folder())

    def refresh_cache_indicators(self):
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        for index in range(self.files.count()):
            item = self.files.item(index); cache = self.cache_for(item.data(Qt.ItemDataRole.UserRole))
            item.setIcon(icon if cache and cache.is_file() else QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            item.setToolTip("Cached locally" if cache and cache.is_file() else "Remote source")

    def set_download_state(self, path, active):
        for index in range(self.files.count()):
            item = self.files.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                if active:
                    item.setIcon(downloading_icon())
                    item.setToolTip("Downloading remote source…")
                else:
                    self.refresh_cache_indicators()
                return

    def refresh_files(self):
        if not self.folder: return
        self.files.clear(); self.runs.clear(); self.stream_uv.clear(); self.stream_tic.clear(); self.histograms.clear(); self.run_data = None; self.uv.region.hide(); self.folder_label.setText(str(self.folder)); self.folder_token += 1; self.set_loading(True); self.submit(self.folder_token, discover_files, self.files_listed, self.folder)

    def files_listed(self, token, paths, error):
        if token != self.folder_token: return
        self.set_loading(False)
        if error: self.statusBar().showMessage(f"Cannot read folder: {error}. Reconnect remote shares, then refresh."); return
        for path in paths:
            item = QListWidgetItem(file_display_name(path, settings.show_date_prefix())); item.setData(Qt.ItemDataRole.UserRole, path); self.files.addItem(item)
        self.refresh_cache_indicators()
        self.statusBar().showMessage(f"{len(paths)} mzML files found. Select one or more files." if paths else "No mzML files found in this folder.")

    def select_files(self):
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        self.load_token += 1; token = self.load_token; self.runs = {p: r for p, r in self.runs.items() if p in paths}; self.stream_uv = {p: [] for p in paths if p not in self.runs}; self.stream_tic = {p: [] for p in paths if p not in self.runs}; self.histograms.clear()
        missing = [p for p in paths if p not in self.runs]
        if missing: self.set_loading(True)
        for path in missing:
            cache = self.cache_for(path)
            source = cache if cache and cache.is_file() else path
            self.set_download_state(path, source == path and is_afp_path(path))
            size = source.stat().st_size / (1024 * 1024) if source.exists() else 0
            self.statusBar().showMessage(f"Loading {path.name} ({size:.1f} MiB)…")
            self.progress.setRange(0, 0); self.progress.setFormat(f"Loading {path.name}…"); self.progress.show()
            self.submit_load(token, path, source, lambda t, r, e, p=path: self.loaded(t, p, r, e))
        self.draw_uv(); self.timer.start()

    def loaded(self, token, path, run, error):
        if token != self.load_token: return
        if error:
            self.set_download_state(path, False)
            self.progress.hide()
            self.statusBar().showMessage(f"Unable to load {path.name}: {error}")
            return
        self.runs[path] = run
        self.stream_uv.pop(path, None)
        self.stream_tic.pop(path, None)
        self.run_data = run
        cache = self.cache_for(path)
        if cache and not cache.is_file():
            self.submit_copy(token, path, cache)
        else:
            self.set_download_state(path, False)
            self.progress.hide()
        if len(self.runs) == len(self.files.selectedItems()): self.set_loading(False); self.draw_uv(); self.timer.start()

    def streamed_uv_points(self, token, path, points):
        """Queue a compact live preview; expensive drawing runs at most 13 fps."""
        if token != self.load_token or path not in self.stream_uv:
            return
        self.stream_uv[path].extend(points)
        if not self.stream_timer.isActive():
            self.stream_timer.start()

    def streamed_tic_points(self, token, path, points):
        if token != self.load_token or path not in self.stream_tic:
            return
        self.stream_tic[path].extend(points)
        if not self.stream_timer.isActive():
            self.stream_timer.start()

    def load_progress(self, token, path, copied, total):
        if token != self.load_token:
            return
        self.show_progress("Loading", path, copied, total)

    def cached(self, token, path, cache, error):
        if token != self.load_token:
            return
        if error:
            self.set_download_state(path, False)
            self.progress.hide()
            self.statusBar().showMessage(f"Loaded {path.name}, but local caching failed: {error}")
            return
        self.refresh_cache_indicators()
        self.progress.hide()
        self.statusBar().showMessage(f"Cached {path.name} locally")

    def cache_progress(self, token, path, copied, total):
        if token != self.load_token:
            return
        self.show_progress("Caching", path, copied, total)

    def show_progress(self, action, path, copied, total):
        if total:
            percent = round(copied * 100 / total)
            self.progress.setRange(0, total); self.progress.setValue(copied)
            self.progress.setFormat(f"{action} {percent}%")
        else:
            self.progress.setRange(0, 0); self.progress.setFormat(f"{action}…")
        self.progress.show()
        self.statusBar().showMessage(f"{action} {path.name}: {copied / 1048576:.1f} / {total / 1048576:.1f} MiB")

    def set_loading(self, visible):
        for plot in (self.uv, self.positive, self.negative): loading_overlay(plot, visible)
        if visible: self.loading_timer.start(); self.statusBar().showMessage("Loading mzML data…")
        else: self.loading_timer.stop()

    def animate_loading(self):
        self.loading_phase = (self.loading_phase + 1) % 4
        for plot in (self.uv, self.positive, self.negative):
            if hasattr(plot, "loading") and plot.loading.isVisible(): plot.loading.setText("Loading" + "." * self.loading_phase)

    def draw_uv(self):
        loading = self.loading_timer.isActive()
        self.uv.clear(); self.uv.addItem(self.uv.region); self.uv.region.hide()
        self.uv.tic_view.clear()
        if loading:
            loading_overlay(self.uv, True)
        if not self.runs and not self.stream_uv: self.uv.setTitle("UV / DAD — select one or more mzML files"); return
        target = self.wavelength.value()
        if self.mode.currentText() == "DAD heatmap":
            if not self.runs:
                self.uv.setTitle("DAD heatmap — loading complete DAD data…")
                return
            run = next(iter(self.runs.values())); times, waves, matrix = run.heatmap()
            if len(times):
                image = pg.ImageItem(matrix.T); image.setRect(QRectF(times.min(), waves.min(), np.ptp(times) or 1, np.ptp(waves) or 1)); self.uv.addItem(image); self.uv.setLabel("left", "Wavelength", units="nm"); self.uv.setTitle("DAD heatmap (first selected file)")
            return
        all_times = []
        tic_by_polarity = {"+": {}, "-": {}}
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        for index, path in enumerate(selected):
            if path in self.runs:
                times, signal, used = self.runs[path].uv_trace(target)
                tic = [(scan.time, float(scan.intensity.sum()), scan.polarity) for scan in self.runs[path].scans]
            else:
                values = np.asarray(self.stream_uv.get(path, []), dtype=float).reshape(-1, 3)
                times, signal, used = values[:, 0], values[:, 1], values[:, 2]
                tic = self.stream_tic.get(path, [])
            if len(times): self.uv.plot(times, signal, pen=pg.mkPen(COLORS[index % len(COLORS)], width=2), name=path.name); all_times.extend(times)
            for time, intensity, polarity in tic:
                tic_by_polarity[polarity][time] = tic_by_polarity[polarity].get(time, 0) + intensity
        for polarity, color, label in (("+", "#4ecf88", "Positive MS TIC"), ("-", "#f36f6f", "Negative MS TIC")):
            if tic_by_polarity[polarity]:
                points = sorted(tic_by_polarity[polarity].items())
                values = np.asarray(points, dtype=float)
                self.uv.tic_view.addItem(pg.PlotCurveItem(values[:, 0], values[:, 1], pen=pg.mkPen(color, width=1.5, style=Qt.PenStyle.DashLine), name=label))
        suffix = " (streaming)" if self.stream_uv or self.stream_tic else ""
        self.uv.setLabel("left", "UV signal"); self.uv.setTitle(f"UV / DAD + positive/negative MS TIC — target {target} nm{suffix}; drag to select time")
        if all_times:
            bounds = (min(all_times), max(all_times)); self.uv.region.setBounds(bounds); self.uv.region.setRegion(bounds); self.uv.region.show(); self.uv.enableAutoRange()
        if loading:
            loading_overlay(self.uv, True)

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
            stacked = {}
            for index, result in enumerate(self.histograms.values()):
                x, y = result[polarity]; bx, by, width = pixel_buckets(x, y, low, high, pixels); plot.data.append((x, y))
                if len(bx):
                    base = np.asarray([stacked.get(value, 0) for value in bx])
                    for value, height in zip(bx, by):
                        stacked[value] = stacked.get(value, 0) + height
                    plot.addItem(pg.BarGraphItem(x=bx, y0=base, height=by, width=width, brush=COLORS[index % len(COLORS)], pen=None))
            if not plot.data: plot.setTitle(f"{title} — no MS1 data in selection")
        self.label_peaks()

    def label_peaks(self):
        for plot in (self.positive, self.negative):
            low, high = plot.viewRange()[0]
            candidates = []
            for result in self.histograms.values():
                x, y = result["+" if plot is self.positive else "-"]
                candidates.extend((float(value), float(mass)) for mass, value in zip(x, y) if low <= mass <= high)
            # Labels name actual source bins, never the screen-pixel aggregate.
            peaks = sorted(candidates, reverse=True)[:20]
            used = []
            for value, x in peaks:
                if len(used) == 5:
                    break
                if all(abs(x - previous) > (high - low) / 12 for previous in used):
                    label = pg.TextItem(f"{x:.2f}", color="#e8e8e8", anchor=(.5, 1)); label.setPos(x, value); plot.addItem(label); used.append(x)

    def closeEvent(self, event): self.stream_timer.stop(); self.pool.clear(); self.pool.waitForDone(); super().closeEvent(event)


def main():
    app = QApplication(sys.argv); app.setApplicationName("BlueLCMS"); app.setApplicationVersion("0.3.15"); window = MainWindow(); window.show(); return app.exec()
