"""Interactive plots for the standalone desktop host."""

import pyqtgraph as pg
from PySide6.QtCore import Signal


class RegionViewBox(pg.ViewBox):
    """Left-drag selects time; other mouse interactions retain QtGraph behavior."""

    region_dragged = Signal(float, float)

    def mouseDragEvent(self, event, axis=None):
        from PySide6.QtCore import Qt

        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            start = self.mapToView(event.buttonDownPos()).x()
            end = self.mapToView(event.pos()).x()
            self.region_dragged.emit(min(start, end), max(start, end))
        else:
            super().mouseDragEvent(event, axis)


class UVPlot(pg.PlotWidget):
    def __init__(self):
        view = RegionViewBox()
        super().__init__(viewBox=view)
        self.setLabel("bottom", "Retention time", units="min")
        self.setLabel("left", "UV signal", units="recorded units")
        self.setTitle("UV / DAD — 254 nm")
        self.showGrid(x=True, y=True, alpha=0.2)
        self.trace = self.plot(pen=pg.mkPen("#48a9ef", width=2))
        self.region = pg.LinearRegionItem(brush=(72, 169, 239, 45), movable=False)
        # Let drags inside the fill reach the ViewBox to select a new interval.
        # The two boundary lines remain independently draggable for resizing.
        for line in self.region.lines:
            line.setMovable(True)
        self.region.setZValue(10)
        self.addItem(self.region)
        self.region.hide()
        view.region_dragged.connect(self.select_region)

    def select_region(self, start, end):
        if self.region.isVisible():
            self.region.setRegion((start, end))


def mass_plot(title: str) -> pg.PlotWidget:
    plot = pg.PlotWidget(title=title)
    plot.setLabel("bottom", "m/z", units="Th")
    plot.setLabel("left", "Summed intensity")
    plot.showGrid(x=True, y=True, alpha=0.2)
    return plot
