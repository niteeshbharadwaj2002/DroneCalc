# DroneCalc core API (`API_VERSION = "1.1"`)

Import from `dronecalc.core` only. It has no UI dependencies, so a desktop UI or web front end can
sit on top unchanged. Breaking changes require bumping `API_VERSION`. 1.1 (Phase 2) only adds names; every 1.0 call works unchanged.

```python
from dronecalc.core import (
    Database,
    Mission,
    Assumptions,
    Constraints,
    Build,
    size_forward,
    size_reverse,
    estimate_frame_mass_kg,
)

db = Database.load()  # data/seed + data/custom
mission = Mission(target_flight_time_min=20, payload_kg=0.5, altitude_m=500)
result = size_forward(mission, db, scorer="flight_time", top_n=5)  # SizingResult
best = result.ranked[0]  # BuildResult (best first)

rev = size_reverse(best.build, payload_kg=0.5, altitude_m=500)  # ReverseResult
rev.max_payload_kg, rev.limiting_factor, rev.result.flight_time_min
```

| Name | Purpose |
|---|---|
| `Database`, `DatabaseError` | Load seed + custom JSON, `add_custom` / `update_custom` / `delete_custom` (a deleted override restores the seed entry), `is_custom`, `check()`, `battery_groups(allowed_ids=None)` |
| `Motor`, `Propeller`, `Battery`, `ESC` | Component models (validated on construction) |
| `Build` | One motor/prop/ESC set x N rotors + battery + frame mass |
| `Mission`, `Assumptions`, `Constraints` | Inputs; every default is overridable |
| `size_forward(mission, db, ..., allow=, progress=, cancel=)` | Requirements -> ranked feasible `BuildResult`s, with rejection counts. `allow` restricts component ids per kind; `progress(done, total)`; `cancel()` returning True raises `SizingCancelled` |
| `size_reverse(build, payload_kg, ...)` | Flight time at a payload and maximum payload (bisection) |
| `assess_build`, `evaluate_build`, `check_constraints` | Evaluate one build and list constraint `Violation`s |
| `rank_builds`, `SCORERS` | Pluggable ranking; a scorer is `Callable[[BuildResult], float]`, higher is better |
| `atmosphere`, `density_altitude_m`, `battery_temp_factor` | Environment |
| `validate`, `load_reference_points`, `ValidationReport` | Datasheet comparison harness |
| `sweep_payload`, `sweep_altitude`, `SweepPoint` | One build evaluated over a range (plots); never re-implement physics in a front end |
| `mission_to_dict` / `_from_dict`, same for `assumptions`, `constraints`, `build` | JSON-ready round trips (builds are stored as component ids) |
| `Project`, `save_project`, `load_project`, `ProjectError` | `.dronecalc.json` files holding inputs only, never results |
| `write_results_csv` | CSV export of ranked results |
| `SolveError`, `SizingError`, `SizingCancelled` | No operating point / candidate cannot be sized / run cancelled |

`BuildResult.to_dict()` is JSON-ready and always carries `"label": "predicted, unverified"`.

## Model summary

| Item | Model |
|---|---|
| Propeller | `T = Ct rho n^2 D^4`, `P = Cp rho n^3 D^5` (n rev/s); FM = `Ct^1.5 / (sqrt(2) Cp)`, flagged outside 0.55-0.75 |
| Motor | `Ke = Kt = 60/(2 pi Kv)`, `I = Q/Kt + I0`, `V = Ke w + I Rm` |
| Pack | `V = n_cells * V_nom - I R_pack` (V_nom 3.7 LiPo, 3.6 Li-ion), fixed-point iteration |
| Battery power | `N V I / eta_esc + avionics + payload power` |
| Flight time | `t = C DoD f_temp (1 - derate) / I_bat` |
| Peak thrust | Full throttle with pack sag, capped at `min(motor, ESC)` max current |
| Mass | frame + motors + props + ESCs + battery + avionics + wiring (5% of dry mass) + payload |
| Atmosphere | ISA to 20 km, shifted by a temperature offset; density from `p / (R T)` |

Defaults (`Assumptions`): DoD 80%, ESC efficiency 0.95, wiring 5%, flight-time derate 10%,
avionics 5 W / 80 g. Hard constraints (`Constraints`): hover throttle <= 70%, thrust-to-weight
>= 2, motor/ESC current, motor power, battery continuous and burst C-rate, cell-count and prop-size
compatibility, mass limit, budget, target flight time.

## Behaviours worth knowing

- **Current-limited builds are density-independent in thrust.** At a fixed torque limit the model
  gives `T = (Ct/Cp) 2 pi Q / D`, so air density does not change peak thrust there; it shows up as
  higher hover throttle and shorter flight time. Voltage-limited builds lose thrust in thin air.
- **Default ranking is by flight time**, so forward mode favours the largest battery that passes
  the constraints. The scoring function is an open decision in the project plan.
- **Seed data is approximate** (`verified: false`). Frame mass, battery masses and prop
  coefficients are generic. Use `data/custom` for datasheet values.

## Known limitations (project doc, 3.4)

Static propeller coefficients, constant ESC efficiency and avionics load, no motor thermal model,
no coaxial penalty, hover only. The battery is assumed to be at ambient temperature.
