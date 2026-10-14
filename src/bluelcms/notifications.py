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
        self.gdbus = shutil.which("gdbus") if sys.platform == "linux" else None
        self.notify_send = shutil.which("notify-send") if sys.platform == "linux" else None
        self.mode = None
        self.pending = {}
        self.notification_ids = set()
        self.connection = None
        self.available = False
        if sys.platform != "linux" or QApplication.platformName() in ("offscreen", "minimal"):
            return
        try:
            from PySide6.QtDBus import QDBusConnection
        except ImportError:
            QDBusConnection = None
        if QDBusConnection is not None and self.gdbus:
            connection = QDBusConnection.sessionBus()
            if connection.isConnected():
                service, path, interface = "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications"
                connected = connection.connect(service, path, interface, "ActionInvoked", self, SLOT("notification_action(uint,QString)"))
                connection.connect(service, path, interface, "NotificationClosed", self, SLOT("notification_closed(uint,uint)"))
                if connected:
                    self.connection = connection
                    self.mode = "gdbus"
        if self.mode is None and self.notify_send:
            self.mode = "notify-send"
        self.available = self.mode is not None

    def show(self, title, body):
        if not self.available:
            return False
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        icon = root / "bluelcms.svg" if getattr(sys, "frozen", False) else root / "packaging/linux/bluelcms.svg"
        self.last_notification = (title, body, icon)
        if self.mode == "notify-send":
            return self.send_notify_send(title, body, icon)
        process = QProcess(self)
        self.pending[process] = "gdbus"
        process.finished.connect(lambda code, status, p=process: self.completed(p, code, status))
        process.errorOccurred.connect(lambda error, p=process: self.process_error(p, error))
        # gdbus supplies the exact unsigned-ID/array/map types expected by Notify.
        # It exits immediately; Qt listens for notification clicks on the bus.
        process.start(self.gdbus, [
            "call", "--session", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications", "--timeout", "5",
            "--method", "org.freedesktop.Notifications.Notify", "--",
            "BlueLCMS", "0", str(icon), title, html.escape(body),
            "['default', 'Open BlueLCMS']", "{'desktop-entry': <'BlueLCMS'>}", "5000"])
        return True

    def send_notify_send(self, title, body, icon):
        process = QProcess(self)
        self.pending[process] = "notify-send"
        process.finished.connect(lambda code, status, p=process: self.completed(p, code, status))
        process.errorOccurred.connect(lambda error, p=process: self.process_error(p, error))
        process.start(self.notify_send, [
            "--app-name=BlueLCMS", f"--icon={icon}",
            "--action=default=Open BlueLCMS", "--wait", title, body])
        return True

    def completed(self, process, code, status):
        mode = self.pending.pop(process, None)
        if mode is None:
            return
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        process.deleteLater()
        if mode == "notify-send":
            if code == 0 and output.strip() == "default":
                self.activated.emit()
            elif code != 0 and self.mode == "notify-send":
                self.failed.emit()
            return
        match = re.search(r"\((?:uint32\s+)?(\d+)", output)
        if code == 0 and match:
            self.notification_ids.add(int(match[1]))
        elif self.notify_send:
            title, body, icon = self.last_notification
            self.send_notify_send(title, body, icon)
        else:
            self.failed.emit()

    def process_error(self, process, error):
        mode = self.pending.pop(process, None)
        if error == QProcess.ProcessError.FailedToStart and mode is not None:
            process.deleteLater()
            if mode == "gdbus" and self.notify_send:
                title, body, icon = self.last_notification
                self.send_notify_send(title, body, icon)
            else:
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
