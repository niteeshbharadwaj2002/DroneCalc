"""Shared application state for the desktop UI.

``AppState`` owns the database, the user's inputs and the latest results, and exposes Qt signals so
screens stay decoupled from each other. All physics goes through ``dronecalc.core``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from dronecalc.core import (
    SCORERS,
    Assumptions,
    Build,
    BuildResult,
    Constraints,
    Database,
    DatabaseError,
    Mission,
    Project,
    ProjectError,
    ReverseResult,
    SizingCancelled,
    SizingResult,
    SolveError,
    assess_build,
    atmosphere,
    build_from_dict,
    build_to_dict,
    estimate_frame_mass_kg,
    load_project,
    save_project,
    size_forward,
    size_reverse,
    write_results_csv,
)

KINDS = ("motors", "props", "batteries", "escs")
SINGULAR = {"motors": "motor", "props": "prop", "batteries": "battery", "escs": "esc"}
MAX_COMPARE = 4

DEFAULT_MISSION = Mission(target_flight_time_min=20.0, payload_kg=0.5)


class _TaskSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class _Task(QRunnable):
    """Runs ``fn(progress, is_cancelled)`` on the thread pool and reports back through signals."""

    def __init__(self, fn: Callable[[Callable[[int, int], None], Callable[[], bool]], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit, lambda: self._cancel)
        except SizingCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.finished.emit(result)


class AppState(QObject):
    missionChanged = Signal()
    settingsChanged = Signal()  # assumptions, constraints, ranking, mode
    filtersChanged = Signal()
    reverseSelectionChanged = Signal()
    reverseResultChanged = Signal()
    resultsChanged = Signal()
    compareChanged = Signal()
    databaseChanged = Signal()
    projectChanged = Signal()  # file name / dirty flag
    busyChanged = Signal(bool)
    progress = Signal(int, int)
    errorOccurred = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, db: Database | None = None, custom_dir: Path | None = None):
        super().__init__()
        self.custom_dir = Path(custom_dir) if custom_dir is not None else None
        self.db = db or Database.load(custom_dir=self.custom_dir)
        self._reset_inputs()
        self.sizing_result: SizingResult | None = None
        self.sizing_error: str | None = None
        self._results_version = -1
        self.reverse_result: ReverseResult | None = None
        self.reverse_error: str | None = None
        self.busy = False
        self._task: _Task | None = None
        self.project_path: Path | None = None
        self.dirty = False

    # ---- inputs ----------------------------------------------------------------------------

    def _reset_inputs(self) -> None:
        self.mission = DEFAULT_MISSION
        self.assumptions = Assumptions()
        self.constraints = Constraints()
        self.mode = "forward"
        self.scorer = "flight_time"
        self.top_n = 10
        self.allow: dict[str, set[str] | None] = {k: None for k in KINDS}
        self.reverse_ids: dict[str, str | None] = {SINGULAR[k]: None for k in KINDS}
        self.compare_builds: list[Build] = []
        self._inputs_version = 0

    def _touch(self, affects_results: bool = False) -> None:
        """Mark the project dirty; ``affects_results`` also marks forward results as stale."""
        if affects_results:
            self._inputs_version += 1
        self.dirty = True
        self.projectChanged.emit()

    @property
    def results_stale(self) -> bool:
        return self.sizing_result is not None and self._results_version != self._inputs_version

    def update_mission(self, **changes: Any) -> bool:
        """Apply field changes to the mission. Returns False (and reports) when invalid."""
        try:
            new = replace(self.mission, **changes)
        except (ValueError, TypeError) as exc:
            self.errorOccurred.emit(str(exc))
            return False
        if new == self.mission:
            return True
        self.mission = new
        self._touch(True)
        self.missionChanged.emit()
        self.evaluate_reverse()
        return True

    def update_assumptions(self, **changes: Any) -> bool:
        try:
            new = replace(self.assumptions, **changes)
        except (ValueError, TypeError) as exc:
            self.errorOccurred.emit(str(exc))
            return False
        if new != self.assumptions:
            self.assumptions = new
            self._touch(True)
            self.settingsChanged.emit()
            self.evaluate_reverse()
        return True

    def update_constraints(self, **changes: Any) -> bool:
        try:
            new = replace(self.constraints, **changes)
        except (ValueError, TypeError) as exc:
            self.errorOccurred.emit(str(exc))
            return False
        if new != self.constraints:
            self.constraints = new
            self._touch(True)
            self.settingsChanged.emit()
            self.evaluate_reverse()
        return True

    def reset_model_settings(self) -> None:
        self.assumptions = Assumptions()
        self.constraints = Constraints()
        self._touch(True)
        self.settingsChanged.emit()
        self.evaluate_reverse()

    def set_mode(self, mode: str) -> None:
        if mode not in ("forward", "reverse"):
            raise ValueError(f"unknown mode {mode!r}")
        if mode != self.mode:
            self.mode = mode
            self._touch()
            self.settingsChanged.emit()

    def set_ranking(self, scorer: str | None = None, top_n: int | None = None) -> None:
        if scorer is not None:
            if scorer not in SCORERS:
                raise ValueError(f"unknown scorer {scorer!r}")
            self.scorer = scorer
        if top_n is not None:
            self.top_n = max(1, int(top_n))
        self._touch(True)
        self.settingsChanged.emit()

    def set_allow(self, kind: str, ids: set[str] | None) -> None:
        """Restrict forward sizing to ``ids`` of ``kind`` (``None`` = every component)."""
        if ids is not None and set(ids) >= set(getattr(self.db, kind)):
            ids = None
        self.allow[kind] = None if ids is None else set(ids)
        self._touch(True)
        self.filtersChanged.emit()

    def allow_for_core(self) -> dict[str, set[str] | None]:
        return {k: (None if v is None else set(v)) for k, v in self.allow.items()}

    # ---- reverse mode ----------------------------------------------------------------------

    def set_reverse_component(self, kind: str, entry_id: str | None) -> None:
        """``kind`` is singular: motor, prop, battery or esc."""
        if kind not in self.reverse_ids:
            raise ValueError(f"unknown component kind {kind!r}")
        if self.reverse_ids[kind] == entry_id:
            return
        self.reverse_ids[kind] = entry_id
        self._touch()
        self.reverseSelectionChanged.emit()
        self.evaluate_reverse()

    def set_reverse_build(self, build: Build | None) -> None:
        if build is None:
            ids: dict[str, str | None] = {k: None for k in self.reverse_ids}
        else:
            ids = {
                "motor": build.motor.id,
                "prop": build.prop.id,
                "battery": build.battery.id,
                "esc": build.esc.id,
            }
        self.reverse_ids = ids
        self._touch()
        self.reverseSelectionChanged.emit()
        self.evaluate_reverse()

    def reverse_ready(self) -> bool:
        return all(self.reverse_ids.values())

    def reverse_build(self) -> Build | None:
        if not self.reverse_ready():
            return None
        try:
            motor = self.db.get("motors", self.reverse_ids["motor"])
            prop = self.db.get("props", self.reverse_ids["prop"])
            battery = self.db.get("batteries", self.reverse_ids["battery"])
            esc = self.db.get("escs", self.reverse_ids["esc"])
        except KeyError:
            return None
        frame_kg = estimate_frame_mass_kg(
            prop.diameter_in,
            self.mission.n_rotors,
            self.assumptions.prop_clearance,
            self.mission.frame_mass_override_g,
        )
        return Build(motor, prop, battery, esc, self.mission.n_rotors, frame_kg)

    def evaluate_reverse(self) -> None:
        """Inline reverse sizing for the selected components (a few milliseconds)."""
        build = self.reverse_build()
        self.reverse_result, self.reverse_error = None, None
        if build is not None:
            try:
                self.reverse_result = size_reverse(
                    build,
                    self.mission.payload_kg,
                    self.mission.altitude_m,
                    self.mission.temp_offset_c,
                    self.mission.payload_power_w,
                    self.assumptions,
                    self.constraints,
                )
            except (SolveError, ValueError) as exc:
                self.reverse_error = str(exc) or "build cannot be evaluated"
        self.reverseResultChanged.emit()

    # ---- forward sizing (background) -------------------------------------------------------

    def run_forward(self) -> bool:
        """Start forward sizing in a worker thread. Returns False if one is already running."""
        if self.busy:
            return False
        mission, assumptions, constraints = self.mission, self.assumptions, self.constraints
        scorer, top_n, allow = self.scorer, self.top_n, self.allow_for_core()
        db = self.db

        def job(progress, cancelled):
            return size_forward(
                mission,
                db,
                assumptions,
                constraints,
                scorer,
                top_n=top_n,
                allow=allow,
                progress=progress,
                cancel=cancelled,
            )

        version = self._inputs_version

        def done(result: SizingResult) -> None:
            self.sizing_result, self.sizing_error = result, None
            self._results_version = version
            self._finish_task()
            self.resultsChanged.emit()
            self.statusMessage.emit(
                f"Forward sizing done: {len(result.ranked)} shown, "
                f"{result.n_feasible} feasible builds"
            )

        def failed(message: str) -> None:
            self.sizing_error = message
            self._finish_task()
            self.errorOccurred.emit(f"Sizing failed: {message}")
            self.resultsChanged.emit()

        def cancelled() -> None:
            self._finish_task()
            self.statusMessage.emit("Sizing cancelled")

        self._start_task(_Task(job), done, failed, cancelled)
        return True

    def cancel_run(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _start_task(self, task: _Task, done, failed, cancelled) -> None:
        self._task = task
        task.signals.progress.connect(self.progress)
        task.signals.finished.connect(done)
        task.signals.failed.connect(failed)
        task.signals.cancelled.connect(cancelled)
        self.busy = True
        self.busyChanged.emit(True)
        QThreadPool.globalInstance().start(task)

    def _finish_task(self) -> None:
        self._task = None
        self.busy = False
        self.busyChanged.emit(False)

    def wait_idle(self, timeout_ms: int = 30000) -> bool:
        """Block until background work is done (used by scripts and tests)."""
        from PySide6.QtCore import QCoreApplication, QElapsedTimer

        timer = QElapsedTimer()
        timer.start()
        while self.busy and timer.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
            QThreadPool.globalInstance().waitForDone(10)
        return not self.busy

    # ---- compare ---------------------------------------------------------------------------

    def add_to_compare(self, build: Build) -> bool:
        if build in self.compare_builds:
            self.statusMessage.emit("That build is already in the comparison")
            return False
        if len(self.compare_builds) >= MAX_COMPARE:
            self.errorOccurred.emit(f"The comparison holds at most {MAX_COMPARE} builds")
            return False
        self.compare_builds.append(build)
        self._touch()
        self.compareChanged.emit()
        return True

    def remove_from_compare(self, index: int) -> None:
        if 0 <= index < len(self.compare_builds):
            del self.compare_builds[index]
            self._touch()
            self.compareChanged.emit()

    def clear_compare(self) -> None:
        self.compare_builds.clear()
        self._touch()
        self.compareChanged.emit()

    def compare_results(self) -> list[tuple[Build, BuildResult | None, str | None]]:
        """Each compared build evaluated in the current environment and payload."""
        out = []
        atm = atmosphere(self.mission.altitude_m, self.mission.temp_offset_c)
        for b in self.compare_builds:
            try:
                r = assess_build(
                    b,
                    self.mission.payload_kg,
                    atm,
                    self.assumptions,
                    self.constraints,
                    payload_power_w=self.mission.payload_power_w,
                )
                out.append((b, r, None))
            except SolveError as exc:
                out.append((b, None, str(exc) or "cannot hover"))
        return out

    # ---- database --------------------------------------------------------------------------

    def save_component(self, kind: str, entry: dict[str, Any]) -> None:
        """Validate and persist a custom component. Raises ``DatabaseError`` on bad input."""
        self.db.add_custom(kind, entry, self.custom_dir)
        self._after_database_change()

    def delete_component(self, kind: str, entry_id: str) -> None:
        self.db.delete_custom(kind, entry_id, self.custom_dir)
        self._after_database_change()

    def _after_database_change(self) -> None:
        # Drop references to components that no longer exist, keep the rest.
        for kind in KINDS:
            ids = self.allow[kind]
            if ids is not None:
                self.allow[kind] = {i for i in ids if i in getattr(self.db, kind)} or None
        for kind in KINDS:
            single = SINGULAR[kind]
            if self.reverse_ids[single] not in getattr(self.db, kind):
                self.reverse_ids[single] = None
        self.compare_builds = [
            b
            for b in self.compare_builds
            if b.motor.id in self.db.motors
            and b.prop.id in self.db.props
            and b.battery.id in self.db.batteries
            and b.esc.id in self.db.escs
        ]
        self._touch(True)
        self.databaseChanged.emit()
        self.filtersChanged.emit()
        self.compareChanged.emit()
        self.reverseSelectionChanged.emit()
        self.evaluate_reverse()

    # ---- projects and export ---------------------------------------------------------------

    def to_project(self) -> Project:
        build = self.reverse_build()
        return Project(
            mission=self.mission,
            assumptions=self.assumptions,
            constraints=self.constraints,
            mode=self.mode,
            scorer=self.scorer,
            top_n=self.top_n,
            allow={k: (None if v is None else sorted(v)) for k, v in self.allow.items()},
            reverse_build=build_to_dict(build) if build else None,
            compare_builds=[build_to_dict(b) for b in self.compare_builds],
        )

    def apply_project(self, project: Project) -> list[str]:
        """Load a project's inputs; returns warnings for components that no longer exist."""
        warnings: list[str] = []
        self._reset_inputs()
        self.mission, self.assumptions = project.mission, project.assumptions
        self.constraints, self.mode = project.constraints, project.mode
        self.scorer = project.scorer if project.scorer in SCORERS else "flight_time"
        self.top_n = project.top_n
        for kind in KINDS:
            ids = project.allow.get(kind)
            if ids is not None:
                known = {i for i in ids if i in getattr(self.db, kind)}
                if len(known) < len(ids):
                    warnings.append(f"some {kind} in the project's filter no longer exist")
                self.allow[kind] = known or None
        if project.reverse_build:
            try:
                b = build_from_dict(self.db, project.reverse_build)
                self.reverse_ids = {
                    "motor": b.motor.id,
                    "prop": b.prop.id,
                    "battery": b.battery.id,
                    "esc": b.esc.id,
                }
            except ValueError as exc:
                warnings.append(f"reverse-mode selection dropped: {exc}")
        for raw in project.compare_builds:
            try:
                self.compare_builds.append(build_from_dict(self.db, raw))
            except ValueError as exc:
                warnings.append(f"comparison entry dropped: {exc}")
        self.sizing_result = None
        self._results_version = -1
        self.dirty = False
        for sig in (
            self.missionChanged,
            self.settingsChanged,
            self.filtersChanged,
            self.reverseSelectionChanged,
            self.compareChanged,
            self.resultsChanged,
        ):
            sig.emit()
        self.evaluate_reverse()
        self.projectChanged.emit()
        return warnings

    def new_project(self) -> None:
        self._reset_inputs()
        self.sizing_result = None
        self.project_path = None
        self.dirty = False
        for sig in (
            self.missionChanged,
            self.settingsChanged,
            self.filtersChanged,
            self.reverseSelectionChanged,
            self.compareChanged,
            self.resultsChanged,
        ):
            sig.emit()
        self.evaluate_reverse()
        self.projectChanged.emit()

    def save_project_to(self, path: Path | str) -> None:
        save_project(path, self.to_project())
        self.project_path = Path(path)
        self.dirty = False
        self.projectChanged.emit()
        self.statusMessage.emit(f"Saved {self.project_path.name}")

    def open_project_from(self, path: Path | str) -> list[str]:
        """Raises ``ProjectError`` for unreadable files."""
        project = load_project(path)
        warnings = self.apply_project(project)
        self.project_path = Path(path)
        self.dirty = False
        self.projectChanged.emit()
        self.statusMessage.emit(f"Opened {self.project_path.name}")
        return warnings

    def export_results_csv(self, path: Path | str) -> int:
        if not self.sizing_result or not self.sizing_result.ranked:
            raise ValueError("there are no results to export; run a forward sizing first")
        n = write_results_csv(self.sizing_result.ranked, path)
        self.statusMessage.emit(f"Exported {n} builds to {Path(path).name}")
        return n


__all__ = ["AppState", "DatabaseError", "ProjectError", "KINDS", "SINGULAR", "MAX_COMPARE"]
