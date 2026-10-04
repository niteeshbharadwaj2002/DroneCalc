"""Main window: navigation, menus, status bar and the permanent 'predicted, unverified' banner."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dronecalc import __version__
from dronecalc.core import ProjectError
from dronecalc.ui.format import DISCLAIMER
from dronecalc.ui.screens.compare import CompareScreen
from dronecalc.ui.screens.components import ComponentsScreen
from dronecalc.ui.screens.database import DatabaseScreen
from dronecalc.ui.screens.mission import MissionScreen
from dronecalc.ui.screens.results import ResultsScreen
from dronecalc.ui.state import AppState

SCREENS = ["Mission", "Components", "Results", "Compare", "Database"]
PROJECT_FILTER = "DroneCalc project (*.dronecalc.json);;JSON (*.json)"

ABOUT_HTML = """
<h3>DroneCalc {version}</h3>
<p><b>All results are predicted and unverified.</b> They come from a preliminary-design physics
model run on approximate component data, and have not been validated against flight tests.</p>
<h4>Model</h4>
<ul>
<li>Hover: thrust per rotor T = m g / N; propeller T = Ct rho n^2 D^4, P = Cp rho n^3 D^5.</li>
<li>Motor: Kv / Kt / Rm model with no-load current; battery loaded voltage by iteration.</li>
<li>Flight time = capacity x depth of discharge x temperature factor x (1 - derate) / current.</li>
<li>Forward mode sizes the battery by iterating total mass, then matches real batteries.</li>
<li>Reverse mode finds the maximum payload by bisection against the hover limits.</li>
</ul>
<h4>Known limitations</h4>
<ul>
<li>Static propeller coefficients (no advance-ratio or inflow effects)</li>
<li>Constant ESC efficiency and avionics load; no motor thermal model</li>
<li>No coaxial interference penalty; hover only, no forward flight</li>
<li>Seed database entries are approximate and flagged unverified</li>
</ul>
"""


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, interactive: bool = False):
        super().__init__()
        self.state = state
        self.interactive = interactive  # show modal dialogs for errors (off in tests)
        self.errors: list[str] = []
        self.resize(1280, 820)

        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.addItems(SCREENS)
        self.stack = QStackedWidget()

        self.mission = MissionScreen(state)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.mission)
        self.components = ComponentsScreen(state)
        self.results = ResultsScreen(state)
        self.compare = CompareScreen(state)
        self.database = DatabaseScreen(state)
        self.screens: dict[str, QWidget] = {
            "Mission": scroll,
            "Components": self.components,
            "Results": self.results,
            "Compare": self.compare,
            "Database": self.database,
        }
        for name in SCREENS:
            self.stack.addWidget(self.screens[name])

        self.banner = QLabel(DISCLAIMER)
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setStyleSheet(
            "background: #FAEEDA; color: #633806; padding: 4px; font-weight: 600;"
        )
        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(body, 1)
        lay.addWidget(self.banner)
        self.setCentralWidget(central)

        self.status_label = QLabel("")
        self.busy_bar = QProgressBar()
        self.busy_bar.setMaximumWidth(160)
        self.busy_bar.hide()
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.busy_bar)

        self._menus()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.mission.runRequested.connect(self.run_forward)
        self.mission.reverseRequested.connect(self.run_reverse)
        self.results.openInComponents.connect(lambda: self.show_screen("Components", 0))
        self.results.exportRequested.connect(self.export_csv)
        self.components.openMission.connect(lambda: self.show_screen("Mission"))
        state.statusMessage.connect(self.status_label.setText)
        state.errorOccurred.connect(self._error)
        state.busyChanged.connect(self._busy)
        state.progress.connect(self._progress)
        state.projectChanged.connect(self._title)
        self._title()

    # ---- navigation ------------------------------------------------------------------------

    def show_screen(self, name: str, components_tab: int | None = None) -> None:
        self.nav.setCurrentRow(SCREENS.index(name))
        if name == "Components" and components_tab is not None:
            self.components.tabs.setCurrentIndex(components_tab)

    def current_screen(self) -> str:
        return SCREENS[self.stack.currentIndex()]

    def run_forward(self) -> None:
        if self.state.run_forward():
            self.show_screen("Results")

    def run_reverse(self) -> None:
        self.state.evaluate_reverse()
        if not self.state.reverse_ready():
            self.state.statusMessage.emit("Choose all four components first")
        self.show_screen("Components", 0)

    # ---- menus -----------------------------------------------------------------------------

    def _menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self.act_new = self._act(f, "&New project", self.new_project, QKeySequence.New)
        self.act_open = self._act(f, "&Open project...", self.open_project, QKeySequence.Open)
        self.act_save = self._act(f, "&Save project", self.save_project, QKeySequence.Save)
        self.act_save_as = self._act(
            f, "Save project &as...", self.save_project_as, QKeySequence.SaveAs
        )
        f.addSeparator()
        self.act_export = self._act(f, "&Export results as CSV...", self.export_csv, "Ctrl+E")
        f.addSeparator()
        self._act(f, "&Quit", self.close, QKeySequence.Quit)
        h = mb.addMenu("&Help")
        self._act(h, "&Assumptions and about", self.about, None)

    def _act(self, menu, text, slot, shortcut) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(shortcut)
        a.triggered.connect(lambda _checked=False: slot())
        menu.addAction(a)
        return a

    # ---- status ----------------------------------------------------------------------------

    def _title(self) -> None:
        s = self.state
        name = s.project_path.name if s.project_path else "Untitled"
        self.setWindowTitle(f"DroneCalc - {name}{' *' if s.dirty else ''}")

    def _busy(self, busy: bool) -> None:
        self.busy_bar.setVisible(busy)
        if busy:
            self.busy_bar.setRange(0, 0)

    def _progress(self, done: int, total: int) -> None:
        self.busy_bar.setRange(0, max(total, 1))
        self.busy_bar.setValue(done)

    def _error(self, message: str) -> None:
        self.errors.append(message)
        self.status_label.setText(f"Error: {message}")
        if self.interactive:
            QMessageBox.warning(self, "DroneCalc", message)

    # ---- project actions -------------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        if not (self.state.dirty and self.interactive):
            return True
        box = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes to the current project first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if box == QMessageBox.Save:
            return self.save_project()
        return box == QMessageBox.Discard

    def new_project(self) -> None:
        if self._confirm_discard():
            self.state.new_project()

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", PROJECT_FILTER)
        if path:
            self.open_project_path(path)

    def open_project_path(self, path: str | Path) -> bool:
        try:
            warnings = self.state.open_project_from(path)
        except ProjectError as exc:
            self.state.errorOccurred.emit(str(exc))
            return False
        for w in warnings:
            self.state.statusMessage.emit(w)
        return True

    def save_project(self) -> bool:
        if self.state.project_path is None:
            return self.save_project_as()
        return self.save_project_path(self.state.project_path)

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "project.dronecalc.json", PROJECT_FILTER
        )
        return bool(path) and self.save_project_path(path)

    def save_project_path(self, path: str | Path) -> bool:
        try:
            self.state.save_project_to(path)
        except OSError as exc:
            self.state.errorOccurred.emit(f"Cannot save project: {exc}")
            return False
        return True

    def export_csv(self) -> None:
        if not (self.state.sizing_result and self.state.sizing_result.ranked):
            self.state.errorOccurred.emit("There are no results to export; run a sizing first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "results.csv", "CSV (*.csv)")
        if path:
            self.export_csv_path(path)

    def export_csv_path(self, path: str | Path) -> bool:
        try:
            self.state.export_results_csv(path)
        except (OSError, ValueError) as exc:
            self.state.errorOccurred.emit(f"Cannot export: {exc}")
            return False
        return True

    def about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Assumptions and about")
        box.setTextFormat(Qt.RichText)
        box.setText(ABOUT_HTML.format(version=__version__))
        if self.interactive:
            box.exec()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._confirm_discard():
            self.state.cancel_run()
            self.state.wait_idle(5000)
            event.accept()
        else:
            event.ignore()
