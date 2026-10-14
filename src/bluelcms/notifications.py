"""Native Linux desktop notifications without triggering GNOME's ready alert."""

import html
from pathlib import Path
import re
import shutil
import sys

from PySide6.QtCore import QObject, QProcess, Signal, Slot, SLOT
from PySide6.QtWidgets import QApplication


class DesktopNotifications(QObject):
    activated = Signal()
    failed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = shutil.which("gdbus") if sys.platform == "linux" else None
        self.pending = {}
        self.notification_ids = set()
        self.connection = None
        self.available = False
        if not self.program or QApplication.platformName() in ("offscreen", "minimal"):
            return
        try:
            from PySide6.QtDBus import QDBusConnection
        except ImportError:
            return
        connection = QDBusConnection.sessionBus()
        if not connection.isConnected():
            return
        service, path, interface = "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications"
        connected = connection.connect(service, path, interface, "ActionInvoked", self, SLOT("notification_action(uint,QString)"))
        connection.connect(service, path, interface, "NotificationClosed", self, SLOT("notification_closed(uint,uint)"))
        self.connection = connection
        self.available = connected

    def show(self, title, body):
        if not self.available:
            return False
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        icon = root / "bluelcms.svg" if getattr(sys, "frozen", False) else root / "packaging/linux/bluelcms.svg"
        process = QProcess(self)
        self.pending[process] = True
        process.finished.connect(lambda code, status, p=process: self.completed(p, code))
        process.errorOccurred.connect(lambda error, p=process: self.process_error(p, error))
        # gdbus supplies the exact unsigned-ID/array/map types expected by Notify.
        # It exits immediately; Qt listens for notification clicks on the bus.
        process.start(self.program, [
            "call", "--session", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications", "--timeout", "5",
            "--method", "org.freedesktop.Notifications.Notify", "--",
            "BlueLCMS", "0", str(icon), title, html.escape(body),
            "['default', 'Open BlueLCMS']", "{'desktop-entry': <'BlueLCMS'>}", "5000"])
        return True

    def completed(self, process, code):
        if process not in self.pending:
            return
        self.pending.pop(process)
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        match = re.search(r"\((?:uint32\s+)?(\d+)", output)
        process.deleteLater()
        if code == 0 and match:
            self.notification_ids.add(int(match[1]))
        else:
            self.failed.emit()

    def process_error(self, process, error):
        if error == QProcess.ProcessError.FailedToStart and process in self.pending:
            self.pending.pop(process)
            process.deleteLater()
            self.failed.emit()

    @Slot("uint", str)
    def notification_action(self, notification_id, action):
        if notification_id in self.notification_ids and action == "default":
            self.notification_ids.discard(notification_id)
            self.activated.emit()

    @Slot("uint", "uint")
    def notification_closed(self, notification_id, reason):
        self.notification_ids.discard(notification_id)

    def close(self):
        processes = tuple(self.pending)
        self.pending.clear()
        self.notification_ids.clear()
        for process in processes:
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
