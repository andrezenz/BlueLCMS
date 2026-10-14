"""Standalone Qt desktop entry point."""

import os
import json
import shutil
import sys
from threading import Event
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QRectF, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
    QLabel, QListWidget, QMainWindow, QMessageBox, QSplitter,
    QDialog, QDialogButtonBox, QDockWidget, QHBoxLayout, QPushButton, QProgressBar, QSpinBox, QStyle,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget, QInputDialog)

from . import settings
from .folders import cached_path, cleanup_expired_cache, is_afp_path, legacy_cached_path, remote_mount_roots
from .integrations import integrate_trace, load_integrations, save_integrations
from . import updater
from . import releases
from . import package_updater
from .sidebar import MeasurementItem, MeasurementTree
from .external import OpenRequestServer, forward_request, parse_request
from .version import application_version
from .help import DocumentDialog
from .mzml import NATIVE_BIN_WIDTH, display_bin_width, discover_files, file_display_name, load_run, mass_histograms, rebin_histogram, write_compact_cache
from .vendor import (MeasurementKey, VendorMeasurement, advion_raw_path, discover_vendor_measurements,
    load_vendor_measurement)


def vendor_display_name(measurement, show_date_prefix: bool) -> str:
    """Label a matched measurement the same way mzML files are labelled."""
    if show_date_prefix:
        return f"{measurement.key.date}_{measurement.key.sample}   [Agilent + Advion]"
    return f"{measurement.key.sample}   [Agilent + Advion]"


def integration_anchor(source):
    """Map a sidebar source to the file whose fingerprint identifies its integrations."""
    if isinstance(source, VendorMeasurement):
        archive = next((item for item in sorted(source.agilent.iterdir()) if item.suffix.lower() == ".dx"), None) if source.agilent.is_dir() else None
        return archive or source.agilent
    return source


def integration_beside_source(source):
    """Vendor folders are usually read-only shares, so never write beside them."""
    return not isinstance(source, VendorMeasurement) and source.is_file()


def measurement_tooltip(measurement) -> str:
    """List the vendor files that make up one displayed measurement."""
    spectra = sum(1 for source in (measurement.advion_positive, measurement.advion_negative) if advion_raw_path(source))
    lines = [
        measurement.label,
        f"Agilent HPLC/DAD: {measurement.agilent.name}",
        f"Advion ESI +: {measurement.advion_positive.name}",
        f"Advion ESI -: {measurement.advion_negative.name}",
        "Mass spectra available." if spectra == 2 else "Chromatograms only: open the run in Advion Mass Express to enable mass spectra.",
    ]
    return "\n".join(lines)
from .views import MassPlot, UVPlot, loading_overlay, pixel_buckets

COLORS = ("#48a9ef", "#f3ae57", "#c17fe8", "#61c98b", "#ed6f8c", "#e3cf4f")


def cache_metadata(source):
    if isinstance(source, VendorMeasurement):
        return json.dumps({"vendor": True, "date": source.key.date, "sample": source.key.sample,
                           "replicate": source.key.replicate, "agilent": str(source.agilent),
                           "positive": str(source.advion_positive), "negative": str(source.advion_negative)})
    return json.dumps({"path": str(source)})


def discover_cached_measurements(folder):
    entries = {}
    if folder is None or not folder.is_dir():
        return entries
    for cache in folder.glob("*.bluelcms.npz"):
        try:
            with np.load(cache, allow_pickle=False) as data:
                metadata = json.loads(str(data["source_metadata"])) if "source_metadata" in data and str(data["source_metadata"]) else {}
            if metadata.get("vendor"):
                source = VendorMeasurement(MeasurementKey(metadata["date"], metadata["sample"], metadata["replicate"]),
                                           Path(metadata["agilent"]), Path(metadata["positive"]), Path(metadata["negative"]))
            else:
                source = Path(metadata["path"]) if "path" in metadata else cache
            entries[source] = cache
        except (OSError, ValueError, KeyError):
            continue
    for cache in folder.iterdir():
        if cache.is_file() and not cache.name.startswith(".") and cache.suffix.lower() in (".mzml", ".gz"):
            entries[cache] = cache
    return entries


def source_available(source):
    if isinstance(source, VendorMeasurement):
        return source.agilent.is_dir() and source.advion_positive.is_file() and source.advion_negative.is_file()
    return source.is_file()


def measurement_state_icon(state):
    """A source monitor, monitor with disk, or standalone disk."""
    canvas = QPixmap(24, 24); canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setPen(QPen(QColor("#48a9ef" if state != "cache-only" else "#61c98b"), 2))
    if state != "cache-only":
        painter.drawRect(2, 2, 17, 12); painter.drawLine(10, 14, 10, 19); painter.drawLine(5, 19, 15, 19)
    if state != "source-only":
        painter.setBrush(QColor("#61c98b")); painter.drawRect(12 if state == "source-cached" else 4, 12 if state == "source-cached" else 4, 10 if state == "source-cached" else 16, 10 if state == "source-cached" else 16)
        painter.setPen(QPen(QColor("#163c28"), 2)); painter.drawLine(16 if state == "source-cached" else 8, 15 if state == "source-cached" else 8, 19 if state == "source-cached" else 16, 15 if state == "source-cached" else 8)
    painter.end()
    return QIcon(canvas)


def start_packaged_process(executable, arguments):
    process = QProcess()
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
    process.setProcessEnvironment(environment)
    process.setProgram(executable)
    process.setArguments(arguments)
    started, _ = process.startDetached()
    return started


def downloading_icon():
    style = QApplication.style()
    canvas = QPixmap(24, 24); canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload).paint(painter, 0, 0, 18, 18)
    style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown).paint(painter, 8, 8, 16, 16)
    painter.end()
    return QIcon(canvas)


def compacted_icon():
    style = QApplication.style()
    canvas = QPixmap(24, 24); canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton).paint(painter, 0, 0, 18, 18)
    painter.setPen(QPen(QColor("#58dce6"), 2))
    for y in (15, 18, 21):
        painter.drawLine(13, y, 22, y)
    painter.end()
    return QIcon(canvas)


def application_icon() -> QIcon:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    icon = root / "bluelcms.svg" if getattr(sys, "frozen", False) else root / "packaging" / "linux" / "bluelcms.svg"
    return QIcon(str(icon))


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


class PausableLoadJob(Job):
    def __init__(self, token, function, *args):
        super().__init__(token, function, *args)
        self.ready = Event()
        self.ready.set()

    def pause(self):
        self.ready.clear()

    def resume(self):
        self.ready.set()

    def report_progress(self, done, total):
        self.ready.wait()
        self.signals.progress.emit(self.token, done, total)


class VendorLoadJob(PausableLoadJob):
    """Load one matched Agilent + Advion measurement, reporting step progress."""

    def __init__(self, token, measurement):
        super().__init__(token, load_vendor_measurement, measurement)
        self.measurement = measurement

    def run(self):
        try:
            result = load_vendor_measurement(
                self.measurement,
                progress=self.report_progress)
        except Exception as error:
            self.signals.done.emit(self.token, None, str(error))
        else:
            self.signals.done.emit(self.token, result, "")


class LoadJob(PausableLoadJob):
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
            self.ready.wait()
            if len(scan.wavelength) and scan.wavelength.min() <= self.wavelength <= scan.wavelength.max():
                index = int(np.argmin(np.abs(scan.wavelength - self.wavelength)))
                points.append((scan.time, scan.intensity[index], scan.wavelength[index]))
                if len(points) >= 64:
                    flush()
        def stream_ms(scan):
            self.ready.wait()
            tic.append((scan.time, float(scan.intensity.sum()), scan.polarity))
            if len(tic) >= 64:
                flush()
        try:
            self.ready.wait()
            result = load_run(self.args[0], progress=self.report_progress, dad_callback=stream, scan_callback=stream_ms)
            flush()
        except Exception as error:
            self.signals.done.emit(self.token, None, str(error))
        else:
            self.signals.done.emit(self.token, result, "")


class LocationsDialog(QDialog):
    def __init__(self, locations, parent=None):
        super().__init__(parent)
        self.setWindowTitle("mzML locations")
        self.resize(620, 320)
        self.locations = QListWidget()
        self.locations.addItems([str(path) for path in locations])
        add = QPushButton("Add folder…"); add.clicked.connect(self.add_folder)
        remove = QPushButton("Remove selected"); remove.clicked.connect(lambda: self.locations.takeItem(self.locations.currentRow()))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self); layout.addWidget(QLabel("Files from all listed folders appear together in the sidebar.")); layout.addWidget(self.locations)
        actions = QHBoxLayout(); actions.addWidget(add); actions.addWidget(remove); actions.addStretch(); layout.addLayout(actions); layout.addWidget(buttons)

    def add_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Add mzML folder", str(Path.home())):
            if folder not in [self.locations.item(index).text() for index in range(self.locations.count())]:
                self.locations.addItem(folder)

    def selected_locations(self):
        return [Path(self.locations.item(index).text()) for index in range(self.locations.count())]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⌊Blue⌋ LCMS")
        self.resize(1250, 850)
        self.folders = settings.data_folders()
        self.folder = self.folders[0] if self.folders else None
        self.runs, self.histograms, self.stream_uv, self.stream_tic, self.run_data = {}, {}, {}, {}, None
        self.integrations, self.integration_source = [], None
        self.discovered_measurements = {}
        self.cached_measurements = {}
        self.background_discovery = False
        self.pending_discoveries = 0
        self.source_refresh_timer = QTimer(self)
        self.source_refresh_timer.setInterval(60000)
        self.source_refresh_timer.timeout.connect(lambda: self.refresh_files(background=True))
        self.load_token = self.region_token = self.folder_token = 0
        self.load_queue = []
        self.active_load = None
        self.failed_loads = set()
        self.load_jobs = {}
        self.paused_loads = {}
        self.deferred_results = {}
        self.load_sequence = 0
        self.session_sources = set()
        self.cache_policy = {}
        self.external_requests = []
        self.pending_view_request = None
        self.last_uv_bounds = None
        self.jobs, self.pool = set(), QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.loading_phase = 0; self.loading_timer = QTimer(self); self.loading_timer.setInterval(250); self.loading_timer.timeout.connect(self.animate_loading)
        self.stream_timer = QTimer(self); self.stream_timer.setSingleShot(True); self.stream_timer.setInterval(75); self.stream_timer.timeout.connect(self.draw_uv)
        self.histogram_redraw = QTimer(self); self.histogram_redraw.setSingleShot(True); self.histogram_redraw.setInterval(40); self.histogram_redraw.timeout.connect(self.draw_histograms)
        self.drawing_histograms = False
        self.progress = QProgressBar(); self.progress.setFixedWidth(260); self.progress.setTextVisible(True); self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        toolbar = QToolBar("Display", self)
        self.addToolBar(toolbar)
        self.tic_actions = {}
        for polarity in ("+", "-"):
            action = QAction(f"MS TIC ({polarity})", self)
            action.setCheckable(True)
            action.setChecked(settings.show_tic(polarity))
            action.toggled.connect(lambda show, p=polarity: self.set_show_tic(p, show))
            toolbar.addAction(action)
            self.tic_actions[polarity] = action
        self.show_tic_positive = self.tic_actions["+"]
        self.show_tic_negative = self.tic_actions["-"]
        menu = self.menuBar().addMenu("Settings")
        for text, slot in (("Manage mzML locations…", self.choose_folder),
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
        self.auto_refresh_sources = QAction("Automatically refresh sources every minute", self)
        self.auto_refresh_sources.setCheckable(True)
        self.auto_refresh_sources.setChecked(settings.auto_refresh_sources())
        self.auto_refresh_sources.toggled.connect(self.set_auto_refresh_sources)
        menu.addAction(self.auto_refresh_sources)
        if self.auto_refresh_sources.isChecked():
            self.source_refresh_timer.start()
        update_menu = self.menuBar().addMenu("Update")
        update_actions = (("Update version…", self.select_release),)
        for text, slot in update_actions:
            action = QAction(text, self); action.triggered.connect(slot); update_menu.addAction(action)
        about_menu = self.menuBar().addMenu("About")
        about_action = QAction("About BlueLCMS", self)
        about_action.triggered.connect(self.show_about)
        about_menu.addAction(about_action)
        for text, slot in (("Changelog…", self.show_changelog), ("External program commands…", self.show_external_commands)):
            action = QAction(text, self); action.triggered.connect(slot); about_menu.addAction(action)
        self.files, self.folder_label = MeasurementTree(), QLabel("Choose a data folder in Settings")
        self.files.itemSelectionChanged.connect(self.select_files)
        self.folder_label.setWordWrap(True)
        self.wavelength = QSpinBox(); self.wavelength.setRange(1, 2000); self.wavelength.setValue(254); self.wavelength.setSuffix(" nm")
        self.wavelength.valueChanged.connect(self.draw_uv)
        self.mode = QComboBox(); self.mode.addItems(("UV traces", "DAD heatmap")); self.mode.currentIndexChanged.connect(self.draw_uv)
        self.cache_expiry = QSpinBox(); self.cache_expiry.setRange(0, 365); self.cache_expiry.setValue(settings.cache_expiry_days()); self.cache_expiry.setSuffix(" days")
        self.cache_expiry.setSpecialValueText("Never")
        self.cache_expiry.setToolTip("Cached files are automatically removed after this many days (0 = never expire)")
        self.cache_expiry.valueChanged.connect(self.set_cache_expiry)
        controls = QWidget(); controls_layout = QVBoxLayout(controls); controls_layout.addWidget(QLabel("Wavelength")); controls_layout.addWidget(self.wavelength); controls_layout.addWidget(self.mode); controls_layout.addWidget(QLabel("Cache expiry")); controls_layout.addWidget(self.cache_expiry); controls_layout.addWidget(self.folder_label); controls_layout.addWidget(self.files)
        self.uv, self.positive, self.negative = UVPlot(), MassPlot("Positive ions"), MassPlot("Negative ions")
        self.negative.setXLink(self.positive); self.positive.changed.connect(self.schedule_histogram_draw); self.negative.changed.connect(self.schedule_histogram_draw)
        masses = QSplitter(Qt.Orientation.Vertical); masses.addWidget(self.positive); masses.addWidget(self.negative)
        plots = QSplitter(Qt.Orientation.Vertical); plots.addWidget(self.uv); plots.addWidget(masses); plots.setSizes([410, 360])
        root = QSplitter(Qt.Orientation.Horizontal); root.addWidget(controls); root.addWidget(plots); root.setStretchFactor(1, 1); root.setSizes([250, 1000]); self.setCentralWidget(root)
        self.integration_table = QTableWidget(0, 5)
        self.integration_table.setHorizontalHeaderLabels(("Start (min)", "Stop (min)", "Wavelength (nm)", "Absolute integral", "% of integrals"))
        self.integration_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.integration_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_integration)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_integrations)
        integration_panel = QWidget()
        integration_layout = QVBoxLayout(integration_panel)
        integration_layout.addWidget(self.integration_table)
        actions = QHBoxLayout(); actions.addWidget(remove); actions.addWidget(clear); actions.addStretch()
        integration_layout.addLayout(actions)
        self.integration_dock = QDockWidget("UV integrations", self)
        self.integration_dock.setWidget(integration_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.integration_dock)
        self.integration_dock.hide()
        self.timer = QTimer(self); self.region_timer = self.timer; self.timer.setSingleShot(True); self.timer.setInterval(120); self.timer.timeout.connect(self.calculate_region)
        self.uv.region.sigRegionChanged.connect(lambda: self.timer.start())
        self.uv.integrate_requested.connect(self.integrate_region)
        self.statusBar().showMessage("Choose an mzML folder from Settings.")
        if self.folders or settings.cache_folder(): self.refresh_files()
        removed = cleanup_expired_cache(settings.cache_folder(), settings.cache_expiry_days())
        if removed:
            self.statusBar().showMessage(f"Removed {removed} expired cache file(s)")

    def submit(self, token, function, callback, *args):
        job = Job(token, function, *args); self.jobs.add(job); job.signals.done.connect(callback); job.signals.done.connect(lambda *_: self.jobs.discard(job)); self.pool.start(job)

    def submit_load(self, token, path, source, source_label, callback):
        job = LoadJob(token, source, self.wavelength.value())
        self.load_jobs[path] = job
        self.jobs.add(job)
        job.signals.progress.connect(lambda t, copied, total, p=path, label=source_label: self.load_progress(t, p, label, copied, total))
        job.signals.uv_points.connect(lambda t, points, p=path: self.streamed_uv_points(t, p, points))
        job.signals.tic_points.connect(lambda t, points, p=path: self.streamed_tic_points(t, p, points))
        job.signals.done.connect(callback)
        job.signals.done.connect(lambda *_: self.jobs.discard(job))
        self.pool.start(job)

    def choose_folder(self):
        dialog = LocationsDialog(self.folders, self)
        if dialog.exec():
            self.folders = dialog.selected_locations()
            self.folder = self.folders[0] if self.folders else None
            settings.set_data_folders(self.folders)
            self.refresh_files()

    def choose_remote_folder(self):
        roots = remote_mount_roots()
        if not roots:
            QMessageBox.information(self, "Mounted remote folders", "Mount the AFP share in your system file manager first, then use this action. For /mnt or /media mounts, use the normal folder chooser.")
            return
        dialog = QFileDialog(self, "Choose a mounted remote folder"); dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True); dialog.setFileMode(QFileDialog.FileMode.Directory); dialog.setSidebarUrls([QUrl.fromLocalFile(str(x)) for x in [Path.home(), *roots]]); dialog.setDirectory(str(roots[0]))
        if dialog.exec() and dialog.selectedFiles():
            folder = Path(dialog.selectedFiles()[0])
            self.folders = [*self.folders, folder] if folder not in self.folders else self.folders
            self.folder = self.folders[0] if self.folders else None
            settings.set_data_folders(self.folders)
            self.refresh_files()

    def choose_cache_folder(self):
        initial = settings.cache_folder() or Path.home()
        if folder := QFileDialog.getExistingDirectory(self, "Choose local mzML cache folder", str(initial)):
            settings.set_cache_folder(Path(folder))
            self.cached_measurements = {}
            self.refresh_files()
            self.statusBar().showMessage(f"mzML cache folder: {folder}")

    def set_show_date_prefix(self, show):
        settings.set_show_date_prefix(show)
        for index in range(self.files.count()):
            item = self.files.item(index)
            source = item.data(Qt.ItemDataRole.UserRole)
            item.setText(vendor_display_name(source, show) if isinstance(source, VendorMeasurement) else file_display_name(source, show))

    def set_show_tic(self, polarity, show):
        settings.set_show_tic(show, polarity)
        self.draw_uv()

    def set_cache_expiry(self, days):
        settings.set_cache_expiry_days(days)
        removed = cleanup_expired_cache(settings.cache_folder(), days)
        if removed:
            self.refresh_cache_indicators()
            self.statusBar().showMessage(f"Removed {removed} expired cache file(s)")

    def open_debug_terminal(self):
        terminal = shutil.which("x-terminal-emulator")
        if not terminal:
            QMessageBox.warning(self, "No terminal found", "Install an x-terminal-emulator, then try again.")
            return
        root = Path(__file__).resolve().parents[2]
        if not QProcess.startDetached(terminal, ["-e", sys.executable, str(root / "debug_launch.py")]):
            QMessageBox.warning(self, "Debug terminal failed", "The system terminal could not be started.")

    def show_about(self):
        QMessageBox.about(self, "About BlueLCMS",
                          f"BlueLCMS\nVersion {QApplication.applicationVersion()}\n\nLC-MS and DAD data viewer")

    def show_changelog(self):
        DocumentDialog("BlueLCMS changelog", "CHANGELOG.md", self).exec()

    def show_external_commands(self):
        DocumentDialog("BlueLCMS external program commands", "EXTERNAL_COMMANDS.md", self).exec()

    def check_updates(self):
        self.statusBar().showMessage("Checking GitHub for updates…")
        self.submit(0, updater.status, self.update_status_ready, updater.repository_root(), True)

    def update_status_ready(self, token, result, error):
        if error:
            self.statusBar().showMessage("Could not check for updates.")
            QMessageBox.warning(self, "Update check failed", error)
            return
        releases = ", ".join(result["releases"][:5]) or "No release tags"
        QMessageBox.information(self, "BlueLCMS update status", f"Current branch: {result['branch']}\nCurrent commit: {result['commit']}\n\nRecent releases: {releases}")
        self.statusBar().showMessage("Update check complete.")

    def select_release(self):
        self.statusBar().showMessage("Fetching available releases…")
        if getattr(sys, "frozen", False):
            self.submit(0, releases.published_versions, self.release_options_ready)
        else:
            self.submit(0, updater.available_versions, self.release_options_ready, updater.repository_root())

    def release_options_ready(self, token, result, error):
        if error:
            QMessageBox.warning(self, "Release check failed", error)
            return
        if not result:
            QMessageBox.information(self, "Update version", "No versions are available on GitHub.")
            return
        release, accepted = QInputDialog.getItem(self, "Update version", "GitHub version:", list(result), 0, False)
        if accepted and release:
            self.statusBar().showMessage(f"Downloading and installing {release}…")
            self.progress.setRange(0, 0); self.progress.setFormat("Downloading and installing…"); self.progress.show()
            if getattr(sys, "frozen", False):
                self.submit(0, package_updater.install, self.package_updated, result[release])
            else:
                self.submit(0, updater.update, self.updated, updater.repository_root(), result[release])

    def package_updated(self, token, result, error):
        self.progress.hide()
        if error:
            self.statusBar().showMessage("Update failed.")
            QMessageBox.warning(self, "Update failed", error)
            return
        if "helper" in result:
            answer = QMessageBox.question(self, "Install update", f"Downloaded {result['version']}. Close BlueLCMS to install it?\n\nThe installer will offer to restart when finished.")
            if answer == QMessageBox.StandardButton.Yes:
                if start_packaged_process("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", result["helper"]]):
                    QApplication.quit()
                else:
                    QMessageBox.warning(self, "Update failed", "The installation helper could not be started.")
            return
        self.statusBar().showMessage(f"Installed {result['version']}. Restart to use it.")
        answer = QMessageBox.question(self, "Update complete", f"Installed {result['version']}. Restart now?")
        if answer == QMessageBox.StandardButton.Yes:
            if start_packaged_process(result["executable"], []):
                QApplication.quit()
            else:
                QMessageBox.warning(self, "Restart failed", "Restart BlueLCMS manually to use the installed version.")

    def update_to(self, target):
        answer = QMessageBox.question(self, "Confirm update", f"Update BlueLCMS to {target}?\n\nLocal source changes will prevent the update.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage(f"Updating to {target}…")
        self.submit(0, updater.update, self.updated, updater.repository_root(), target)

    def updated(self, token, result, error):
        self.progress.hide()
        if error:
            self.statusBar().showMessage("Update failed; current application remains running.")
            QMessageBox.warning(self, "Update failed", error)
            return
        answer = QMessageBox.question(self, "Update complete", f"Updated to {result['branch']} at {result['commit']}. Restart now?")
        if answer == QMessageBox.StandardButton.Yes:
            root = updater.repository_root()
            if QProcess.startDetached(str(root / ".venv" / "bin" / "python"), [str(root / "launch.py")]):
                QApplication.quit()
            else:
                QMessageBox.warning(self, "Restart failed", "Restart BlueLCMS manually to use the updated version.")
        else:
            self.statusBar().showMessage("Update complete. Restart BlueLCMS to use the new version.")

    def startup_checks(self):
        self.check_packaged_release()
        if settings.cache_folder() is None:
            answer = QMessageBox.question(self, "No cache folder configured",
                "No cache folder is configured. Choose a folder to enable local caching and offline access to measurements.\n\nChoose a cache folder now?")
            if answer == QMessageBox.StandardButton.Yes:
                self.choose_cache_folder()

    def check_packaged_release(self, manual=False):
        self.submit(0, releases.release, lambda token, result, error: self.packaged_release_ready(token, result, error, manual), "stable")

    def packaged_release_ready(self, token, result, error, manual=False, channel="stable"):
        version = QApplication.applicationVersion()
        if error:
            if manual:
                QMessageBox.warning(self, "Release check failed", error)
            return
        if not result:
            if manual:
                QMessageBox.warning(self, "Release check failed", f"No {channel} release is currently available from GitHub.")
            return
        if not releases.newer_stable_version(result["tag"], version):
            if manual:
                QMessageBox.information(self, "BlueLCMS is current", "This packaged version is the latest GitHub release.")
            return
        answer = QMessageBox.question(self, "BlueLCMS update available", f"A newer stable version, {result['tag']}, is available.\nCurrent version: {version}\n\nSelect a version to install?")
        if answer == QMessageBox.StandardButton.Yes:
            self.select_release()

    def cache_for(self, source):
        if source in self.cached_measurements:
            return self.cached_measurements[source]
        return cached_path(source.agilent if isinstance(source, VendorMeasurement) else source, settings.cache_folder())

    def legacy_cache_for(self, source):
        return legacy_cached_path(source, settings.cache_folder())

    def load_source_label(self, path, source):
        if self.cached_measurements.get(path) == source:
            return "compact local cache" if source.name.endswith(".bluelcms.npz") else "cached mzML"
        if source == path:
            return "original remote mzML" if is_afp_path(path) else "original local mzML"
        return "compact local cache" if source.name.endswith(".bluelcms.npz") else "cached mzML"

    def refresh_cache_indicators(self):
        for index in range(self.files.count()):
            item = self.files.item(index); path = item.data(Qt.ItemDataRole.UserRole)
            cache = self.cache_for(path)
            legacy = None if isinstance(path, VendorMeasurement) else self.legacy_cache_for(path)
            cached = bool((cache and cache.is_file()) or (legacy and legacy.is_file()))
            available = source_available(path) and path != cache
            state = "source-cached" if available and cached else "cache-only" if cached else "source-only"
            item.setIcon(measurement_state_icon(state))
            item.setData(Qt.ItemDataRole.UserRole + 1, state)
            tooltip = {"source-only": "Remote/source only", "source-cached": "Remote/source + cached locally", "cache-only": "Cached only — original source unavailable"}[state]
            if isinstance(path, VendorMeasurement):
                tooltip += "\n" + measurement_tooltip(path)
            else:
                tooltip += f"\n{path}"
            item.setToolTip(tooltip)

    def set_download_state(self, path, active):
        if isinstance(path, VendorMeasurement):
            return
        for index in range(self.files.count()):
            item = self.files.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                if active:
                    item.setIcon(downloading_icon())
                    item.setToolTip("Downloading remote source…")
                else:
                    self.refresh_cache_indicators()
                return

    def set_auto_refresh_sources(self, enabled):
        settings.set_auto_refresh_sources(enabled)
        if enabled:
            self.source_refresh_timer.start()
        else:
            self.source_refresh_timer.stop()

    def refresh_files(self, background=False):
        if background and self.pending_discoveries:
            return
        self.background_discovery = background
        if not self.folders and self.folder:
            self.folders = [self.folder]
        self.files.set_roots(self.folders)
        if not background:
            self.files.clear(); self.runs.clear(); self.stream_uv.clear(); self.stream_tic.clear(); self.histograms.clear(); self.run_data = None; self.uv.region.hide()
        self.folder_token += 1
        if not self.folders and settings.cache_folder() is None:
            self.folder_label.setText("Add mzML locations in Settings")
            self.statusBar().showMessage("No mzML locations configured.")
            return
        self.folder_label.setText(f"{len(self.folders)} mzML location{'s' if len(self.folders) != 1 else ''}")
        self.discovered_paths, self.discovered_measurements, self.discovery_errors = [], {}, []
        self.pending_discoveries = len(self.folders) * 2 + 1
        if not background:
            self.set_loading(True)
        self.submit(self.folder_token, discover_cached_measurements, self.caches_listed, settings.cache_folder())
        if len(self.folders) >= 2:
            agilent_folder, advion_folder = self.folders[0], self.folders[1]
        else:
            agilent_folder, advion_folder = self.folders[0] if self.folders else None, None
        for folder in self.folders:
            self.submit(self.folder_token, discover_files, self.files_listed, folder)
            self.submit(
                self.folder_token,
                discover_vendor_measurements,
                self.measurements_listed,
                folder,
                advion_folder if folder == agilent_folder else None,
            )

    def discovery_finished(self):
        if self.pending_discoveries:
            self.pending_discoveries -= 1
        if self.pending_discoveries:
            return
        if not self.background_discovery:
            self.set_loading(False)
        # Reconcile old caches regardless of which discovery worker finished first.
        for source in self.discovered_paths:
            for expected in (cached_path(source, settings.cache_folder()), legacy_cached_path(source, settings.cache_folder())):
                if expected in self.cached_measurements:
                    self.cached_measurements.pop(expected)
                    self.cached_measurements.setdefault(source, expected)
        paths = set(self.discovered_paths)
        paths.update(self.session_sources)
        for source in self.cached_measurements:
            if isinstance(source, VendorMeasurement):
                self.discovered_measurements.setdefault(source.key, source)
            else:
                paths.add(source)
        existing = {self.files.item(index).data(Qt.ItemDataRole.UserRole): self.files.item(index) for index in range(self.files.count())}
        if self.background_discovery:
            available = paths | set(self.discovered_measurements.values())
            # A transient discovery error must not erase the current sidebar.
            if self.discovery_errors:
                available.update(existing)
            removed_selection = False
            previous_block = self.files.blockSignals(True)
            try:
                for source, item in existing.items():
                    if source not in available:
                        removed_selection |= item.isSelected()
                        self.files.takeItem(self.files.row(item))
            finally:
                self.files.blockSignals(previous_block)
            if removed_selection:
                self.select_files()
        for path in sorted(paths, key=lambda value: value.name.casefold()):
            if path in existing:
                continue
            item = MeasurementItem(file_display_name(path, settings.show_date_prefix())); item.setData(Qt.ItemDataRole.UserRole, path); self.files.addItem(item)
        for measurement in sorted(self.discovered_measurements.values(), key=lambda value: value.key, reverse=True):
            if measurement in existing:
                continue
            item = MeasurementItem(vendor_display_name(measurement, settings.show_date_prefix()))
            item.setData(Qt.ItemDataRole.UserRole, measurement)
            item.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            item.setToolTip(measurement_tooltip(measurement))
            self.files.addItem(item)
        self.refresh_cache_indicators()
        if self.external_requests:
            requests, self.external_requests = self.external_requests, []
            for request in requests:
                self.open_external(request)
        if self.background_discovery:
            return
        pairs = len(self.discovered_measurements)
        found = self.files.count() - pairs
        if self.discovery_errors:
            self.statusBar().showMessage(f"{found} mzML files and {pairs} Agilent+Advion measurements found; {len(self.discovery_errors)} location(s) could not be read.")
        else:
            self.statusBar().showMessage(f"{found} mzML files and {pairs} Agilent+Advion measurements across {len(self.folders)} location(s). Select one or more." if self.files.count() else "No mzML files or matched measurements found in configured locations.")

    def files_listed(self, token, paths, error):
        if token != self.folder_token: return
        if error: self.discovery_errors.append(error)
        elif paths: self.discovered_paths.extend(paths)
        self.discovery_finished()

    def caches_listed(self, token, entries, error):
        if token != self.folder_token: return
        self.cached_measurements = entries or {}
        if error: self.discovery_errors.append(error)
        # Older caches without source metadata can still be matched by filename.
        for source in self.discovered_paths:
            expected = cached_path(source, settings.cache_folder())
            if expected in self.cached_measurements:
                self.cached_measurements.pop(expected)
                self.cached_measurements[source] = expected
        self.discovery_finished()

    def measurements_listed(self, token, measurements, error):
        if token != self.folder_token: return
        if error: self.discovery_errors.append(error)
        else:
            for measurement in measurements:
                self.discovered_measurements.setdefault(measurement.key, measurement)
        self.discovery_finished()

    def select_files(self):
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        if self.pending_view_request and self.pending_view_request[0] not in paths:
            self.pending_view_request = None
        if len(paths) == 1 and self.active_load is not None and self.active_load not in paths:
            previous = self.active_load
            job = self.load_jobs.get(previous)
            if job is not None:
                job.pause()
                self.paused_loads[previous] = (job, self.load_token)
                # Paused jobs retain their parser state on their worker thread.
                self.pool.setMaxThreadCount(3 + len(self.paused_loads))
            self.active_load = None
        self.runs = {p: r for p, r in self.runs.items() if p in paths}
        self.failed_loads.intersection_update(paths)
        self.stream_uv = {p: self.stream_uv.get(p, []) for p in paths if p not in self.runs}
        self.stream_tic = {p: self.stream_tic.get(p, []) for p in paths if p not in self.runs}
        self.histograms.clear(); self.region_token += 1
        self.uv.integration_enabled = len(paths) == 1 and paths[0] in self.runs
        self.refresh_integrations()
        missing = [p for p in paths if p not in self.runs and p not in self.failed_loads and p != self.active_load]
        self.load_queue = [p for p in self.load_queue if p in missing]
        self.load_queue.extend(p for p in missing if p not in self.load_queue)
        if self.active_load is not None:
            self.progress.setFormat(f"Loading {self.queue_marker()} %p%")
        self.start_next_load(update_display=False)
        self.draw_uv(); self.timer.start()
        self.apply_external_view()

    def open_external(self, request):
        if self.pending_discoveries:
            self.external_requests.append(request)
            return
        path = Path(request.path)
        # A caller may also name an existing cache directly.
        path = next((source for source, cache in self.cached_measurements.items() if cache == path and isinstance(source, Path)), path)
        cache = self.cache_for(path)
        cached = bool(cache and cache.is_file())
        if not path.is_file() and not cached:
            QMessageBox.warning(self, "Cannot open measurement", f"The file is unavailable and no local cache was found:\n{path}")
            return
        outside_sources = not any(path.is_relative_to(folder) for folder in self.folders)
        if outside_sources and not cached:
            answer = QMessageBox.question(self, "Cache external measurement",
                f"This measurement is outside your configured source folders:\n{path}\n\nAdd its analysis data to your cache?\n\nNo opens it for this session without caching.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            should_cache = answer == QMessageBox.StandardButton.Yes
            if should_cache and settings.cache_folder() is None:
                folder = QFileDialog.getExistingDirectory(self, "Choose local cache folder", str(Path.home()))
                if not folder:
                    return
                settings.set_cache_folder(Path(folder))
            self.cache_policy[path] = should_cache
        self.session_sources.add(path)
        item = next((self.files.item(index) for index in range(self.files.count()) if self.files.item(index).data(Qt.ItemDataRole.UserRole) == path), None)
        if item is None:
            item = MeasurementItem(file_display_name(path, settings.show_date_prefix()))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.files.addItem(item)
        self.pending_view_request = (path, request)
        self.mode.setCurrentText("UV traces")
        self.showNormal(); self.raise_(); self.activateWindow()
        self.files.setCurrentRow(self.files.row(item))
        if path in self.runs:
            self.apply_external_view()
            if self.cache_policy.get(path, True) and settings.cache_folder() and not cached:
                cache = self.cache_for(path)
                self.submit(self.load_token, write_compact_cache, lambda t, result, error: self.cached(t, path, result, error), self.runs[path], cache, cache_metadata(path))
        self.refresh_cache_indicators()

    def apply_external_view(self):
        if not self.pending_view_request:
            return
        path, request = self.pending_view_request
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
        if path not in self.runs or path not in selected or self.active_load == path:
            return
        self.pending_view_request = None
        run = self.runs[path]
        if request.wavelength is not None:
            self.wavelength.setValue(request.wavelength)
        start, end = request.start, request.end
        if request.time is not None:
            scans = [scan for scan in run.scans if request.polarity is None or scan.polarity == request.polarity]
            if not scans:
                QMessageBox.warning(self, "Spectrum unavailable", "This measurement has no mass scans for the requested polarity.")
                return
            start = end = min(scans, key=lambda scan: abs(scan.time - request.time)).time
        if start is not None:
            times = [scan.time for scan in run.scans] + [scan.time for scan in run.dad]
            if not times or end < min(times) or start > max(times):
                QMessageBox.warning(self, "Spectrum unavailable", "The requested interval is outside this measurement's time range.")
                return
            self.uv.region.setBounds((min(min(times), start), max(max(times), end)))
            self.uv.region.setRegion((start, end))
            self.uv.region.show()
            self.timer.stop()
            self.calculate_region()
        if request.polarity:
            (self.positive if request.polarity == "+" else self.negative).setFocus()

    def queue_marker(self):
        if self.active_load is None:
            return ""
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
        if self.active_load not in selected:
            return "[background]"
        completed = len((set(self.runs) | self.failed_loads) & (selected - {self.active_load}))
        return f"[{completed + 1}/{max(1, len(selected))}]"

    def start_next_load(self, update_display=True):
        if self.active_load is not None:
            return
        if not self.load_queue:
            self.progress.hide(); self.set_loading(False)
            self.uv.integration_enabled = len(self.runs) == 1 and len(self.files.selectedItems()) == 1
            if update_display:
                self.refresh_integrations(); self.draw_uv(); self.timer.start()
                self.apply_external_view()
            if self.paused_loads:
                path = next(iter(self.paused_loads))
                self.resume_load(path)
            return
        path = self.load_queue.pop(0)
        if path in self.paused_loads:
            self.resume_load(path)
            return
        self.active_load = path
        self.load_sequence += 1; self.load_token = self.load_sequence; token = self.load_token
        self.set_loading(True)
        self.progress.setRange(0, 0); self.progress.setFormat(f"Loading {self.queue_marker()}…"); self.progress.show()
        cache = self.cache_for(path)
        if isinstance(path, VendorMeasurement) and not (cache and cache.is_file()):
            self.submit_vendor_load(token, path)
            return
        legacy = None if isinstance(path, VendorMeasurement) else self.legacy_cache_for(path)
        source = cache if cache and cache.is_file() else legacy if legacy and legacy.is_file() else path
        source_label = self.load_source_label(path, source)
        self.set_download_state(path, source == path and is_afp_path(path))
        name = path.label if isinstance(path, VendorMeasurement) else path.name
        self.statusBar().showMessage(f"Loading {self.queue_marker()} {source_label}: {name}…")
        self.submit_load(token, path, source, source_label, lambda t, r, e, p=path: self.loaded(t, p, r, e))

    def resume_load(self, path):
        job, token = self.paused_loads.pop(path)
        self.active_load = path
        self.load_token = token
        self.pool.setMaxThreadCount(3 + len(self.paused_loads))
        if path in self.deferred_results:
            run, error = self.deferred_results.pop(path)
            self.loaded(token, path, run, error)
        else:
            self.progress.setRange(0, 0); self.progress.setFormat(f"Loading {self.queue_marker()}…"); self.progress.show()
            selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
            self.set_loading(path in selected)
            job.resume()

    def finish_load(self, path):
        self.set_download_state(path, False)
        self.stream_uv.pop(path, None); self.stream_tic.pop(path, None)
        if path == self.active_load:
            self.active_load = None
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
        self.start_next_load(update_display=path in selected)

    def snap_wavelength(self, run):
        """Select a wavelength the run actually contains.

        Agilent exports here carry a single fixed channel (250 nm), so leaving the
        control at its mzML default of 254 nm would show an empty plot.
        """
        available = run.uv_wavelengths()
        if len(available) and not (available.min() <= self.wavelength.value() <= available.max()):
            self.wavelength.setValue(int(round(float(available.min()))))

    def submit_vendor_load(self, token, measurement):
        """Load a matched Agilent+Advion pair through the measurement queue."""
        job = VendorLoadJob(token, measurement)
        self.load_jobs[measurement] = job
        self.jobs.add(job)
        job.signals.progress.connect(lambda t, done, total: self.load_progress(t, measurement, "Agilent+Advion measurement", done, total))
        job.signals.done.connect(lambda t, r, e, m=measurement: self.loaded(t, m, r, e))
        job.signals.done.connect(lambda *_: self.jobs.discard(job))
        self.set_loading(True)
        self.progress.setRange(0, 0); self.progress.setFormat(f"Loading {self.queue_marker()} {measurement.label}…"); self.progress.show()
        self.pool.start(job)

    def loaded(self, token, path, run, error):
        if path in self.paused_loads and token == self.paused_loads[path][1]:
            self.deferred_results[path] = (run, error)
            return
        if token != self.load_token: return
        self.load_jobs.pop(path, None)
        if error:
            self.failed_loads.add(path)
            name = path.name if isinstance(path, Path) else path.label
            self.finish_load(path)
            self.statusBar().showMessage(f"Unable to load {name}: {error}")
            return
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
        if path in selected:
            self.runs[path] = run
            self.run_data = run
        self.stream_uv.pop(path, None)
        self.stream_tic.pop(path, None)
        if path in selected and isinstance(path, VendorMeasurement):
            self.snap_wavelength(run)
        if path in selected:
            if selected <= (set(self.runs) | self.failed_loads):
                self.set_loading(False)
            self.draw_uv()
        cache = self.cache_for(path)
        if cache and not cache.is_file() and self.cache_policy.get(path, True):
            name = path.label if isinstance(path, VendorMeasurement) else path.name
            self.progress.setRange(0, 0); self.progress.setFormat(f"Compacting {self.queue_marker()} {name}…"); self.progress.show()
            self.submit(token, write_compact_cache, lambda t, result, error, p=path: self.cached(t, p, result, error), run, cache, cache_metadata(path))
        self.finish_load(path)

    def selected_integration_source(self):
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        return paths[0] if len(paths) == 1 and paths[0] in self.runs else None

    def refresh_integrations(self):
        source = self.selected_integration_source()
        self.integrations, self.integration_source = [], source
        if source is not None:
            records, _, stale = load_integrations(integration_anchor(source), settings.integration_folder(), integration_beside_source(source))
            self.integrations = records
            self.integration_dock.setWindowTitle("UV integrations (source changed)" if stale else "UV integrations")
        self.refresh_integration_table()

    def refresh_integration_table(self):
        self.integration_table.setRowCount(len(self.integrations))
        total = sum(record["absolute_integral"] for record in self.integrations)
        for row, record in enumerate(self.integrations):
            values = (
                f"{record['start_min']:.4f}", f"{record['stop_min']:.4f}",
                f"{record['wavelength_nm']:g}", f"{record['absolute_integral']:.6g}",
                f"{100 * record['absolute_integral'] / total:.2f}%" if len(self.integrations) > 1 and total else "",
            )
            for column, value in enumerate(values):
                self.integration_table.setItem(row, column, QTableWidgetItem(value))
        self.integration_table.resizeColumnsToContents()

    def integrate_region(self):
        source = self.selected_integration_source()
        if source is None:
            return
        start, stop = self.uv.region.getRegion()
        target = self.wavelength.value()
        times, signal, _ = self.runs[source].uv_trace(target)
        try:
            integral = integrate_trace(times, signal, start, stop)
        except ValueError as error:
            self.statusBar().showMessage(f"Cannot integrate: {error}")
            return
        if self.integration_source != source:
            self.refresh_integrations()
        self.integrations.append({"start_min": min(start, stop), "stop_min": max(start, stop), "wavelength_nm": target, "absolute_integral": integral})
        try:
            save_integrations(integration_anchor(source), settings.integration_folder(), self.integrations, integration_beside_source(source))
        except OSError as error:
            self.integrations.pop()
            self.statusBar().showMessage(f"Could not save integration: {error}")
            return
        self.refresh_integration_table()
        self.integration_dock.show()
        self.statusBar().showMessage(f"Integrated {min(start, stop):.4f}–{max(start, stop):.4f} min")

    def remove_integration(self):
        source = self.integration_source
        selected = self.integration_table.selectionModel().selectedRows()
        if source is None or not selected:
            return
        del self.integrations[selected[0].row()]
        save_integrations(integration_anchor(source), settings.integration_folder(), self.integrations, integration_beside_source(source))
        self.refresh_integration_table()

    def clear_integrations(self):
        if self.integration_source is None or not self.integrations:
            return
        self.integrations.clear()
        save_integrations(integration_anchor(self.integration_source), settings.integration_folder(), self.integrations, integration_beside_source(self.integration_source))
        self.refresh_integration_table()

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

    def load_progress(self, token, path, source_label, copied, total):
        if token != self.load_token:
            return
        marker = f"{self.queue_marker()} " if self.active_load is not None else ""
        self.show_progress(f"Loading {marker}{source_label}", path, copied, total)

    def cached(self, token, path, cache, error):
        if token != self.load_token:
            if not error:
                self.cached_measurements[path] = cache
                self.refresh_cache_indicators()
            return
        name = path.label if isinstance(path, VendorMeasurement) else path.name
        if error:
            self.statusBar().showMessage(f"Loaded {name}, but local caching failed: {error}")
            return
        self.cached_measurements[path] = cache
        self.refresh_cache_indicators()
        if self.active_load is None:
            self.statusBar().showMessage(f"Cached {name} locally")

    def show_progress(self, action, path, copied, total):
        if total:
            percent = round(copied * 100 / total)
            self.progress.setRange(0, total); self.progress.setValue(copied)
            self.progress.setFormat(f"{action} {percent}%")
        else:
            self.progress.setRange(0, 0); self.progress.setFormat(f"{action}…")
        self.progress.show()
        name = path.name if isinstance(path, Path) else path.label
        unit = "step" if isinstance(path, VendorMeasurement) else "MiB"
        done, size = (copied, total) if unit == "step" else (copied / 1048576, total / 1048576)
        self.statusBar().showMessage(f"{action} {name}: {done:.0f} / {size:.0f} {unit}")

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
        previous_region = self.uv.region.getRegion()
        preserve_region = self.uv.region.isVisible() and self.last_uv_bounds is not None and previous_region != self.last_uv_bounds
        self.uv.clear(); self.uv.addItem(self.uv.region); self.uv.region.hide()
        self.uv.tic_view.clear()
        enabled_polarities = {polarity for polarity in ("+", "-") if settings.show_tic(polarity)}
        show_tic = bool(enabled_polarities)
        self.uv.showAxis("right", show_tic)
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
                run = self.runs[path]
                times, signal, used = run.uv_trace(target)
                tic = run.tic_points()
            else:
                values = np.asarray(self.stream_uv.get(path, []), dtype=float).reshape(-1, 3)
                times, signal, used = values[:, 0], values[:, 1], values[:, 2]
                tic = self.stream_tic.get(path, [])
            name = path.name if isinstance(path, Path) else path.label
            if len(times): self.uv.plot(times, signal, pen=pg.mkPen(COLORS[index % len(COLORS)], width=2), name=name); all_times.extend(times)
            elif path in self.runs:
                all_times.extend(scan.time for scan in self.runs[path].scans)
            if show_tic and path in self.runs:
                for trace in self.runs[path].auxiliary:
                    self.uv.tic_view.addItem(pg.PlotCurveItem(trace.times, trace.values, pen=pg.mkPen("#9d8ce0", width=1.5, style=Qt.PenStyle.DotLine), name=trace.name))
                    all_times.extend(trace.times.tolist())
            if show_tic:
                for time, intensity, polarity in tic:
                    if polarity in enabled_polarities:
                        tic_by_polarity[polarity][time] = tic_by_polarity[polarity].get(time, 0) + intensity
        if show_tic:
            for polarity, color, label in (("+", "#4ecf88", "MS TIC (+)"), ("-", "#f36f6f", "MS TIC (-)")):
                if tic_by_polarity[polarity]:
                    points = sorted(tic_by_polarity[polarity].items())
                    values = np.asarray(points, dtype=float)
                    self.uv.tic_view.addItem(pg.PlotCurveItem(values[:, 0], values[:, 1], pen=pg.mkPen(color, width=1.5, style=Qt.PenStyle.DashLine), name=label))
        suffix = " (streaming)" if self.stream_uv or self.stream_tic else ""
        title = "UV / DAD" + "".join(f" + MS TIC ({polarity})" for polarity in ("+", "-") if polarity in enabled_polarities)
        self.uv.setLabel("left", "UV signal"); self.uv.setTitle(f"{title} — target {target} nm{suffix}; drag to select time")
        if all_times:
            bounds = (min(all_times), max(all_times))
            self.uv.region.setBounds(bounds)
            region = (max(bounds[0], min(bounds[1], previous_region[0])), max(bounds[0], min(bounds[1], previous_region[1]))) if preserve_region else bounds
            self.uv.region.setRegion(region); self.uv.region.show(); self.uv.enableAutoRange()
            self.last_uv_bounds = bounds
        if loading:
            loading_overlay(self.uv, True)

    def calculate_region(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()}
        if self.active_load is not None and self.active_load in selected:
            return
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
                self.statusBar().showMessage(f"{start:.3f}–{end:.3f} min | MS1 intensity sums | {self.display_bin_width:g} Th display bins")
        for path, run in self.runs.items(): self.submit(self.region_token, mass_histograms, lambda t, r, e, p=path: done(t, r, e, p), run, start, end, NATIVE_BIN_WIDTH)

    def schedule_histogram_draw(self):
        if self.histograms and not self.drawing_histograms:
            self.histogram_redraw.start()

    def draw_histograms(self):
        if self.drawing_histograms:
            return
        self.drawing_histograms = True
        try:
            self._draw_histograms()
        finally:
            self.drawing_histograms = False

    def _draw_histograms(self):
        for polarity, plot, title in (("+", self.positive, "Positive ions"), ("-", self.negative, "Negative ions")):
            plot.clear(); plot.data = []; plot.setTitle(title)
            low, high = plot.getViewBox().viewRange()[0]; pixels = max(1, int(plot.getViewBox().width()))
            full_x = [result[polarity][0] for result in self.histograms.values() if len(result[polarity][0])]
            if full_x and (high < min(x.min() for x in full_x) or low > max(x.max() for x in full_x)):
                plot.setXRange(min(x.min() for x in full_x), max(x.max() for x in full_x), padding=.03)
                low, high = plot.getViewBox().viewRange()[0]
            bin_width = display_bin_width(low, high, pixels)
            stacked = {}
            for index, result in enumerate(self.histograms.values()):
                x, y = rebin_histogram(*result[polarity], bin_width); bx, by, width = pixel_buckets(x, y, low, high, pixels)
                if len(x):
                    plot.data.append((x, y))
                if len(bx):
                    base = np.asarray([stacked.get(value, 0) for value in bx])
                    for value, height in zip(bx, by):
                        stacked[value] = stacked.get(value, 0) + height
                    plot.addItem(pg.BarGraphItem(x=bx, y0=base, height=by, width=width, brush=COLORS[index % len(COLORS)], pen=None))
            if not plot.data: plot.setTitle(f"{title} — no MS1 data in selection")
            self.display_bin_width = bin_width
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

    def closeEvent(self, event):
        if hasattr(self, "open_request_server"):
            self.open_request_server.close()
        self.source_refresh_timer.stop(); self.stream_timer.stop()
        for job in self.load_jobs.values():
            job.resume()
        self.pool.clear(); self.pool.waitForDone(); super().closeEvent(event)


def main():
    request = parse_request(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName("BlueLCMS"); app.setApplicationVersion(application_version()); app.setWindowIcon(application_icon())
    if request:
        try:
            if forward_request(request):
                return 0
        except RuntimeError as error:
            QMessageBox.warning(None, "External open failed", str(error))
            return 1
    window = MainWindow()
    window.open_request_server = OpenRequestServer(window)
    window.open_request_server.requested.connect(window.open_external)
    window.open_request_server.listen()
    window.show()
    QTimer.singleShot(0, window.startup_checks)
    if request:
        QTimer.singleShot(0, lambda: window.open_external(request))
    return app.exec()
