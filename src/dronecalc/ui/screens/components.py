"""Components screen: pick a build for reverse sizing, or limit the forward search."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dronecalc.ui.format import DISCLAIMER, limiting_text
from dronecalc.ui.screens.detail import BuildDetail
from dronecalc.ui.state import KINDS, SINGULAR, AppState

TITLES = {"motors": "Motors", "props": "Propellers", "batteries": "Batteries", "escs": "ESCs"}


def _label(kind: str, item) -> str:
    if kind == "motors":
        return f"{item.name}  ({item.id})"
    if kind == "props":
        return f"{item.name}  ({item.diameter_in:g}x{item.pitch_in:g})"
    if kind == "batteries":
        return f"{item.name}  ({item.cells}S {item.capacity_mah:.0f} mAh)"
    return f"{item.name}  ({item.max_current_a:g} A)"


class ComponentsScreen(QWidget):
    openMission = Signal()

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        tabs = QTabWidget()
        tabs.addTab(self._build_reverse_tab(), "Pick a build (reverse mode)")
        tabs.addTab(self._build_filter_tab(), "Limit the search (forward mode)")
        self.tabs = tabs
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        note = QLabel(DISCLAIMER)
        note.setStyleSheet("color: palette(mid);")
        root.addWidget(note)

        state.databaseChanged.connect(self.reload_lists)
        state.reverseSelectionChanged.connect(self._sync_combos)
        state.reverseResultChanged.connect(self._show_reverse)
        state.missionChanged.connect(self._env_label)
        state.filtersChanged.connect(self._sync_filters)
        self.reload_lists()
        self._env_label()

    # ---- reverse tab -----------------------------------------------------------------------

    def _build_reverse_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Components")
        grid = QGridLayout(box)
        self.combos: dict[str, QComboBox] = {}
        for row, kind in enumerate(KINDS):
            single = SINGULAR[kind]
            cb = QComboBox()
            cb.setMinimumWidth(300)
            cb.currentIndexChanged.connect(lambda _i, k=single, c=cb: self._picked(k, c))
            self.combos[single] = cb
            grid.addWidget(QLabel(TITLES[kind][:-1] if kind != "batteries" else "Battery"), row, 0)
            grid.addWidget(cb, row, 1)
        ll.addWidget(box)
        self.env_label = QLabel("")
        self.env_label.setWordWrap(True)
        self.env_label.setStyleSheet("color: palette(mid);")
        ll.addWidget(self.env_label)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 600;")
        ll.addWidget(self.status)
        self.add_btn = QPushButton("Add to comparison")
        self.mission_btn = QPushButton("Change payload or environment...")
        ll.addWidget(self.add_btn)
        ll.addWidget(self.mission_btn)
        ll.addStretch(1)
        self.add_btn.clicked.connect(self._add)
        self.mission_btn.clicked.connect(self.openMission)
        self.detail = BuildDetail(self.state)
        lay.addWidget(left, 2)
        lay.addWidget(self.detail, 3)
        return w

    def _picked(self, single: str, cb: QComboBox) -> None:
        self.state.set_reverse_component(single, cb.currentData())

    def _sync_combos(self) -> None:
        for single, cb in self.combos.items():
            want = self.state.reverse_ids[single]
            cb.blockSignals(True)
            cb.setCurrentIndex(cb.findData(want))
            cb.blockSignals(False)

    def _env_label(self) -> None:
        m = self.state.mission
        self.env_label.setText(
            f"Evaluated at payload {m.payload_kg:g} kg, {m.altitude_m:g} m altitude, "
            f"ISA {m.temp_offset_c:+g} K, {m.n_rotors} rotors (set on the Mission screen)."
        )

    def _show_reverse(self) -> None:
        s = self.state
        rev, err = s.reverse_result, s.reverse_error
        if not s.reverse_ready():
            self.status.setText("Choose a motor, propeller, battery and ESC.")
            self.detail.show_result(None)
            self.add_btn.setEnabled(False)
            return
        self.add_btn.setEnabled(True)
        if rev is None:
            self.status.setText(f"This build cannot be evaluated: {err}")
            self.detail.show_result(None)
            return
        if rev.can_fly_empty:
            extra = (
                f", flight time there {rev.flight_time_at_max_payload_min:.1f} min"
                if rev.flight_time_at_max_payload_min is not None
                else ""
            )
            self.status.setText(
                f"Maximum payload {rev.max_payload_kg:.2f} kg "
                f"(limited by {limiting_text(rev.limiting_factor)}{extra})"
            )
        else:
            self.status.setText(
                f"Fails its limits even empty ({limiting_text(rev.limiting_factor)})."
            )
        self.detail.show_result(rev.result)

    def _add(self) -> None:
        b = self.state.reverse_build()
        if b:
            self.state.add_to_compare(b)

    # ---- filter tab ------------------------------------------------------------------------

    def _build_filter_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(
            "Forward sizing only considers ticked components. Leave everything ticked to search "
            "the whole database."
        )
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        self.lists: dict[str, QListWidget] = {}
        self.counts: dict[str, QLabel] = {}
        for kind in KINDS:
            col = QVBoxLayout()
            title = QLabel(TITLES[kind])
            title.setStyleSheet("font-weight: 600;")
            lw = QListWidget()
            lw.itemChanged.connect(lambda _it, k=kind: self._filter_edited(k))
            count = QLabel("")
            btns = QHBoxLayout()
            all_b, none_b = QPushButton("All"), QPushButton("None")
            all_b.clicked.connect(lambda _c=False, k=kind: self._set_all(k, True))
            none_b.clicked.connect(lambda _c=False, k=kind: self._set_all(k, False))
            btns.addWidget(all_b)
            btns.addWidget(none_b)
            col.addWidget(title)
            col.addWidget(lw, 1)
            col.addWidget(count)
            col.addLayout(btns)
            row.addLayout(col)
            self.lists[kind] = lw
            self.counts[kind] = count
        lay.addLayout(row, 1)
        return w

    def reload_lists(self) -> None:
        db = self.state.db
        for kind in KINDS:
            single = SINGULAR[kind]
            cb = self.combos[single]
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("(choose)", None)
            lw = self.lists[kind]
            lw.blockSignals(True)
            lw.clear()
            for item in getattr(db, kind).values():
                text = _label(kind, item) + ("" if item.verified else "  [unverified]")
                cb.addItem(text, item.id)
                li = QListWidgetItem(text)
                li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                li.setData(Qt.UserRole, item.id)
                li.setCheckState(Qt.Checked)
                lw.addItem(li)
            cb.blockSignals(False)
            lw.blockSignals(False)
        self._sync_combos()
        self._sync_filters()
        self._show_reverse()

    def _checked_ids(self, kind: str) -> set[str]:
        lw = self.lists[kind]
        return {
            lw.item(i).data(Qt.UserRole)
            for i in range(lw.count())
            if lw.item(i).checkState() == Qt.Checked
        }

    def _filter_edited(self, kind: str) -> None:
        self.state.set_allow(kind, self._checked_ids(kind))

    def _set_all(self, kind: str, on: bool) -> None:
        lw = self.lists[kind]
        lw.blockSignals(True)
        for i in range(lw.count()):
            lw.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        lw.blockSignals(False)
        self.state.set_allow(kind, self._checked_ids(kind))

    def _sync_filters(self) -> None:
        for kind in KINDS:
            allowed = self.state.allow[kind]
            lw = self.lists[kind]
            lw.blockSignals(True)
            for i in range(lw.count()):
                it = lw.item(i)
                on = allowed is None or it.data(Qt.UserRole) in allowed
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            lw.blockSignals(False)
            n_on = len(self._checked_ids(kind))
            self.counts[kind].setText(f"{n_on} of {lw.count()} selected")
