"""Detail panel for one evaluated build: metrics, mass bar, notices and payload plots."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from dronecalc.core import BuildResult, size_reverse, sweep_payload
from dronecalc.ui.format import mass_parts, metrics_for
from dronecalc.ui.state import AppState
from dronecalc.ui.widgets import MassBar, MetricGrid, NoticeList, make_plot, plot_curve

N_POINTS = 25


class BuildDetail(QScrollArea):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.setWidget(inner)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.title.setWordWrap(True)
        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color: palette(mid);")
        self.metrics = MetricGrid(2)
        self.mass_label = QLabel("Mass breakdown")
        self.mass_bar = MassBar()
        self.notices = NoticeList()
        self.time_plot = make_plot("Flight time vs payload", "payload (kg)", "minutes", 220)
        self.thr_plot = make_plot("Hover throttle vs payload", "payload (kg)", "throttle (%)", 220)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        for w in (
            self.title,
            self.subtitle,
            self.metrics,
            self.mass_label,
            self.mass_bar,
            self.notices,
            self.time_plot,
            self.thr_plot,
        ):
            lay.addWidget(w)
        lay.addStretch(1)
        self.result: BuildResult | None = None
        self.show_result(None)

    def show_result(self, result: BuildResult | None) -> None:
        self.result = result
        has = result is not None
        for w in (
            self.metrics,
            self.mass_label,
            self.mass_bar,
            self.time_plot,
            self.thr_plot,
        ):
            w.setVisible(has)
        if not has:
            self.title.setText("Select a build to see its details")
            self.subtitle.setText("")
            self.notices.setNotices([], [])
            return
        b = result.build
        self.title.setText(f"{b.motor.name}  +  {b.prop.name}  +  {b.battery.name}")
        self.subtitle.setText(
            f"ESC {b.esc.name} | {b.n_rotors} rotors | {b.battery.cells}S "
            f"{b.battery.capacity_mah:.0f} mAh | frame {b.frame_mass_kg * 1000:.0f} g | "
            f"payload {result.payload_kg:g} kg"
        )
        self.metrics.setItems(metrics_for(result))
        self.mass_bar.setParts(mass_parts(result))
        self.notices.setNotices([v.message for v in result.violations], result.warnings)
        self._plots(result)

    def _plots(self, r: BuildResult) -> None:
        s = self.state
        m = s.mission
        rev = size_reverse(
            r.build,
            r.payload_kg,
            m.altitude_m,
            m.temp_offset_c,
            m.payload_power_w,
            s.assumptions,
            s.constraints,
        )
        max_payload = rev.max_payload_kg if rev.can_fly_empty else 0.0
        x_max = max(0.5, 1.25 * max(max_payload, r.payload_kg, 0.2))
        x_max = min(x_max, 30.0)
        xs = [x_max * i / (N_POINTS - 1) for i in range(N_POINTS)]
        pts = sweep_payload(
            r.build,
            xs,
            m.altitude_m,
            m.temp_offset_c,
            m.payload_power_w,
            s.assumptions,
            s.constraints,
        )
        self.time_plot.clear()
        self.thr_plot.clear()
        plot_curve(self.time_plot, xs, [p.flight_time_min for p in pts], "#378ADD")
        plot_curve(
            self.thr_plot,
            xs,
            [None if p.hover_throttle is None else 100 * p.hover_throttle for p in pts],
            "#7F77DD",
        )
        self.thr_plot.addItem(
            pg.InfiniteLine(
                pos=100 * s.constraints.max_hover_throttle,
                angle=0,
                pen=pg.mkPen("#D85A30", style=pg.QtCore.Qt.DashLine),
            )
        )
        for pw in (self.time_plot, self.thr_plot):
            pw.addItem(
                pg.InfiniteLine(pos=r.payload_kg, angle=90, pen=pg.mkPen("#1D9E75", width=2))
            )
            if rev.can_fly_empty and max_payload < x_max:
                pw.addItem(
                    pg.InfiniteLine(
                        pos=max_payload,
                        angle=90,
                        pen=pg.mkPen("#D85A30", style=pg.QtCore.Qt.DashLine),
                    )
                )
        self.thr_plot.setYRange(0, 105)
        self.time_plot.setXRange(0, x_max, padding=0)
        self.thr_plot.setXRange(0, x_max, padding=0)
