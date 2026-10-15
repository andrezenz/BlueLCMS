"""Interactive, resolution-aware graphics for the standalone desktop host."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtWidgets import QMenu


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


def heatmap_levels(matrix, sensitivity_percentile):
    """Keep the lower data range and clip highlights at a chosen percentile."""
    values = np.asarray(matrix, dtype=float)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return 0.0, 1.0
    lower = float(finite.min())
    upper = float(np.percentile(finite, sensitivity_percentile))
    if upper <= lower:
        upper = float(finite.max())
    if upper <= lower:
        upper = lower + np.finfo(float).eps
    return lower, upper


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
    integrate_requested = Signal()
    def __init__(self):
        self.view = RegionViewBox()
        super().__init__(viewBox=self.view)
        self.setLabel("bottom", "Retention time", units="min")
        self.setLabel("left", "UV signal")
        self.showAxis("right")
        self.setLabel("right", "MS TIC")
        self.showGrid(x=True, y=True, alpha=.2)
        self.tic_view = pg.ViewBox()
        self.plotItem.scene().addItem(self.tic_view)
        self.getAxis("right").linkToView(self.tic_view)
        self.tic_view.setXLink(self.getViewBox())
        self.getViewBox().sigResized.connect(self.update_tic_view)
        self.trace = self.plot(pen=pg.mkPen("#48a9ef", width=2))
        self.region = pg.LinearRegionItem(brush=(72, 169, 239, 45), movable=False)
        self.integration_enabled = False
        for line in self.region.lines:
            line.setMovable(True)
        self.addItem(self.region)
        self.region.hide()
        self.view.region_dragged.connect(lambda a, b: self.region.setRegion((min(a, b), max(a, b))))
        self.view.reset_requested.connect(self.enableAutoRange)

    def update_tic_view(self):
        self.tic_view.setGeometry(self.getViewBox().sceneBoundingRect())
        self.tic_view.linkedViewChanged(self.getViewBox(), self.tic_view.XAxis)

    def contextMenuEvent(self, event):
        time = self.getViewBox().mapSceneToView(self.mapToScene(event.pos())).x()
        start, stop = self.region.getRegion()
        if self.integration_enabled and self.region.isVisible() and start <= time <= stop:
            menu = QMenu(self)
            integrate = menu.addAction("Integrate")
            if menu.exec(event.globalPos()) == integrate:
                self.integrate_requested.emit()
        else:
            super().contextMenuEvent(event)


class MassPlot(pg.PlotWidget):
    changed = Signal()
    NH3_MASS = 17.026549101
    NA_PLUS_MASS = 22.989220702

    def __init__(self, title):
        self.view = MassViewBox()
        super().__init__(viewBox=self.view, title=title)
        self.setLabel("bottom", "m/z", units="Th")
        self.setLabel("left", "Summed intensity")
        self.showGrid(x=True, y=True, alpha=.2)
        self.data = []
        self.snap_data = []
        self.snap_enabled = False
        self.snap_range = 5.0
        self.snap_unit = "mz"
        self.cursor_position = None
        self.reference_mass = None
        self.reference_lines = []
        self.view.sigRangeChanged.connect(lambda *_: self.changed.emit())
        self.view.reset_requested.connect(self.reset)
        self.cursor_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#ffd25a", width=1, style=Qt.PenStyle.DashLine),
            label="m/z {value:.4f}",
            labelOpts={"position": .95, "color": "#ffd25a", "fill": "#10212d"})
        self.cursor_line.setZValue(20)
        self.cursor_line.hide()
        self.addItem(self.cursor_line, ignoreBounds=True)
        self.scene().sigMouseMoved.connect(self.move_cursor)
        self.view.mass_clicked.connect(self.set_mass_reference)
        self.zoom_region = pg.LinearRegionItem(
            movable=False, brush=(72, 169, 239, 55),
            pen=pg.mkPen("#48a9ef", width=1))
        self.zoom_region.setZValue(10)
        self.zoom_region.hide()
        self.addItem(self.zoom_region, ignoreBounds=True)
        self.view.zoom_dragged.connect(self.preview_mass_zoom)
        self.view.zoom_finished.connect(self.zoom_region.hide)
        # PlotWidget installs clear as an instance alias to PlotItem.clear.
        self.clear = self.clear_spectra

    def move_cursor(self, position):
        self.cursor_position = position
        if self.isEnabled() and self.view.sceneBoundingRect().contains(position):
            self.cursor_line.show()
            self.cursor_line.setPos(self.snapped_mass(self.view.mapSceneToView(position).x(), self.snap_radius_in_mz()))
            self.update_reference_hover(position)
        else:
            self.cursor_line.hide()
            self.update_reference_hover(None)

    def update_reference_hover(self, position):
        hovered = None
        if position is not None and self.view.sceneBoundingRect().contains(position):
            mouse_x = position.x()
            candidates = []
            for line in self.reference_lines:
                x_position = self.view.mapViewToScene(QPointF(line.value(), 0)).x()
                distance = abs(mouse_x - x_position)
                if distance <= 8:
                    candidates.append((distance, line))
            if candidates:
                hovered = min(candidates, key=lambda candidate: candidate[0])[1]
        for line in self.reference_lines:
            if line.label is not None:
                line.label.setVisible(line is hovered)

    def snap_radius_in_mz(self):
        if self.snap_unit == "pixels":
            minimum, maximum = self.view.viewRange()[0]
            width = self.view.sceneBoundingRect().width()
            if width > 0:
                return self.snap_range * (maximum - minimum) / width
        return self.snap_range

    def set_cursor_snapping(self, enabled, radius, unit="mz"):
        self.snap_enabled = enabled
        self.snap_range = radius
        self.snap_unit = unit
        if self.cursor_line.isVisible() and self.cursor_position is not None:
            self.move_cursor(self.cursor_position)

    def preview_mass_zoom(self, start, end):
        self.zoom_region.setRegion((min(start, end), max(start, end)))
        self.zoom_region.show()

    def snapped_mass(self, mass, radius=None):
        if not self.snap_enabled:
            return mass
        radius = self.snap_radius_in_mz() if radius is None else radius
        masses, intensities = [], []
        for x, y in self.snap_data or self.data:
            left = np.searchsorted(x, mass - radius, side="left")
            right = np.searchsorted(x, mass + radius, side="right")
            values, heights = np.asarray(x[left:right]), np.asarray(y[left:right])
            valid = np.isfinite(values) & np.isfinite(heights) & (heights > 0)
            masses.extend(values[valid]); intensities.extend(heights[valid])
        if not masses:
            return mass
        positions, inverse = np.unique(masses, return_inverse=True)
        heights = np.bincount(inverse, weights=intensities)
        strongest = positions[heights == heights.max()]
        return float(strongest[np.argmin(np.abs(strongest - mass))])

    def set_mass_reference(self, mass):
        mass = self.snapped_mass(mass, self.snap_radius_in_mz())
        self.reference_mass = mass
        for line in self.reference_lines:
            self.removeItem(line)
        self.reference_lines = []
        offsets = [("Reference", 0, 230, .87)]
        for sign, direction in (("−", -1), ("+", 1)):
            offsets.extend((
                (f"{sign}NH₃", direction * self.NH3_MASS, 180, .77),
                (f"{sign}Na⁺", direction * self.NA_PLUS_MASS, 180, .67),
                (f"{sign}2NH₃", direction * 2 * self.NH3_MASS, 95, .57),
                (f"{sign}2Na⁺", direction * 2 * self.NA_PLUS_MASS, 95, .47),
                (f"{sign}NH₃{sign}Na⁺", direction * (self.NH3_MASS + self.NA_PLUS_MASS), 95, .37),
            ))
        for name, offset, alpha, label_position in offsets:
            color = (255, 210, 90, alpha)
            line = pg.InfiniteLine(
                pos=mass + offset, angle=90, movable=False,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DotLine),
                label=f"{name}\nm/z {{value:.4f}}",
                labelOpts={"position": label_position, "color": color, "fill": (16, 33, 45, 160)})
            line.setZValue(15)
            self.addItem(line, ignoreBounds=True)
            if line.label is not None:
                line.label.hide()
            self.reference_lines.append(line)

    def leaveEvent(self, event):
        self.cursor_line.hide()
        self.update_reference_hover(None)
        super().leaveEvent(event)

    def clear_spectra(self):
        self.plotItem.clear()
        # Histogram redraws clear data items; keep the hover overlay attached.
        if hasattr(self, "cursor_line"):
            self.addItem(self.cursor_line, ignoreBounds=True)
            self.addItem(self.zoom_region, ignoreBounds=True)
            for line in self.reference_lines:
                self.addItem(line, ignoreBounds=True)

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
    """Wheel scales intensity in the plot or m/z over the x-axis."""
    mass_clicked = Signal(float)
    zoom_dragged = Signal(float, float)
    zoom_finished = Signal()

    def mouseClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.mass_clicked.emit(self.mapToView(event.pos()).x())
        else:
            super().mouseClickEvent(event)

    def wheelEvent(self, event, axis=None):
        event.accept()
        if axis == 0:
            low, high = self.viewRange()[0]
            anchor = self.mapSceneToView(event.scenePos()).x()
            factor = .9 ** (event.delta() / 120)
            self.setXRange(anchor + (low - anchor) * factor, anchor + (high - anchor) * factor, padding=0)
            return
        upper = max(0, self.viewRange()[1][1])
        lower, upper = positive_zoom_range(upper, event.delta() > 0)
        self.setYRange(lower, upper, padding=0)

    def mouseDragEvent(self, event, axis=None):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(event, axis)
            return
        event.accept()
        start = self.mapToView(event.buttonDownPos()).x()
        end = self.mapToView(event.pos()).x()
        if event.isFinish():
            self.zoom_finished.emit()
            if abs(end - start) > 1e-9:
                self.setXRange(min(start, end), max(start, end), padding=0)
        else:
            self.zoom_dragged.emit(start, end)


def loading_overlay(plot, visible):
    if visible and hasattr(plot, "cursor_line"):
        plot.cursor_line.hide()
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
