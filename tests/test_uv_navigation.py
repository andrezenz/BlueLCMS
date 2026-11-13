import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bluelcms.views import UVPlot


@pytest.mark.parametrize("lower", (-20., 15.))
def test_uv_wheel_preserves_current_lower_y_and_x_range(lower):
    app = QApplication.instance() or QApplication([])
    plot = UVPlot()
    class Wheel:
        def delta(self): return 120
        def accept(self): pass
    try:
        plot.setXRange(1, 9, padding=0); plot.setYRange(lower, lower + 100, padding=0)
        plot.view.wheelEvent(Wheel())
        np.testing.assert_allclose(plot.view.viewRange()[0], [1, 9])
        np.testing.assert_allclose(plot.view.viewRange()[1], [lower, lower + 90])
    finally:
        plot.close(); app.processEvents()


def test_dragging_axes_pans_only_the_selected_axis():
    app = QApplication.instance() or QApplication([])
    plot = UVPlot(); plot.resize(900, 450); plot.show()
    try:
        plot.trace.setData([0, 5, 10], [-10, 50, 0])
        plot.setXRange(0, 10, padding=0); plot.setYRange(-20, 100, padding=0)
        plot.region.setRegion((2, 4)); plot.region.show()
        app.processEvents()
        def drag_axis(name, dx, dy):
            axis = plot.getAxis(name)
            start = plot.mapFromScene(axis.mapToScene(axis.shape().boundingRect().center()))
            end = start + QPointF(dx, dy).toPoint()
            QTest.mouseMove(plot.viewport(), start)
            QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, pos=start)
            for fraction in (.5, 1.):
                QTest.qWait(30)
                pos = start + QPointF(dx * fraction, dy * fraction).toPoint()
                QApplication.sendEvent(plot.viewport(), QMouseEvent(
                    QEvent.Type.MouseMove, QPointF(pos), QPointF(plot.viewport().mapToGlobal(pos)),
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
            QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, pos=end)
            app.processEvents()
        before = plot.view.viewRange()
        drag_axis("left", 0, 30)
        after_y = plot.view.viewRange()
        np.testing.assert_allclose(after_y[0], before[0])
        assert after_y[1][0] != pytest.approx(before[1][0])
        assert np.diff(after_y[1])[0] == pytest.approx(np.diff(before[1])[0])
        drag_axis("bottom", 40, 0)
        after_x = plot.view.viewRange()
        np.testing.assert_allclose(after_x[1], after_y[1])
        assert after_x[0][0] != pytest.approx(after_y[0][0])
        assert plot.region.getRegion() == (2, 4)
    finally:
        plot.close(); app.processEvents()
