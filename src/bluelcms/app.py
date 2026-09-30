"""Standalone Qt desktop entry point."""

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget,
)

from . import settings
from .folders import remote_mount_roots
from .mzml import discover_files, load_run, mass_histograms
from .views import UVPlot, mass_plot


class JobSignals(QObject):
    done = Signal(int, object, str)


class Job(QRunnable):
    def __init__(self, token, function, *args):
        super().__init__()
        self.signals = JobSignals()
        self.token, self.function, self.args = token, function, args

    def run(self):
        try:
            result = self.function(*self.args)
        except Exception as error:
            self.signals.done.emit(self.token, None, str(error))
        else:
            self.signals.done.emit(self.token, result, "")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlueLCMS")
        self.resize(1200, 800)
        self.run_data = None
        self.load_token = 0
        self.region_token = 0
        self.folder_token = 0
        self.jobs = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.folder = None

        menu = self.menuBar().addMenu("Settings")
        choose = QAction("Choose mzML folder…", self)
        choose.triggered.connect(self.choose_folder)
        menu.addAction(choose)
        remote = QAction("Choose mounted remote folder…", self)
        remote.triggered.connect(self.choose_remote_folder)
        menu.addAction(remote)
        refresh = QAction("Refresh file list", self)
        refresh.triggered.connect(self.refresh_files)
        menu.addAction(refresh)

        self.files = QListWidget()
        self.files.setMinimumWidth(180)
        self.files.currentItemChanged.connect(self.select_file)
        self.folder_label = QLabel("Choose a data folder in Settings")
        self.folder_label.setWordWrap(True)
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.files)

        self.uv = UVPlot()
        self.positive = mass_plot("Positive ions")
        self.negative = mass_plot("Negative ions")
        self.negative.setXLink(self.positive)
        masses = QSplitter(Qt.Orientation.Horizontal)
        masses.addWidget(self.positive)
        masses.addWidget(self.negative)
        plots = QSplitter(Qt.Orientation.Vertical)
        plots.addWidget(self.uv)
        plots.addWidget(masses)
        plots.setSizes([400, 350])
        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(sidebar)
        main.addWidget(plots)
        main.setStretchFactor(1, 1)
        main.setSizes([220, 980])
        self.setCentralWidget(main)

        self.region_timer = QTimer(self)
        self.region_timer.setSingleShot(True)
        self.region_timer.setInterval(150)
        self.region_timer.timeout.connect(self.calculate_region)
        self.uv.region.sigRegionChanged.connect(self.region_changed)
        self.statusBar().showMessage("Choose an mzML folder from Settings.")
        saved = settings.data_folder()
        if saved is not None:
            self.folder = saved
            self.refresh_files()

    def submit(self, token, function, callback, *args):
        job = Job(token, function, *args)
        self.jobs.add(job)
        job.signals.done.connect(callback)
        job.signals.done.connect(lambda *_: self.jobs.discard(job))
        self.pool.start(job)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose mzML folder", str(self.folder or Path.home()))
        if folder:
            self.folder = Path(folder)
            settings.set_data_folder(self.folder)
            self.refresh_files()

    def choose_remote_folder(self):
        roots = remote_mount_roots()
        if not roots:
            QMessageBox.information(
                self, "Mounted remote folders",
                "Connect to your AFP share in the system file manager first "
                "(afp://server/share). On Linux, GVFS FUSE support must be installed "
                "to expose it as a local path.\n\n"
                "For shares mounted at /mnt, /media, or another filesystem path, "
                "use Settings → Choose mzML folder instead.",
            )
            return
        dialog = QFileDialog(self, "Choose a folder inside a mounted remote share")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setSidebarUrls([QUrl.fromLocalFile(str(path)) for path in [Path.home(), *roots]])
        dialog.setDirectory(str(roots[0]))
        if dialog.exec() and dialog.selectedFiles():
            self.folder = Path(dialog.selectedFiles()[0])
            settings.set_data_folder(self.folder)
            self.refresh_files()

    def refresh_files(self):
        if self.folder is None:
            return
        self.files.clear()
        self.clear_data()
        self.folder_label.setText(str(self.folder))
        self.folder_token += 1
        self.statusBar().showMessage("Listing mzML files…")
        self.submit(self.folder_token, discover_files, self.files_listed, self.folder)

    def files_listed(self, token, paths, error):
        if token != self.folder_token:
            return
        if error:
            self.statusBar().showMessage(f"Cannot read folder: {error}. Reconnect remote shares, then refresh.")
            return
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.files.addItem(item)
        self.statusBar().showMessage(f"{len(paths)} mzML files found. Select a file." if paths else "No mzML files found in this folder.")

    def clear_data(self):
        self.load_token += 1
        self.region_token += 1
        self.region_timer.stop()
        self.run_data = None
        self.uv.trace.clear()
        self.uv.region.hide()
        self.uv.setTitle("UV / DAD — 254 nm")
        self.clear_masses()

    def clear_masses(self):
        for plot, title in ((self.positive, "Positive ions"), (self.negative, "Negative ions")):
            plot.clear()
            plot.setTitle(title)

    def select_file(self, item, previous=None):
        self.clear_data()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self.statusBar().showMessage(f"Loading {path.name}…")
        self.submit(self.load_token, load_run, self.loaded, path)

    def loaded(self, token, run, error):
        if token != self.load_token:
            return
        if error:
            self.statusBar().showMessage("Unable to load mzML file.")
            QMessageBox.warning(self, "mzML loading failed", error)
            return
        self.run_data = run
        if not len(run.times):
            self.uv.setTitle("UV / DAD unavailable — no wavelength data covering 254 nm")
            self.statusBar().showMessage("No usable DAD trace; time-region selection is unavailable.")
            return
        wavelengths = np.unique(run.wavelengths)
        label = f"{wavelengths[0]:g}" if len(wavelengths) == 1 else f"{wavelengths.min():g}–{wavelengths.max():g}"
        self.uv.setTitle(f"UV / DAD — {label} nm (target 254 nm); drag to select time")
        self.uv.trace.setData(run.times, run.uv)
        bounds = (float(run.times.min()), float(run.times.max()))
        self.uv.region.setBounds(bounds)
        self.uv.region.setRegion(bounds)
        self.uv.region.show()
        self.uv.autoRange()
        self.region_changed()

    def region_changed(self):
        self.region_token += 1
        self.clear_masses()
        if self.run_data is not None and self.uv.region.isVisible():
            self.statusBar().showMessage("Updating selected-region MS1 histograms…")
            self.region_timer.start()

    def calculate_region(self):
        if self.run_data is None:
            return
        start, end = self.uv.region.getRegion()
        self.submit(self.region_token, mass_histograms, self.histograms_ready, self.run_data, start, end)

    def histograms_ready(self, token, result, error):
        if token != self.region_token:
            return
        if error:
            self.statusBar().showMessage(f"Histogram error: {error}")
            return
        for polarity, plot, title in (("+", self.positive, "Positive ions"), ("-", self.negative, "Negative ions")):
            x, y = result[polarity]
            plot.clear()
            plot.setTitle(title if len(x) else f"{title} — no MS1 data in selection")
            if len(x):
                plot.addItem(pg.BarGraphItem(x=x, height=y, width=0.1, brush="#48a9ef" if polarity == "+" else "#f3ae57", pen=None))
            plot.enableAutoRange()
        start, end = self.uv.region.getRegion()
        skipped = self.run_data.skipped_scans
        self.statusBar().showMessage(f"{start:.3f}–{end:.3f} min | MS1 intensity sums | 0.1 Th bins | {skipped} scans excluded (missing time or polarity)")

    def closeEvent(self, event):
        self.region_timer.stop()
        self.pool.clear()
        self.pool.waitForDone()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BlueLCMS")
    app.setApplicationVersion("0.2.2")
    window = MainWindow()
    window.show()
    return app.exec()
