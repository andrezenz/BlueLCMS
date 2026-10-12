"""Render the shared BlueLCMS SVG into a multi-resolution Windows icon."""

import io
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    root = Path(__file__).resolve().parents[2]
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "packaging/windows/bluelcms.ico"
    renderer = QSvgRenderer(str(root / "packaging/linux/bluelcms.svg"))
    if not renderer.isValid():
        raise RuntimeError("The BlueLCMS SVG icon could not be loaded.")
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("The rendered icon could not be encoded.")
    with Image.open(io.BytesIO(bytes(buffer.data()))) as png:
        png.save(destination, format="ICO", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])


if __name__ == "__main__":
    main()
