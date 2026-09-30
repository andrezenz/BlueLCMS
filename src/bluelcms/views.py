"""Interactive, resolution-aware graphics for the standalone desktop host."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal


def pixel_buckets(x, y, minimum, maximum, pixels):
    """Sum all source bins that map to one rendered x pixel, never thin them."""
    x, y = np.asarray(x), np.asarray(y)
    if len(x) == 0 or maximum <= minimum or pixels < 1:
        return np.array([]), np.array([]), 1
    visible = (x >= minimum) & (x <= maximum)
    x, y = x[visible], y[visible]
    width = (maximum - minimum) / pixels
    indexes = np.clip(((x - minimum) / width).astype(int), 0, pixels - 1)
    bins, inverse = np.unique(indexes, return_inverse=True)
    return minimum + (bins + .5) * width, np.bincount(inverse, weights=y), width


def positive_zoom_range(current_upper, zoom_in):
    """Scale a non-negative intensity axis while retaining a physical zero."""
    factor = .9 if zoom_in else 1 / .9
    return 0, max(np.finfo(float).eps, current_upper * factor)


class ResetViewBox(pg.ViewBox):
    reset_requested = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.reset_requested.emit()
        else:
            super().mouseDoubleClickEvent(event)


class RegionViewBox(ResetViewBox):
    region_dragged = Signal(float, float)

    def mouseDragEvent(self, event, axis=None):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.region_dragged.emit(
                self.mapToView(event.buttonDownPos()).x(), self.mapToView(event.pos()).x())
        else:
            super().mouseDragEvent(event, axis)


class UVPlot(pg.PlotWidget):
    def __init__(self):
        self.view = RegionViewBox()
        super().__init__(viewBox=self.view)
        self.setLabel("bottom", "Retention time", units="min")
        self.setLabel("left", "UV signal")
        self.showGrid(x=True, y=True, alpha=.2)
        self.trace = self.plot(pen=pg.mkPen("#48a9ef", width=2))
        self.region = pg.LinearRegionItem(brush=(72, 169, 239, 45), movable=False)
        for line in self.region.lines:
            line.setMovable(True)
        self.addItem(self.region)
        self.region.hide()
        self.view.region_dragged.connect(lambda a, b: self.region.setRegion((min(a, b), max(a, b))))
        self.view.reset_requested.connect(self.enableAutoRange)


class MassPlot(pg.PlotWidget):
    changed = Signal()

    def __init__(self, title):
        self.view = MassViewBox()
        super().__init__(viewBox=self.view, title=title)
        self.setLabel("bottom", "m/z", units="Th")
        self.setLabel("left", "Summed intensity")
        self.showGrid(x=True, y=True, alpha=.2)
        self.data = []
        self.view.sigRangeChanged.connect(lambda *_: self.changed.emit())
        self.view.reset_requested.connect(self.reset)

    def reset(self):
        if self.data:
            x = np.concatenate([item[0] for item in self.data if len(item[0])])
            if len(x):
                self.setXRange(x.min(), x.max(), padding=.03)
                self.enableAutoRange(axis="y")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.changed.emit()


class MassViewBox(ResetViewBox):
    """Wheel scales intensity only; left drag selects an m/z interval."""

    def wheelEvent(self, event, axis=None):
        event.accept()
        upper = max(0, self.viewRange()[1][1])
        lower, upper = positive_zoom_range(upper, event.delta() > 0)
        self.setYRange(lower, upper, padding=0)

    def mouseDragEvent(self, event, axis=None):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(event, axis)
            return
        event.accept()
        if event.isFinish():
            start = self.mapToView(event.buttonDownPos()).x()
            end = self.mapToView(event.pos()).x()
            if abs(end - start) > 1e-9:
                self.setXRange(min(start, end), max(start, end), padding=0)


def loading_overlay(plot, visible):
    if not hasattr(plot, "loading") or plot.loading.scene() is None:
        plot.loading = pg.TextItem("Loading…", color="#f0f0f0", anchor=(.5, .5))
        plot.loading.setZValue(100)
        plot.addItem(plot.loading)
    plot.setEnabled(not visible)
    plot.setStyleSheet("background-color: #6a6a6a;" if visible else "")
    plot.loading.setVisible(visible)
    if visible:
        rect = plot.getViewBox().viewRect()
        plot.loading.setPos(rect.center())
