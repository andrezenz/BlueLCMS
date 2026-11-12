import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bluelcms.views import UVPlot


def test_mouse_drags_baseline_points_and_limits_without_background_clicks():
    app = QApplication.instance() or QApplication([])
    plot = UVPlot(); plot.resize(900, 450); plot.show()
    clicks = []
    plot.uv_clicked.connect(clicks.append)
    try:
        plot.trace.setData([0., 1., 2.], [0., 2., 0.])
        plot.region.setBounds((0, 2)); plot.region.setRegion((.5, 1.5)); plot.region.show()
        plot.setXRange(0, 2, padding=0); plot.setYRange(0, 2.5, padding=0)
        editor = plot.baseline_editor
        editor.set_trace(np.array([0., 1., 2.]), np.array([0., 2., 0.]))
        app.processEvents()

        def pixel(x, y):
            return plot.mapFromScene(plot.view.mapViewToScene(QPointF(x, y)))

        def drag(start, end):
            QTest.mouseMove(plot.viewport(), pixel(*start))
            QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, pos=pixel(*start))
            for fraction in (.5, 1.):
                QTest.qWait(30)
                position = pixel(start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction)
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(plot.viewport().mapToGlobal(position)),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(plot.viewport(), event)
            QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, pos=pixel(*end))
            app.processEvents()

        drag((.5, 1.), (.3, .6))
        assert plot.region.getRegion()[0] == pytest.approx(.3, abs=.02)
        assert editor.points[0].pos().y() == pytest.approx(.6, abs=.03)
        assert not clicks
        editor.set_trace(np.array([0., 1., 2.]), np.array([0., 2., 0.]))
        drag((1.5, 1.8), (1.7, 1.8))
        assert plot.region.getRegion()[1] == pytest.approx(1.7, abs=.02)
        assert not clicks
        QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton, pos=pixel(1., 2.3))
        assert len(clicks) == 1
        assert clicks[0] == pytest.approx(1., abs=.02)
    finally:
        plot.close(); app.processEvents()
