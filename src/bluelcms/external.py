"""Command-line and local IPC requests to open a measurement in BlueLCMS."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


@dataclass(frozen=True)
class OpenRequest:
    path: str
    start: float | None = None
    end: float | None = None
    time: float | None = None
    polarity: str | None = None
    wavelength: int | None = None

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("A measurement path is required.")
        if Path(self.path).suffix.lower() not in (".mzml", ".gz", ".npz"):
            raise ValueError("External requests support mzML, compressed mzML, and BlueLCMS cache files.")
        if (self.start is None) != (self.end is None):
            raise ValueError("Specify both --start and --end.")
        for value in (self.start, self.end, self.time):
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("Retention times must be finite, non-negative minutes.")
        if self.start is not None and self.end < self.start:
            raise ValueError("The interval end must not precede its start.")
        if self.time is not None and self.start is not None:
            raise ValueError("Use either --time or --start/--end.")
        if self.polarity not in (None, "+", "-"):
            raise ValueError("Polarity must be positive or negative.")
        if self.wavelength is not None and (not isinstance(self.wavelength, int) or not 1 <= self.wavelength <= 2000):
            raise ValueError("Wavelength must be between 1 and 2000 nm.")

    def encode(self):
        return json.dumps(asdict(self)).encode("utf-8") + b"\n"

    @classmethod
    def decode(cls, payload):
        request = cls(**json.loads(payload))
        if not Path(request.path).is_absolute():
            raise ValueError("IPC requests require an absolute measurement path.")
        return request


def parse_request(arguments):
    parser = argparse.ArgumentParser(description="BlueLCMS measurement viewer")
    parser.add_argument("--open", dest="path", help="Open a measurement from any folder")
    parser.add_argument("--start", type=float, help="Interval start in minutes")
    parser.add_argument("--end", type=float, help="Interval end in minutes")
    parser.add_argument("--time", type=float, help="Select the nearest MS scan at this time in minutes")
    parser.add_argument("--polarity", choices=("positive", "negative", "+", "-"), help="Focus a polarity and restrict nearest-scan selection")
    parser.add_argument("--wavelength", type=int, help="UV wavelength in nm")
    values = vars(parser.parse_args(arguments))
    if values["path"] is None:
        if any(value is not None for value in values.values()):
            parser.error("Spectrum options require --open.")
        return None
    values["path"] = str(Path(values["path"]).expanduser().absolute())
    values["polarity"] = {"positive": "+", "negative": "-"}.get(values["polarity"], values["polarity"])
    try:
        return OpenRequest(**values)
    except ValueError as error:
        parser.error(str(error))


def server_name():
    user = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    return f"BlueLCMS-open-{user}"


def forward_request(request, name=None, timeout=5000):
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout):
        return False
    socket.write(request.encode())
    socket.flush()
    if not socket.canReadLine() and not socket.waitForReadyRead(timeout):
        raise RuntimeError("The running BlueLCMS instance did not acknowledge the request.")
    reply = bytes(socket.readLine()).decode().strip()
    socket.disconnectFromServer()
    if reply != "accepted":
        raise RuntimeError(reply or "The running BlueLCMS instance rejected the request.")
    return True


class OpenRequestServer(QObject):
    requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept_connections)
        self.buffers = {}

    def listen(self, name=None):
        name = name or server_name()
        if self.server.listen(name):
            return True
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(200):
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(name)
        return self.server.listen(name)

    def accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.buffers[socket] = bytearray()
            socket.readyRead.connect(lambda connection=socket: self.read_request(connection))
            socket.disconnected.connect(lambda connection=socket: self.buffers.pop(connection, None))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self.read_request(socket)

    def read_request(self, socket):
        payload = self.buffers.get(socket)
        if payload is None:
            return
        payload.extend(bytes(socket.readAll()))
        if len(payload) > 65536:
            socket.disconnectFromServer()
            return
        if b"\n" not in payload:
            return
        try:
            request = OpenRequest.decode(bytes(payload).split(b"\n", 1)[0])
        except (ValueError, TypeError) as error:
            socket.write((f"Invalid open request: {error}\n").encode())
        else:
            socket.write(b"accepted\n")
            socket.flush()
            socket.disconnectFromServer()
            self.requested.emit(request)
            return
        socket.flush()
        socket.disconnectFromServer()

    def close(self):
        for socket in tuple(self.buffers):
            socket.abort()
        self.server.close()
