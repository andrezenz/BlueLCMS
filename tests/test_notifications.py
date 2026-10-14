import os
import shutil
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bluelcms.notifications import DesktopNotifications


def test_native_notification_skips_automatic_focus(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from bluelcms import settings
    from bluelcms.app import MainWindow

    application = QApplication.instance() or QApplication([])
    preferences = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings, "settings", lambda: preferences)
    calls = []
    class Notifier(QObject):
        activated = Signal()
        failed = Signal()
        def show(self, title, body):
            calls.append((title, body))
            return True
        def close(self):
            pass
    window = MainWindow()
    window.desktop_notifications = Notifier(window)
    monkeypatch.setattr(window, "focus_new_results", lambda: pytest.fail("A native notification must not trigger GNOME's ready popup"))
    try:
        window.notify_new_measurements({tmp_path / "sample.mzML"})
        assert calls[0][0] == "New result available"
        assert "sample.mzML" in calls[0][1]
    finally:
        window.close()


def test_notification_actions_only_activate_known_notifications():
    application = QApplication.instance() or QApplication([])
    notifier = DesktopNotifications()
    clicked = []
    notifier.activated.connect(lambda: clicked.append(True))
    notifier.notification_ids.add(23)
    notifier.notification_action(99, "default")
    notifier.notification_action(23, "unrelated")
    assert not clicked
    notifier.notification_action(23, "default")
    assert clicked == [True]
    notifier.notification_action(23, "default")
    assert clicked == [True]
    notifier.notification_ids.add(24)
    notifier.notification_closed(24, 1)
    assert not notifier.notification_ids


def test_notify_send_fallback_uses_custom_title_and_click_action(monkeypatch):
    import bluelcms.notifications as module

    application = QApplication.instance() or QApplication([])
    calls = []
    class SignalStub:
        def connect(self, callback):
            self.callback = callback
    class ProcessStub:
        def __init__(self, parent=None):
            self.finished = SignalStub()
            self.errorOccurred = SignalStub()
        def start(self, program, args):
            calls.append((program, args))
        def readAllStandardOutput(self):
            return b"default\n"
        def deleteLater(self):
            pass
    monkeypatch.setattr(module, "QProcess", ProcessStub)
    notifier = DesktopNotifications()
    notifier.mode = "notify-send"
    notifier.notify_send = "/usr/bin/notify-send"
    notifier.available = True
    activated = []
    notifier.activated.connect(lambda: activated.append(True))
    assert notifier.show("New result available", "sample.mzML")
    program, arguments = calls[0]
    assert program == "/usr/bin/notify-send"
    assert "New result available" in arguments
    assert "sample.mzML" in arguments
    assert "--action=default=Open BlueLCMS" in arguments
    process = next(iter(notifier.pending))
    notifier.completed(process, 0, None)
    assert activated == [True]


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("dbus-run-session") or not shutil.which("gdbus"), reason="requires a Linux D-Bus test session")
def test_desktop_notification_dbus_protocol_and_click_action():
    code = r'''
import os, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QObject, Signal, Slot, ClassInfo
from PySide6.QtWidgets import QApplication
from PySide6.QtDBus import QDBusConnection
from bluelcms.notifications import DesktopNotifications

app = QApplication([])
QApplication.platformName = staticmethod(lambda: "xcb")

@ClassInfo(**{"D-Bus Interface": "org.freedesktop.Notifications"})
class Daemon(QObject):
    ActionInvoked = Signal("uint", str)
    NotificationClosed = Signal("uint", "uint")
    def __init__(self):
        super().__init__()
        self.received = None
    @Slot(str, "uint", str, str, str, "QStringList", "QVariantMap", int, result="uint")
    def Notify(self, app_name, replacement, icon, title, body, actions, hints, timeout):
        self.received = (app_name, title, body, actions)
        return 23

connection = QDBusConnection.sessionBus()
assert connection.registerService("org.freedesktop.Notifications")
daemon = Daemon()
options = QDBusConnection.RegisterOption.ExportAllSlots | QDBusConnection.RegisterOption.ExportAllSignals
assert connection.registerObject("/org/freedesktop/Notifications", daemon, options)
notifier = DesktopNotifications()
activated = []
failed = []
notifier.activated.connect(lambda: activated.append(True))
notifier.failed.connect(lambda: failed.append(True))
assert notifier.show("New result available", "sample.mzML")
deadline = time.monotonic() + 8
while notifier.pending and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
assert not failed, "native Notify call failed"
assert daemon.received[:3] == ("BlueLCMS", "New result available", "sample.mzML"), daemon.received
assert daemon.received[3] == ["default", "Open BlueLCMS"]
assert 23 in notifier.notification_ids
daemon.ActionInvoked.emit(23, "default")
deadline = time.monotonic() + 2
while not activated and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
assert activated == [True]
notifier.close()
'''
    result = subprocess.run(["dbus-run-session", "--", sys.executable, "-c", code], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
