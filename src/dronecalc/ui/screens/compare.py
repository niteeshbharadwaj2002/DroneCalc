"""Compare screen: 2 to 4 builds side by side in the current environment."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dronecalc.core import BuildResult, sweep_payload
from dronecalc.ui.format import DISCLAIMER
from dronecalc.ui.state import AppState
from dronecalc.ui.widgets import SERIES_COLORS, is_dark, make_plot, plot_curve

# (label, getter, format, better) where better is "high", "low" or None
Metric = tuple[str, Callable[[BuildResult], float], str, "str | None"]
METRICS: list[Metric] = [
    ("Flight time (min)", lambda r: r.flight_time_min, "{:.1f}", "high"),
    ("Total mass (g)", lambda r: r.total_mass_kg * 1000, "{:.0f}", "low"),
    ("Hover throttle (%)", lambda r: r.hover_throttle * 100, "{:.0f}", "low"),
    ("Hover power (W)", lambda r: r.hover_battery_power_w, "{:.0f}", "low"),
    ("Hover current (A)", lambda r: r.hover_battery_current_a, "{:.1f}", "low"),
    ("Thrust-to-weight", lambda r: r.thrust_to_weight, "{:.2f}", "high"),
    ("Hover efficiency (g/W)", lambda r: r.hover_efficiency_g_per_w, "{:.1f}", "high"),
    ("Propeller FM", lambda r: r.figure_of_merit, "{:.2f}", None),
    ("Battery capacity (mAh)", lambda r: r.build.battery.capacity_mah, "{:.0f}", None),
    ("Cost ($)", lambda r: r.cost_usd, "{:.0f}", "low"),
]


class CompareScreen(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        self.plot = make_plot("Flight time vs payload", "payload (kg)", "minutes", 230)
        self.plot.addLegend(labelTextColor="#D8D8D8" if is_dark() else "#333333")
        btns = QHBoxLayout()
        self.remove_btn = QPushButton("Remove selected build")
        self.clear_btn = QPushButton("Clear all")
        btns.addWidget(self.remove_btn)
        btns.addWidget(self.clear_btn)
        btns.addStretch(1)
        root.addWidget(self.table, 2)
        root.addLayout(btns)
        root.addWidget(self.plot, 3)
        note = QLabel(DISCLAIMER)
        note.setStyleSheet("color: palette(mid);")
        root.addWidget(note)

        self.remove_btn.clicked.connect(self._remove)
        self.clear_btn.clicked.connect(state.clear_compare)
        for sig in (
            state.compareChanged,
            state.missionChanged,
            state.settingsChanged,
            state.databaseChanged,
        ):
            sig.connect(self.refresh)
        self.refresh()

    def _remove(self) -> None:
        cols = self.table.selectionModel().selectedColumns()
        if cols:
            self.state.remove_from_compare(cols[0].column())

    def refresh(self) -> None:
        s = self.state
        rows = s.compare_results()
        m = s.mission
        n = len(rows)
        self.info.setText(
            f"{n} build(s) compared at payload {m.payload_kg:g} kg, {m.altitude_m:g} m, "
            f"ISA {m.temp_offset_c:+g} K. Best value per row is highlighted. Add builds from "
            "the Results or Components screens (up to 4)."
            if n
            else "No builds to compare yet. Add builds from the Results or Components screens."
        )
        self.table.clear()
        self.table.setColumnCount(n)
        self.table.setRowCount(len(METRICS))
        self.table.setVerticalHeaderLabels([m_[0] for m_ in METRICS])
        self.table.setHorizontalHeaderLabels(
            [f"{b.motor.id}\n{b.prop.id}\n{b.battery.id}" for b, _r, _e in rows]
        )
        self.table.horizontalHeader().setMinimumHeight(54)
        green = QColor("#1D5E3A" if is_dark() else "#C0DD97")
        for c, (_b, r, err) in enumerate(rows):
            for row, (_label, getter, fmt, _better) in enumerate(METRICS):
                text = fmt.format(getter(r)) if r else (err or "n/a")
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, c, it)
        for row, (_label, getter, _fmt, better) in enumerate(METRICS):
            vals = [(c, getter(r)) for c, (_b, r, _e) in enumerate(rows) if r]
            if better and len(vals) >= 2:
                pick = max if better == "high" else min
                best = pick(v for _c, v in vals)
                for c, v in vals:
                    if abs(v - best) < 1e-9:
                        self.table.item(row, c).setBackground(QBrush(green))
        self.remove_btn.setEnabled(n > 0)
        self.clear_btn.setEnabled(n > 0)
        self._plot(rows)

    def _plot(self, rows) -> None:
        s = self.state
        m = s.mission
        self.plot.clear()
        built = [(b, r) for b, r, _e in rows if r]
        if not built:
            return
        x_max = max(1.0, 2.0 * m.payload_kg, 1.0)
        xs = [x_max * i / 24 for i in range(25)]
        for i, (b, _r) in enumerate(built):
            pts = sweep_payload(
                b,
                xs,
                m.altitude_m,
                m.temp_offset_c,
                m.payload_power_w,
                s.assumptions,
                s.constraints,
            )
            plot_curve(
                self.plot,
                xs,
                [p.flight_time_min for p in pts],
                SERIES_COLORS[i % len(SERIES_COLORS)],
                name=f"{b.motor.id} + {b.prop.id}",
            )
