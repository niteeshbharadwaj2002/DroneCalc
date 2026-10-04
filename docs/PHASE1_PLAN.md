# Phase 1 Plan: CLI Core and Validation

Source: `drone_sizing_project.md` (sections 3.2 to 3.7). Goal: a UI-independent physics and sizing
core with a CLI, a seed database, and a validation harness. No Qt/PySide imports anywhere in
`dronecalc.core`.

## Design decisions

| Topic | Decision |
|---|---|
| Dependencies | Core is pure standard library (`math`, `dataclasses`, `json`, `csv`). No numpy needed. |
| Units | Database/user-facing fields use hobbyist units (g, mAh, inch, A). Physics uses SI internally. |
| Propeller model | `T = Ct rho n^2 D^4`, `P = Cp rho n^3 D^5`, n in rev/s. FM = `Ct^1.5 / (sqrt(2) Cp)`. |
| Motor model | `Ke = Kt = 60/(2 pi Kv)`, `I = Q/Kt + I0`, `V = Ke w + I Rm`. Closed form for max-thrust speed. |
| Battery | Flat nominal open-circuit voltage minus `I R_pack`; loaded voltage by fixed-point iteration. |
| Flight time | `t = C * DoD * f_temp * (1 - derate) / I_bat` |
| Wiring | 5% of dry mass (everything except payload). |
| ESC choice (forward) | Per (motor, cell count) keep the lightest ESC that satisfies current and cell limits. |
| Battery sizing | Continuous capacity from group specific energy, under-relaxed mass loop (tol 0.1%), then matched to real packs and re-evaluated exactly. |
| Scoring | Pluggable `Callable[[BuildResult], float]`; default `flight_time`. |
| Frame mass | `k * wheelbase^1.5 * (N/4)^0.85` regression, with user override. |
| Seed data | Approximate, flagged `verified: false`. Not manufacturer-grade. Validation data is NOT invented. |

## Work breakdown

1. **Housekeeping**: `.gitignore`, `.env.example`, untrack `egg-info`, package layout.
2. **Environment** (`core/environment.py`): ISA to 20 km, temperature offset, density altitude, battery temperature derating.
3. **Models** (`core/models.py`): Motor, Propeller, Battery, ESC, Mission, Assumptions, Constraints.
4. **Database** (`core/database.py`, `data/seed/*.json`): load, validate, custom entries, FM check.
5. **Propulsion** (`core/propulsion.py`): prop, motor, pack solve, max-thrust point.
6. **Frame** (`core/frame.py`): wheelbase and mass regression.
7. **Evaluation** (`core/evaluate.py`): mass breakdown, hover state, full `BuildResult`.
8. **Feasibility and ranking** (`core/feasibility.py`): hard constraints, scorers.
9. **Sizing** (`core/sizing.py`): forward mode (mass convergence, battery matching), reverse mode (payload bisection).
10. **Validation** (`core/validation.py`): reference-point comparison and exit-criterion report.
11. **CLI** (`cli.py`): `size`, `reverse`, `db`, `validate`, `--json`.
12. **API freeze** (`core/__init__.py`, `docs/API.md`).
13. **Tests**: unit, physics sanity, round-trip, CLI.
14. **Verification**: pytest, ruff, CLI smoke runs, clean `git status`.

## Exit criteria for this build

- All tests pass; `ruff check` clean; CLI runs end to end.
- Physics sanity: density scaling, mass scaling, FM range, mass convergence within 0.1%.
- Forward results round-trip through reverse mode consistently.
- The datasheet-validation exit criterion (>= 10 combos within 15%) needs real reference data. The
  harness is built and tested; the criterion is reported as **not met** until data is supplied.
