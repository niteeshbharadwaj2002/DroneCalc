"""Parameter sweeps of one build, used by plots so front ends never re-implement physics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from dronecalc.core.environment import atmosphere
from dronecalc.core.evaluate import evaluate_build
from dronecalc.core.feasibility import check_hover_limits
from dronecalc.core.models import Assumptions, Build, Constraints
from dronecalc.core.propulsion import SolveError


@dataclass(frozen=True)
class SweepPoint:
    x: float
    flight_time_min: float | None  # None when the build cannot hover at this point
    hover_throttle: float | None
    hover_power_w: float | None
    thrust_to_weight: float | None
    total_mass_kg: float | None
    within_limits: bool  # hover throttle and thrust-to-weight limits both met


def _point(
    x: float,
    build: Build,
    payload_kg: float,
    altitude_m: float,
    temp_offset_c: float,
    payload_power_w: float,
    assumptions: Assumptions,
    constraints: Constraints,
) -> SweepPoint:
    atm = atmosphere(altitude_m, temp_offset_c)
    try:
        r = evaluate_build(build, payload_kg, atm, assumptions, payload_power_w)
    except SolveError:
        return SweepPoint(x, None, None, None, None, None, False)
    return SweepPoint(
        x,
        r.flight_time_min,
        r.hover_throttle,
        r.hover_battery_power_w,
        r.thrust_to_weight,
        r.total_mass_kg,
        not check_hover_limits(r, constraints),
    )


def sweep_payload(
    build: Build,
    payloads_kg: Iterable[float],
    altitude_m: float = 0.0,
    temp_offset_c: float = 0.0,
    payload_power_w: float = 0.0,
    assumptions: Assumptions | None = None,
    constraints: Constraints | None = None,
) -> list[SweepPoint]:
    """Evaluate ``build`` at each payload (kg) in a fixed environment."""
    a, c = assumptions or Assumptions(), constraints or Constraints()
    return [
        _point(p, build, p, altitude_m, temp_offset_c, payload_power_w, a, c) for p in payloads_kg
    ]


def sweep_altitude(
    build: Build,
    altitudes_m: Sequence[float],
    payload_kg: float = 0.0,
    temp_offset_c: float = 0.0,
    payload_power_w: float = 0.0,
    assumptions: Assumptions | None = None,
    constraints: Constraints | None = None,
) -> list[SweepPoint]:
    """Evaluate ``build`` at each altitude (m) for a fixed payload."""
    a, c = assumptions or Assumptions(), constraints or Constraints()
    return [
        _point(h, build, payload_kg, h, temp_offset_c, payload_power_w, a, c) for h in altitudes_m
    ]
