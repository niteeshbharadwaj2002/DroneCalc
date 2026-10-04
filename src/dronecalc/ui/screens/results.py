"""Results screen: ranked builds, details, rejection reasons, CSV export."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dronecalc.core import BuildResult
from dronecalc.ui.format import DISCLAIMER, rejection_text
from dronecalc.ui.screens.detail import BuildDetail
from dronecalc.ui.state import AppState

COLUMNS = [
    "#",
    "Motor",
    "Propeller",
    "Battery",
    "ESC",
    "Mass g",
    "Hover %",
    "Power W",
    "Minutes",
    "T/W",
    "Cost $",
]


class NumItem(QTableWidgetItem):
    """Table item that sorts by a number but shows formatted text."""

    def __init__(self, value: float, text: str):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other) -> bool:
        if isinstance(other, NumItem):
            return self.value < other.value
        return super().__lt__(other)


class ResultsScreen(QWidget):
    openInComponents = Signal()
    exportRequested = Signal()

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.stale = QLabel("Inputs changed since this run. Run again to refresh.")
        self.stale.setStyleSheet("color: #BA7517; font-weight: 600;")
        self.stale.hide()
        self.progress = QProgressBar()
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        prow = QHBoxLayout()
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.cancel_btn)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.rej_group = QGroupBox("Why other configurations were rejected")
        rl = QVBoxLayout(self.rej_group)
        self.rej_table = QTableWidget(0, 2)
        self.rej_table.setHorizontalHeaderLabels(["Reason", "Count"])
        self.rej_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rej_table.verticalHeader().hide()
        self.rej_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rej_table.setMaximumHeight(170)
        rl.addWidget(self.rej_table)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.rej_group)

        self.detail = BuildDetail(state)
        self.add_btn = QPushButton("Add to comparison")
        self.rev_btn = QPushButton("Evaluate in reverse mode")
        self.csv_btn = QPushButton("Export CSV...")
        buttons = QHBoxLayout()
        for b in (self.add_btn, self.rev_btn, self.csv_btn):
            buttons.addWidget(b)
        right = QWidget()
        rl2 = QVBoxLayout(right)
        rl2.setContentsMargins(0, 0, 0, 0)
        rl2.addWidget(self.detail, 1)
        rl2.addLayout(buttons)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([680, 660])

        note = QLabel(DISCLAIMER)
        note.setStyleSheet("color: palette(mid);")
        root.addWidget(self.summary)
        root.addWidget(self.stale)
        root.addLayout(prow)
        root.addWidget(split, 1)
        root.addWidget(note)

        self.table.itemSelectionChanged.connect(self._selected)
        self.add_btn.clicked.connect(self._add)
        self.rev_btn.clicked.connect(self._to_reverse)
        self.csv_btn.clicked.connect(self.exportRequested)
        self.cancel_btn.clicked.connect(state.cancel_run)
        state.resultsChanged.connect(self.refresh)
        state.busyChanged.connect(self._busy)
        state.progress.connect(self._progress)
        for sig in (state.missionChanged, state.settingsChanged, state.filtersChanged):
            sig.connect(self._update_stale)
        self.results: list[BuildResult] = []
        self.refresh()

    # ---- state -> widgets ------------------------------------------------------------------

    def _busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
            self.summary.setText("Running forward sizing...")

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def _update_stale(self) -> None:
        self.stale.setVisible(self.state.results_stale)

    def selected_result(self) -> BuildResult | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        idx = item.data(Qt.UserRole) if item else None
        return self.results[idx] if idx is not None else None

    def refresh(self) -> None:
        s = self.state
        res = s.sizing_result
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.results = list(res.ranked) if res else []
        self.rej_table.setRowCount(0)
        self._update_stale()
        if res is None:
            msg = s.sizing_error or "No results yet. Set up a mission and run forward sizing."
            self.summary.setText(msg)
            self.rej_group.hide()
            self.detail.show_result(None)
            self.table.setSortingEnabled(True)
            return
        atm = res.atmosphere
        self.summary.setText(
            f"Mission {res.mission.target_flight_time_min:g} min, {res.mission.payload_kg:g} kg "
            f"payload, {res.mission.n_rotors} rotors | density {atm.density:.3f} kg/m3 "
            f"(density altitude {round(atm.density_altitude_m)} m) | {res.n_candidates} candidate "
            f"configurations, {res.n_feasible} feasible builds, showing {len(res.ranked)}"
        )
        for i, r in enumerate(res.ranked):
            b = r.build
            cells = [
                NumItem(i + 1, str(i + 1)),
                QTableWidgetItem(b.motor.id),
                QTableWidgetItem(b.prop.id),
                QTableWidgetItem(b.battery.id),
                QTableWidgetItem(b.esc.id),
                NumItem(r.total_mass_kg * 1000, f"{r.total_mass_kg * 1000:.0f}"),
                NumItem(r.hover_throttle * 100, f"{r.hover_throttle:.0%}"),
                NumItem(r.hover_battery_power_w, f"{r.hover_battery_power_w:.0f}"),
                NumItem(r.flight_time_min, f"{r.flight_time_min:.1f}"),
                NumItem(r.thrust_to_weight, f"{r.thrust_to_weight:.2f}"),
                NumItem(r.cost_usd, f"{r.cost_usd:.0f}"),
            ]
            self.table.insertRow(i)
            for c, item in enumerate(cells):
                self.table.setItem(i, c, item)
            self.table.item(i, 0).setData(Qt.UserRole, i)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.AscendingOrder)

        rej = sorted(res.rejections.items(), key=lambda kv: -kv[1])
        self.rej_group.setVisible(bool(rej))
        for i, (code, n) in enumerate(rej):
            self.rej_table.insertRow(i)
            self.rej_table.setItem(i, 0, QTableWidgetItem(rejection_text(code)))
            it = NumItem(n, str(n))
            self.rej_table.setItem(i, 1, it)
        if not res.ranked:
            self.summary.setText(
                self.summary.text() + " | No feasible build found: see the reasons below."
            )
            self.detail.show_result(None)
        elif self.table.rowCount():
            self.table.selectRow(0)
        self._selected()

    def _selected(self) -> None:
        r = self.selected_result()
        self.detail.show_result(r)
        for b in (self.add_btn, self.rev_btn):
            b.setEnabled(r is not None)
        self.csv_btn.setEnabled(bool(self.results))

    def _add(self) -> None:
        r = self.selected_result()
        if r:
            self.state.add_to_compare(r.build)

    def _to_reverse(self) -> None:
        r = self.selected_result()
        if r:
            self.state.set_reverse_build(r.build)
            self.openInComponents.emit()
