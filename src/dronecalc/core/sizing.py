"""Forward sizing (mission -> ranked builds) and reverse sizing (components -> performance).

Forward mode, per (motor, prop, battery chemistry/cell-count) candidate:
  1. size a *continuous* battery by under-relaxed mass iteration until total mass converges;
  2. match real database batteries at or above the required capacity;
  3. re-evaluate each exactly, apply the hard constraints, and rank the feasible builds.

Reverse mode bisects payload against the hover-throttle and thrust-to-weight limits.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from dronecalc.core.database import Database
from dronecalc.core.environment import Atmosphere, atmosphere, battery_temp_factor
from dronecalc.core.evaluate import (
    BuildResult,
    SolveError,
    evaluate_build,
    solve_hover,
)
from dronecalc.core.feasibility import (
    Scorer,
    check_constraints,
    check_hover_limits,
    rank_builds,
    with_violations,
)
from dronecalc.core.frame import estimate_frame_mass_kg
from dronecalc.core.models import (
    ESC,
    Assumptions,
    Battery,
    Build,
    Constraints,
    Mission,
    Motor,
    Propeller,
)

MAX_MASS_KG_HARD_STOP = 500.0


class SizingError(RuntimeError):
    """A candidate cannot be sized; the message is a short rejection reason code."""


class SizingCancelled(RuntimeError):
    """Raised by ``size_forward`` when its ``cancel`` callback asks it to stop."""


# ---- shared helpers ------------------------------------------------------------------------


def assess_build(
    build: Build,
    payload_kg: float,
    atm: Atmosphere,
    assumptions: Assumptions,
    constraints: Constraints,
    mission: Mission | None = None,
    payload_power_w: float = 0.0,
) -> BuildResult:
    """Evaluate a build and attach its constraint violations (mission limits are optional)."""
    payload_power = mission.payload_power_w if mission else payload_power_w
    result = evaluate_build(build, payload_kg, atm, assumptions, payload_power)
    violations = check_constraints(
        result,
        constraints,
        max_mass_kg=mission.max_mass_kg if mission else None,
        max_budget_usd=mission.max_budget_usd if mission else None,
        target_flight_time_min=mission.target_flight_time_min if mission else None,
    )
    return with_violations(result, violations)


# ---- forward mode --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContinuousBattery:
    capacity_mah: float
    mass_kg: float
    iterations: int
    total_mass_kg: float


def _pseudo_battery(
    template: list[Battery], cells: int, chemistry: str, mass_kg: float, se: float
) -> Battery:
    """A continuous-size battery of mass ``mass_kg`` using the group's typical properties."""
    ref = template[0]
    nominal = ref.cell_nominal_v
    capacity_ah = mass_kg * se / (cells * nominal)
    coeff = sum(b.resistance_ohm_ah_per_cell for b in template) / len(template)
    return Battery(
        id="continuous",
        name="continuous-size battery",
        chemistry=chemistry,
        nominal_cell_v=nominal,
        cells=cells,
        capacity_mah=capacity_ah * 1000.0,
        mass_g=mass_kg * 1000.0,
        c_rate_cont=min(b.c_rate_cont for b in template),
        internal_resistance_mohm=1000.0 * coeff * cells / capacity_ah,
    )


def size_continuous_battery(
    motor: Motor,
    prop: Propeller,
    esc: ESC,
    group: list[Battery],
    mission: Mission,
    atm: Atmosphere,
    assumptions: Assumptions,
    frame_mass_kg: float,
) -> ContinuousBattery:
    """Under-relaxed battery-mass iteration until total mass converges (default tol 0.1%).

    Raises ``SizingError`` with a reason code when the candidate cannot hover or diverges.
    """
    cells = group[0].cells
    chemistry = group[0].chemistry
    se = Database.group_specific_energy(group)
    f_temp = battery_temp_factor(atm.temperature_c, assumptions.battery_temp_table)
    usable = assumptions.depth_of_discharge * f_temp * (1.0 - assumptions.flight_time_derate)
    hours = mission.target_flight_time_min / 60.0
    nominal_v = cells * group[0].cell_nominal_v
    mass_limit = mission.max_mass_kg or MAX_MASS_KG_HARD_STOP

    other_kg = (
        frame_mass_kg
        + mission.n_rotors * (motor.mass_kg + prop.mass_kg + esc.mass_kg)
        + assumptions.avionics_mass_g / 1000.0
    )
    m_batt = 0.4 * (other_kg + mission.payload_kg) + 0.05  # initial guess, kg

    for it in range(1, assumptions.max_mass_iterations + 1):
        battery = _pseudo_battery(group, cells, chemistry, m_batt, se)
        build = Build(motor, prop, battery, esc, mission.n_rotors, frame_mass_kg)
        try:
            hover = solve_hover(
                build, mission.payload_kg, atm, assumptions, mission.payload_power_w
            )
        except SolveError as exc:
            raise SizingError("no_solution") from exc
        if hover.throttle > 1.0:
            raise SizingError("cannot_hover")
        total = hover.masses.total_kg
        if total > mass_limit:
            raise SizingError("mass_limit")

        capacity_req_ah = hover.battery_current_a * hours / usable
        m_target = capacity_req_ah * nominal_v / se
        residual = abs(m_target - m_batt) * (1.0 + assumptions.wiring_fraction) / total
        if residual <= assumptions.mass_tolerance:
            return ContinuousBattery(capacity_req_ah * 1000.0, m_batt, it, total)
        m_batt += assumptions.relaxation * (m_target - m_batt)
    raise SizingError("mass_diverged")


@dataclass
class SizingResult:
    mission: Mission
    atmosphere: Atmosphere
    ranked: list[BuildResult]
    n_candidates: int
    n_feasible: int
    rejections: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def size_forward(
    mission: Mission,
    db: Database,
    assumptions: Assumptions | None = None,
    constraints: Constraints | None = None,
    scorer: str | Scorer = "flight_time",
    top_n: int = 10,
    batteries_per_config: int = 3,
    allow: Mapping[str, Iterable[str] | None] | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> SizingResult:
    """Derive ranked feasible builds from mission requirements.

    ``allow`` optionally restricts the search to component ids per kind (keys ``motors``,
    ``props``, ``batteries``, ``escs``; a missing or ``None`` kind means all). ``progress(done,
    total)`` is called after each motor/prop pair; ``cancel()`` returning True aborts with
    ``SizingCancelled``.
    """
    assumptions = assumptions or Assumptions()
    constraints = constraints or Constraints()
    atm = atmosphere(mission.altitude_m, mission.temp_offset_c)
    allowed = {k: (None if v is None else set(v)) for k, v in (allow or {}).items()}
    groups = db.battery_groups(allowed.get("batteries"))
    escs = [e for e in db.escs.values() if allowed.get("escs") is None or e.id in allowed["escs"]]
    pairs = [
        (motor, prop)
        for motor in db.motors.values()
        if allowed.get("motors") is None or motor.id in allowed["motors"]
        for prop in db.props.values()
        if (allowed.get("props") is None or prop.id in allowed["props"])
        and motor.prop_min_in <= prop.diameter_in <= motor.prop_max_in
    ]

    feasible: list[BuildResult] = []
    rejections: Counter = Counter()
    n_candidates = 0

    for done, (motor, prop) in enumerate(pairs):
        if cancel is not None and cancel():
            raise SizingCancelled("sizing cancelled")
        if progress is not None:
            progress(done, len(pairs))
        frame_kg = estimate_frame_mass_kg(
            prop.diameter_in,
            mission.n_rotors,
            assumptions.prop_clearance,
            mission.frame_mass_override_g,
        )
        for (_chemistry, cells), packs in groups.items():
            if not (motor.min_cells <= cells <= motor.max_cells):
                continue
            esc = _pick_esc(escs, motor, cells)
            if esc is None:
                rejections["no_esc"] += 1
                continue
            n_candidates += 1
            try:
                cont = size_continuous_battery(
                    motor, prop, esc, packs, mission, atm, assumptions, frame_kg
                )
            except SizingError as exc:
                rejections[str(exc)] += 1
                continue
            matches = [b for b in packs if b.capacity_mah >= cont.capacity_mah]
            if not matches:
                rejections["no_matching_battery"] += 1
                continue
            for battery in matches[:batteries_per_config]:
                build = Build(motor, prop, battery, esc, mission.n_rotors, frame_kg)
                try:
                    result = assess_build(
                        build, mission.payload_kg, atm, assumptions, constraints, mission
                    )
                except SolveError:
                    rejections["no_solution"] += 1
                    continue
                if result.feasible:
                    feasible.append(result)
                else:
                    for v in result.violations:
                        rejections[v.code] += 1

    if progress is not None:
        progress(len(pairs), len(pairs))
    ranked = rank_builds(feasible, scorer)
    warnings = list(db.check(assumptions.fm_range))
    return SizingResult(
        mission=mission,
        atmosphere=atm,
        ranked=ranked[:top_n],
        n_candidates=n_candidates,
        n_feasible=len(feasible),
        rejections=dict(rejections),
        warnings=warnings,
    )


def _pick_esc(escs: Iterable[ESC], motor: Motor, cells: int) -> ESC | None:
    """Lightest ESC whose current rating covers the motor limit and whose cell range fits."""
    ok = [
        e
        for e in escs
        if e.max_current_a >= motor.max_current_a and e.min_cells <= cells <= e.max_cells
    ]
    return min(ok, key=lambda e: (e.mass_g, e.price_usd, e.id)) if ok else None


# ---- reverse mode --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReverseResult:
    result: BuildResult  # evaluated at the requested payload
    max_payload_kg: float
    limiting_factor: str  # "hover_throttle", "thrust_to_weight", "no_solution" or "none_below_cap"
    can_fly_empty: bool
    flight_time_at_max_payload_min: float | None


MAX_PAYLOAD_CAP_KG = 100.0


def size_reverse(
    build: Build,
    payload_kg: float = 0.0,
    altitude_m: float = 0.0,
    temp_offset_c: float = 0.0,
    payload_power_w: float = 0.0,
    assumptions: Assumptions | None = None,
    constraints: Constraints | None = None,
    tol_kg: float = 1e-6,
) -> ReverseResult:
    """Flight time at ``payload_kg`` and the maximum payload for a fixed component set."""
    assumptions = assumptions or Assumptions()
    constraints = constraints or Constraints()
    atm = atmosphere(altitude_m, temp_offset_c)

    at_payload = assess_build(
        build, payload_kg, atm, assumptions, constraints, payload_power_w=payload_power_w
    )

    def failures(payload: float) -> tuple[BuildResult | None, list[str]]:
        try:
            r = evaluate_build(build, payload, atm, assumptions, payload_power_w)
        except SolveError:
            return None, ["no_solution"]
        return r, [v.code for v in check_hover_limits(r, constraints)]

    _, bad0 = failures(0.0)
    if bad0:
        return ReverseResult(at_payload, 0.0, bad0[0], False, None)

    lo, hi = 0.0, 0.1
    while hi < MAX_PAYLOAD_CAP_KG and not failures(hi)[1]:
        lo, hi = hi, hi * 2.0
    if hi >= MAX_PAYLOAD_CAP_KG and not failures(hi)[1]:
        r, _ = failures(hi)
        return ReverseResult(at_payload, hi, "none_below_cap", True, r.flight_time_min)

    while hi - lo > tol_kg:
        mid = 0.5 * (lo + hi)
        if failures(mid)[1]:
            hi = mid
        else:
            lo = mid
    limiting = failures(hi)[1][0]
    r_max, _ = failures(lo)
    return ReverseResult(at_payload, lo, limiting, True, r_max.flight_time_min)


__all__ = [
    "ContinuousBattery",
    "SizingCancelled",
    "ReverseResult",
    "SizingError",
    "SizingResult",
    "assess_build",
    "size_continuous_battery",
    "size_forward",
    "size_reverse",
]
