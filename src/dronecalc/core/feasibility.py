"""Hard feasibility constraints and pluggable ranking of builds."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Callable

from dronecalc.core.evaluate import BuildResult, Violation
from dronecalc.core.models import Constraints

Scorer = Callable[[BuildResult], float]  # higher is better


def check_hover_limits(result: BuildResult, constraints: Constraints) -> list[Violation]:
    """The two limits that bound payload in reverse mode: hover throttle and thrust-to-weight."""
    out: list[Violation] = []
    if result.hover_throttle > constraints.max_hover_throttle:
        out.append(
            Violation(
                "hover_throttle",
                f"hover throttle {result.hover_throttle:.0%} exceeds "
                f"{constraints.max_hover_throttle:.0%}",
                result.hover_throttle,
                constraints.max_hover_throttle,
            )
        )
    if result.thrust_to_weight < constraints.min_thrust_to_weight:
        out.append(
            Violation(
                "thrust_to_weight",
                f"thrust-to-weight {result.thrust_to_weight:.2f} below "
                f"{constraints.min_thrust_to_weight:.2f}",
                result.thrust_to_weight,
                constraints.min_thrust_to_weight,
            )
        )
    return out


def check_constraints(
    result: BuildResult,
    constraints: Constraints,
    *,
    max_mass_kg: float | None = None,
    max_budget_usd: float | None = None,
    target_flight_time_min: float | None = None,
) -> list[Violation]:
    """All hard constraints (project doc, 3.2); returns the violations, empty if feasible."""
    b = result.build
    out: list[Violation] = []

    cells = b.battery.cells
    if not (b.motor.min_cells <= cells <= b.motor.max_cells):
        out.append(
            Violation(
                "motor_voltage",
                f"{cells}S outside motor range {b.motor.min_cells}-{b.motor.max_cells}S",
                cells,
                b.motor.max_cells,
            )
        )
    if not (b.esc.min_cells <= cells <= b.esc.max_cells):
        out.append(
            Violation(
                "esc_voltage",
                f"{cells}S outside ESC range {b.esc.min_cells}-{b.esc.max_cells}S",
                cells,
                b.esc.max_cells,
            )
        )
    d = b.prop.diameter_in
    if not (b.motor.prop_min_in <= d <= b.motor.prop_max_in):
        out.append(
            Violation(
                "prop_size",
                f'{d:g}" prop outside motor range {b.motor.prop_min_in:g}-{b.motor.prop_max_in:g}"',
                d,
                b.motor.prop_max_in,
            )
        )

    out.extend(check_hover_limits(result, constraints))

    if result.hover_motor_current_a > b.motor.max_current_a:
        out.append(
            Violation(
                "motor_current",
                f"hover current {result.hover_motor_current_a:.1f} A exceeds motor limit "
                f"{b.motor.max_current_a:.1f} A",
                result.hover_motor_current_a,
                b.motor.max_current_a,
            )
        )
    if result.hover_motor_current_a > b.esc.max_current_a:
        out.append(
            Violation(
                "esc_current",
                f"hover current {result.hover_motor_current_a:.1f} A exceeds ESC rating "
                f"{b.esc.max_current_a:.1f} A",
                result.hover_motor_current_a,
                b.esc.max_current_a,
            )
        )
    if constraints.check_motor_power and b.motor.max_power_w is not None:
        p_motor = result.hover_motor_current_a * result.hover_motor_voltage_v
        if p_motor > b.motor.max_power_w:
            out.append(
                Violation(
                    "motor_power",
                    f"hover power {p_motor:.0f} W exceeds motor limit {b.motor.max_power_w:.0f} W",
                    p_motor,
                    b.motor.max_power_w,
                )
            )
    if constraints.check_battery_c_rate:
        if result.hover_c_rate > b.battery.c_rate_cont:
            out.append(
                Violation(
                    "battery_c_rate",
                    f"hover draw {result.hover_c_rate:.1f}C exceeds {b.battery.c_rate_cont:g}C "
                    "continuous rating",
                    result.hover_c_rate,
                    b.battery.c_rate_cont,
                )
            )
        if result.peak_c_rate > b.battery.c_rate_burst_eff:
            out.append(
                Violation(
                    "battery_peak_c_rate",
                    f"full-throttle draw {result.peak_c_rate:.1f}C exceeds "
                    f"{b.battery.c_rate_burst_eff:g}C burst rating",
                    result.peak_c_rate,
                    b.battery.c_rate_burst_eff,
                )
            )

    if max_mass_kg is not None and result.total_mass_kg > max_mass_kg:
        out.append(
            Violation(
                "mass_limit",
                f"mass {result.total_mass_kg:.2f} kg exceeds {max_mass_kg:.2f} kg",
                result.total_mass_kg,
                max_mass_kg,
            )
        )
    if max_budget_usd is not None and result.cost_usd > max_budget_usd:
        out.append(
            Violation(
                "budget",
                f"cost ${result.cost_usd:.0f} exceeds ${max_budget_usd:.0f}",
                result.cost_usd,
                max_budget_usd,
            )
        )
    if target_flight_time_min is not None and result.flight_time_min < target_flight_time_min:
        out.append(
            Violation(
                "flight_time",
                f"flight time {result.flight_time_min:.1f} min below target "
                f"{target_flight_time_min:.1f} min",
                result.flight_time_min,
                target_flight_time_min,
            )
        )
    return out


def with_violations(result: BuildResult, violations: list[Violation]) -> BuildResult:
    return replace(result, violations=list(violations))


# ---- ranking -------------------------------------------------------------------------------

SCORERS: dict[str, Scorer] = {
    "flight_time": lambda r: r.flight_time_min,  # default placeholder (project doc, 3.2)
    "lightest": lambda r: -r.total_mass_kg,
    "cheapest": lambda r: -r.cost_usd,
    "efficiency": lambda r: r.hover_efficiency_g_per_w,
}


def get_scorer(scorer: str | Scorer) -> Scorer:
    if callable(scorer):
        return scorer
    try:
        return SCORERS[scorer]
    except KeyError:
        raise ValueError(f"unknown scorer {scorer!r}; choose from {sorted(SCORERS)}") from None


def rank_builds(results: Iterable[BuildResult], scorer: str | Scorer = "flight_time"):
    """Sort best-first by ``scorer``; ties broken by lower cost, then by component ids."""
    score = get_scorer(scorer)
    return sorted(
        results,
        key=lambda r: (
            -score(r),
            r.cost_usd,
            r.build.motor.id,
            r.build.prop.id,
            r.build.battery.id,
        ),
    )
