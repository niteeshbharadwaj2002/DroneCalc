"""Database Manager: browse seed and custom components, add, clone, edit and delete custom ones."""

from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dronecalc.core import DatabaseError
from dronecalc.ui.state import KINDS, AppState

# field name -> type tag: str, float, int, opt (optional float), bool, or a tuple of choices
SPECS: dict[str, dict[str, object]] = {
    "motors": {
        "id": "str", "name": "str", "manufacturer": "str", "kv_rpm_per_v": "float",
        "resistance_ohm": "float", "no_load_current_a": "float", "mass_g": "float",
        "max_current_a": "float", "max_power_w": "opt", "min_cells": "int", "max_cells": "int",
        "prop_min_in": "float", "prop_max_in": "float", "price_usd": "float",
        "verified": "bool", "notes": "str",
    },
    "props": {
        "id": "str", "name": "str", "diameter_in": "float", "pitch_in": "float", "ct": "float",
        "cp": "float", "mass_g": "float", "blades": "int", "price_usd": "float",
        "verified": "bool", "notes": "str",
    },
    "batteries": {
        "id": "str", "name": "str", "chemistry": ("lipo", "liion"), "cells": "int",
        "capacity_mah": "float", "mass_g": "float", "c_rate_cont": "float", "c_rate_burst": "opt",
        "internal_resistance_mohm": "opt", "nominal_cell_v": "opt", "price_usd": "float",
        "verified": "bool", "notes": "str",
    },
    "escs": {
        "id": "str", "name": "str", "max_current_a": "float", "min_cells": "int",
        "max_cells": "int", "mass_g": "float", "efficiency": "opt", "price_usd": "float",
        "verified": "bool", "notes": "str",
    },
}  # fmt: skip

TITLES = {"motors": "Motors", "props": "Propellers", "batteries": "Batteries", "escs": "ESCs"}
HELP = {
    "kv_rpm_per_v": "Motor speed constant, RPM per volt",
    "resistance_ohm": "Phase-to-phase resistance, ohm",
    "ct": "Thrust coefficient: T = Ct rho n^2 D^4",
    "cp": "Power coefficient: P = Cp rho n^3 D^5",
    "c_rate_cont": "Continuous discharge rating, C",
    "c_rate_burst": "Burst rating, C (blank = 2x continuous)",
    "internal_resistance_mohm": "Whole-pack resistance, mOhm (blank = estimated)",
    "nominal_cell_v": "Volts per cell (blank = chemistry default)",
}


class ComponentEditor(QWidget):
    """Form for one component kind, generated from SPECS."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.form = QFormLayout(self)
        self.widgets: dict[str, QWidget] = {}
        for name, spec in SPECS[kind].items():
            if spec == "bool":
                w: QWidget = QCheckBox("verified against a datasheet or test")
            elif isinstance(spec, tuple):
                w = QComboBox()
                w.addItems(list(spec))
            else:
                w = QLineEdit()
                if spec == "opt":
                    w.setPlaceholderText("(optional)")
            w.setToolTip(HELP.get(name, name))
            self.widgets[name] = w
            self.form.addRow(name, w)

    def clear(self) -> None:
        for name in SPECS[self.kind]:
            w = self.widgets[name]
            if isinstance(w, QCheckBox):
                w.setChecked(False)
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(0)
            else:
                w.setText("")
        self.widgets["id"].setReadOnly(False)

    def load(self, item, clone: bool = False) -> None:
        for f in fields(item):
            w = self.widgets.get(f.name)
            value = getattr(item, f.name)
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findText(str(value))))
            else:
                w.setText("" if value is None else str(value))
        if clone:
            self.widgets["id"].setText(item.id + "-copy")
            self.widgets["name"].setText(item.name + " (copy)")
            self.widgets["verified"].setChecked(False)
        self.widgets["id"].setReadOnly(not clone)

    def entry(self) -> dict[str, object]:
        """Parse the form into a dict for ``Database.add_custom``; raises ``ValueError``."""
        out: dict[str, object] = {}
        for name, spec in SPECS[self.kind].items():
            w = self.widgets[name]
            if isinstance(w, QCheckBox):
                out[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[name] = w.currentText()
            else:
                text = w.text().strip()
                if spec == "str":
                    if text or name in ("id", "name"):
                        out[name] = text
                elif text == "":
                    if spec != "opt":
                        raise ValueError(f"{name} is required")
                elif spec == "int":
                    try:
                        out[name] = int(text)
                    except ValueError:
                        raise ValueError(f"{name} must be a whole number") from None
                else:
                    try:
                        out[name] = float(text)
                    except ValueError:
                        raise ValueError(f"{name} must be a number") from None
        if not out.get("id"):
            raise ValueError("id is required")
        return out


class DatabaseScreen(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        self.editors: dict[str, ComponentEditor] = {}
        self.msg: dict[str, QLabel] = {}
        self._select_after: dict[str, str] = {}
        self.buttons: dict[str, tuple[QPushButton, ...]] = {}
        for kind in KINDS:
            self.tabs.addTab(self._make_tab(kind), TITLES[kind])
        self.warn_box = QGroupBox("Database checks")
        wl = QVBoxLayout(self.warn_box)
        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        wl.addWidget(self.warn_label)
        root = QVBoxLayout(self)
        root.addWidget(self.tabs, 1)
        root.addWidget(self.warn_box)
        state.databaseChanged.connect(self.refresh)
        self.refresh()

    # ---- construction ----------------------------------------------------------------------

    def _make_tab(self, kind: str) -> QWidget:
        names = list(SPECS[kind])
        extra = ["FM"] if kind == "props" else []
        table = QTableWidget(0, 1 + len(names) + len(extra))
        table.setHorizontalHeaderLabels(["source"] + names + extra)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().hide()
        table.itemSelectionChanged.connect(lambda k=kind: self._selected(k))
        self.tables[kind] = table

        editor = ComponentEditor(kind)
        self.editors[kind] = editor
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(editor)

        new_b, clone_b = QPushButton("New"), QPushButton("Clone selected")
        save_b, del_b = QPushButton("Save as custom entry"), QPushButton("Delete custom entry")
        new_b.clicked.connect(lambda _c=False, k=kind: self._new(k))
        clone_b.clicked.connect(lambda _c=False, k=kind: self._clone(k))
        save_b.clicked.connect(lambda _c=False, k=kind: self._save(k))
        del_b.clicked.connect(lambda _c=False, k=kind: self._delete(k))
        note = QLabel(
            "Seed entries are read-only; saving a seed entry creates a custom override with "
            "the same id. Datasheet values are best: mark an entry verified only if it is."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        msg = QLabel("")
        msg.setWordWrap(True)
        self.msg[kind] = msg
        row = QHBoxLayout()
        for b in (new_b, clone_b, save_b, del_b):
            row.addWidget(b)
        self.buttons[kind] = (new_b, clone_b, save_b, del_b)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(scroll, 1)
        rl.addLayout(row)
        rl.addWidget(note)
        rl.addWidget(msg)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(table)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

    # ---- table -----------------------------------------------------------------------------

    def refresh(self) -> None:
        db = self.state.db
        for kind in KINDS:
            table = self.tables[kind]
            names = list(SPECS[kind])
            keep = self._select_after.pop(kind, None) or self.selected_id(kind)
            table.setSortingEnabled(False)
            table.setRowCount(0)
            for i, item in enumerate(getattr(db, kind).values()):
                table.insertRow(i)
                src = "custom" if db.is_custom(kind, item.id) else "seed"
                cells = [src] + [self._cell(getattr(item, n)) for n in names]
                if kind == "props":
                    cells.append(f"{item.figure_of_merit:.2f}")
                for c, text in enumerate(cells):
                    table.setItem(i, c, QTableWidgetItem(text))
                if src == "custom":
                    for c in range(table.columnCount()):
                        table.item(i, c).setForeground(Qt.darkCyan)
            table.setSortingEnabled(True)
            table.resizeColumnsToContents()
            if keep:
                self._reselect(kind, keep)
        warnings = db.check(self.state.assumptions.fm_range)
        self.warn_label.setText("<br>".join(warnings) if warnings else "No warnings.")

    @staticmethod
    def _cell(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    def selected_id(self, kind: str) -> str | None:
        table = self.tables[kind]
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        col = 1 + list(SPECS[kind]).index("id")
        return table.item(rows[0].row(), col).text()

    def _selected(self, kind: str) -> None:
        eid = self.selected_id(kind)
        if eid is None:
            return
        self.editors[kind].load(getattr(self.state.db, kind)[eid])
        custom = self.state.db.is_custom(kind, eid)
        new_b, clone_b, save_b, del_b = self.buttons[kind]
        del_b.setEnabled(custom)
        self.msg[kind].setText("Custom entry." if custom else "Seed entry (read-only id).")

    # ---- actions ---------------------------------------------------------------------------

    def _new(self, kind: str) -> None:
        self.tables[kind].clearSelection()
        self.editors[kind].clear()
        self.msg[kind].setText("Fill in the form and save.")

    def _clone(self, kind: str) -> None:
        eid = self.selected_id(kind)
        if eid is None:
            self.msg[kind].setText("Select an entry to clone first.")
            return
        self.editors[kind].load(getattr(self.state.db, kind)[eid], clone=True)
        self.msg[kind].setText("Cloned. Change the id and values, then save.")

    def save_entry(self, kind: str) -> tuple[bool, str]:
        """Save the editor's content; returns (ok, message). Used by the button and by tests."""
        try:
            entry = self.editors[kind].entry()
            self._select_after[kind] = str(entry["id"])
            self.state.save_component(kind, entry)
        except (ValueError, DatabaseError) as exc:
            self._select_after.pop(kind, None)
            return False, str(exc)
        return True, f"Saved {entry['id']}."

    def _save(self, kind: str) -> None:
        ok, text = self.save_entry(kind)
        self.msg[kind].setText(text)
        self.msg[kind].setStyleSheet("" if ok else "color: #A32D2D; font-weight: 600;")

    def _reselect(self, kind: str, entry_id: str) -> None:
        table = self.tables[kind]
        col = 1 + list(SPECS[kind]).index("id")
        for r in range(table.rowCount()):
            if table.item(r, col).text() == entry_id:
                table.selectRow(r)
                return

    def _delete(self, kind: str) -> None:
        eid = self.selected_id(kind)
        if eid is None or not self.state.db.is_custom(kind, eid):
            self.msg[kind].setText("Select a custom entry to delete.")
            return
        if QMessageBox.question(self, "Delete", f"Delete custom entry {eid!r}?") != QMessageBox.Yes:
            return
        self.delete_entry(kind, eid)

    def delete_entry(self, kind: str, eid: str) -> None:
        try:
            self.state.delete_component(kind, eid)
        except DatabaseError as exc:
            self.msg[kind].setText(str(exc))
            return
        self.editors[kind].clear()
        self.msg[kind].setText(f"Deleted {eid}.")
