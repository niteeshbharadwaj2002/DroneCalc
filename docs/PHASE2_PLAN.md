# Phase 2 Plan: Desktop UI

Source: `drone_sizing_project.md` (section 3.5, weeks 6 to 10). Goal: a PySide6 desktop app with five
screens, project save/load and CSV export, so a hobbyist can size a drone without the CLI. The physics
stays in `dronecalc.core`, which keeps zero Qt imports (enforced by a test).

## Design decisions

| Topic | Decision |
|---|---|
| Toolkit | PySide6 Widgets (not QML) |
| Plots | pyqtgraph (responsive while sliders drag). numpy is a UI-only dependency; the core stays pure stdlib |
| Architecture | Screens -> shared `AppState` (Qt signals) -> background workers / project files -> `dronecalc.core` |
| Threading | Forward sizing runs in a worker thread with progress and cancel. Reverse mode is a few milliseconds and runs inline |
| Core changes | Additive only: `API_VERSION` 1.0 -> 1.1 |
| Project files | `.dronecalc.json` holds inputs only (mission, assumptions, constraints, selections), never results, so results are always recomputed |
| User data | Custom components live in `DRONECALC_CUSTOM_DIR`, else the repo `data/custom` in a dev checkout, else a per-user folder |
| Testing | `pytest-qt` with the offscreen platform; UI results are compared with direct core calls |

## Screens

| Screen | Content |
|---|---|
| Mission | Sliders and boxes for flight time, payload, altitude, temperature offset, rotor count; optional mass, budget, payload power, frame mass override; ranking and top-N; live density readout; forward/reverse mode; "Advanced" panel exposing every assumption and constraint with reset-to-defaults |
| Components | Reverse: pick motor, prop, battery, ESC with live compatibility warnings, results, mass bar and a flight-time-vs-payload plot. Forward: tick which components the search may use |
| Results | Sortable ranked table, detail pane (metrics, mass bar, violations, plots), "why were others rejected" panel, CSV export, permanent "predicted, unverified" banner |
| Compare | 2 to 4 builds side by side, best value per row highlighted, overlaid plot |
| Database Manager | Tabs per component type; view, add, clone, edit, delete custom entries; verified flag, figure-of-merit check, core validation errors shown inline |

Cross-cutting: project save/load, CSV export, About/assumptions dialog, readable error messages.

## Core additions (all additive)

1. `core/serialize.py`: dict round trips for `Mission`, `Assumptions`, `Constraints`, `Build`.
2. `size_forward(..., allow=, progress=, cancel=)`: component filters, progress callback, cooperative cancel (`SizingCancelled`).
3. `Database.delete_custom`, `Database.update_custom`; configurable custom directory (`config.default_custom_dir`).
4. `core/sweeps.py`: payload and altitude sweeps that feed the plots, so the UI never re-implements physics.
5. `core/export.py`: CSV export of ranked results.
6. `core/project.py`: project file save/load.
7. CLI wording fix: "evaluated 85 / feasible 88" now reads as candidate configurations vs feasible builds, and `dronecalc gui` launches the app.

## Schedule (weeks 6 to 10)

| Week | Work | Done when |
|---|---|---|
| 6 | UI skeleton, `AppState`, workers, navigation shell, Mission screen, core additions 1, 2, 3, 7 | Mission can be set and shows live density |
| 7 | Results screen, plots, CSV export | Forward sizing runs from the UI and matches the CLI exactly |
| 8 | Components screen, forward filters, reverse mode | A hand-picked build gives flight time and max payload |
| 9 | Compare and Database Manager | A custom motor can be added and appears in results |
| 10 | Save/load, About, error handling, UI tests, usability pass | All flows work without the CLI |

## Exit criteria

- Forward and reverse sizing work end to end in the UI with results identical to the CLI/core.
- Project save/load round-trips.
- Sizing never blocks the window.
- `dronecalc.core` has no Qt imports (test).
- Assumptions and the "predicted, unverified" label are visible wherever results appear.

## Risks

- Seed data is approximate (`verified: false`); the UI shows this clearly. Datasheet validation (next
  work item) may change model constants but not the UI.
- Python 3.9 in the current venv works with PySide6 6.10; newer Python is recommended for release builds.

## Status

Built and verified (see the end-of-build report): all five screens, background forward sizing with
progress and cancel, inline reverse sizing, project save/load, CSV export, About dialog, core
additions 1 to 7, and `pytest-qt` UI tests that compare displayed numbers with direct core calls.
Not done: packaging (Phase 3), usability testing with real users, datasheet validation data.
