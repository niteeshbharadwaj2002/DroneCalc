"""Evaluate a concrete build: mass breakdown, hover state, peak thrust and flight time."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from dronecalc.core.constants import G
from dronecalc.core.environment import Atmosphere, battery_temp_factor
from dronecalc.core.models import Assumptions, Build
from dronecalc.core.propulsion import (
    MotorPoint,
    SolveError,
    max_thrust_point,
    motor_point_for_thrust,
    solve_pack,
)


@dataclass(frozen=True)
class MassBreakdown:
    frame_kg: float
    motors_kg: float
    props_kg: float
    escs_kg: float
    battery_kg: float
    avionics_kg: float
    wiring_kg: float
    payload_kg: float

    @property
    def dry_kg(self) -> float:
        """Everything except payload and wiring (the base for the wiring fraction)."""
        return (
            self.frame_kg
            + self.motors_kg
            + self.props_kg
            + self.escs_kg
            + self.battery_kg
            + self.avionics_kg
        )

    @property
    def total_kg(self) -> float:
        return self.dry_kg + self.wiring_kg + self.payload_kg


def mass_breakdown(build: Build, payload_kg: float, assumptions: Assumptions) -> MassBreakdown:
    n = build.n_rotors
    parts = MassBreakdown(
        frame_kg=build.frame_mass_kg,
        motors_kg=n * build.motor.mass_kg,
        props_kg=n * build.prop.mass_kg,
        escs_kg=n * build.esc.mass_kg,
        battery_kg=build.battery.mass_kg,
        avionics_kg=assumptions.avionics_mass_g / 1000.0,
        wiring_kg=0.0,
        payload_kg=payload_kg,
    )
    wiring = assumptions.wiring_fraction * parts.dry_kg
    return replace(parts, wiring_kg=wiring)


@dataclass(frozen=True)
class HoverState:
    masses: MassBreakdown
    thrust_per_rotor_n: float
    motor: MotorPoint
    throttle: float
    battery_power_w: float
    battery_current_a: float
    pack_voltage_v: float


def solve_hover(
    build: Build,
    payload_kg: float,
    atm: Atmosphere,
    assumptions: Assumptions,
    payload_power_w: float = 0.0,
) -> HoverState:
    masses = mass_breakdown(build, payload_kg, assumptions)
    n = build.n_rotors
    thrust = masses.total_kg * G / n
    mp = motor_point_for_thrust(build.motor, build.prop, thrust, atm.density)
    eta = build.esc.efficiency or assumptions.esc_efficiency
    p_bat = n * mp.electrical_power_w / eta + assumptions.avionics_power_w + payload_power_w
    i_bat, v_loaded = solve_pack(p_bat, build.battery.voltage_v, build.battery.resistance_ohm)
    return HoverState(
        masses=masses,
        thrust_per_rotor_n=thrust,
        motor=mp,
        throttle=mp.voltage_v / v_loaded,
        battery_power_w=p_bat,
        battery_current_a=i_bat,
        pack_voltage_v=v_loaded,
    )


def flight_time_min(
    capacity_ah: float, battery_current_a: float, atm: Atmosphere, assumptions: Assumptions
) -> float:
    """t = C * DoD * f_temp * (1 - derate) / I_bat, in minutes."""
    f_temp = battery_temp_factor(atm.temperature_c, assumptions.battery_temp_table)
    usable_ah = (
        capacity_ah
        * assumptions.depth_of_discharge
        * f_temp
        * (1.0 - assumptions.flight_time_derate)
    )
    return 60.0 * usable_ah / battery_current_a


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    value: float
    limit: float


@dataclass(frozen=True)
class BuildResult:
    build: Build
    atmosphere: Atmosphere
    payload_kg: float
    masses: MassBreakdown
    # hover
    thrust_per_rotor_n: float
    hover_rpm: float
    hover_throttle: float
    hover_motor_current_a: float
    hover_motor_voltage_v: float
    hover_shaft_power_w: float  # total over all rotors
    hover_battery_power_w: float
    hover_battery_current_a: float
    hover_pack_voltage_v: float
    hover_c_rate: float
    hover_efficiency_g_per_w: float
    figure_of_merit: float
    flight_time_min: float
    # peak
    max_thrust_per_rotor_n: float
    thrust_to_weight: float
    peak_battery_current_a: float
    peak_c_rate: float
    peak_limited_by: str
    cost_usd: float
    warnings: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return not self.violations

    @property
    def total_mass_kg(self) -> float:
        return self.masses.total_kg

    def to_dict(self) -> dict:
        b = self.build
        return {
            "motor": b.motor.id,
            "prop": b.prop.id,
            "battery": b.battery.id,
            "esc": b.esc.id,
            "n_rotors": b.n_rotors,
            "cells": b.battery.cells,
            "payload_kg": self.payload_kg,
            "total_mass_kg": self.masses.total_kg,
            "mass_breakdown_kg": asdict(self.masses),
            "hover_rpm": self.hover_rpm,
            "hover_throttle": self.hover_throttle,
            "hover_motor_current_a": self.hover_motor_current_a,
            "hover_battery_current_a": self.hover_battery_current_a,
            "hover_battery_power_w": self.hover_battery_power_w,
            "hover_pack_voltage_v": self.hover_pack_voltage_v,
            "hover_efficiency_g_per_w": self.hover_efficiency_g_per_w,
            "figure_of_merit": self.figure_of_merit,
            "flight_time_min": self.flight_time_min,
            "thrust_to_weight": self.thrust_to_weight,
            "peak_battery_current_a": self.peak_battery_current_a,
            "peak_c_rate": self.peak_c_rate,
            "cost_usd": self.cost_usd,
            "air_density": self.atmosphere.density,
            "density_altitude_m": self.atmosphere.density_altitude_m,
            "warnings": list(self.warnings),
            "violations": [asdict(v) for v in self.violations],
            "feasible": self.feasible,
            "label": "predicted, unverified",
        }


def evaluate_build(
    build: Build,
    payload_kg: float,
    atm: Atmosphere,
    assumptions: Assumptions,
    payload_power_w: float = 0.0,
) -> BuildResult:
    """Full evaluation of a build. Raises ``SolveError`` if the pack cannot supply the load.

    The result carries no constraint violations; run ``feasibility.check_constraints`` for those.
    """
    hover = solve_hover(build, payload_kg, atm, assumptions, payload_power_w)
    n = build.n_rotors
    eta = build.esc.efficiency or assumptions.esc_efficiency
    peak = max_thrust_point(
        build.motor,
        build.prop,
        build.esc,
        build.battery,
        atm.density,
        n,
        eta,
        aux_power_w=assumptions.avionics_power_w + payload_power_w,
    )
    weight_n = hover.masses.total_kg * G
    cap_ah = build.battery.capacity_ah
    warnings: list[str] = []
    fm = build.prop.figure_of_merit
    lo, hi = assumptions.fm_range
    if not (lo <= fm <= hi):
        warnings.append(
            f"propeller {build.prop.id}: figure of merit {fm:.2f} outside expected {lo}-{hi}; "
            "check Ct/Cp"
        )
    cost = n * (build.motor.price_usd + build.prop.price_usd + build.esc.price_usd)
    cost += build.battery.price_usd
    return BuildResult(
        build=build,
        atmosphere=atm,
        payload_kg=payload_kg,
        masses=hover.masses,
        thrust_per_rotor_n=hover.thrust_per_rotor_n,
        hover_rpm=hover.motor.rpm,
        hover_throttle=hover.throttle,
        hover_motor_current_a=hover.motor.current_a,
        hover_motor_voltage_v=hover.motor.voltage_v,
        hover_shaft_power_w=n * hover.motor.shaft_power_w,
        hover_battery_power_w=hover.battery_power_w,
        hover_battery_current_a=hover.battery_current_a,
        hover_pack_voltage_v=hover.pack_voltage_v,
        hover_c_rate=hover.battery_current_a / cap_ah,
        hover_efficiency_g_per_w=hover.masses.total_kg * 1000.0 / hover.battery_power_w,
        figure_of_merit=fm,
        flight_time_min=flight_time_min(cap_ah, hover.battery_current_a, atm, assumptions),
        max_thrust_per_rotor_n=peak.thrust_per_rotor_n,
        thrust_to_weight=n * peak.thrust_per_rotor_n / weight_n,
        peak_battery_current_a=peak.battery_current_a,
        peak_c_rate=peak.battery_current_a / cap_ah,
        peak_limited_by=peak.limited_by,
        cost_usd=cost,
        warnings=warnings,
    )


__all__ = [
    "BuildResult",
    "HoverState",
    "MassBreakdown",
    "SolveError",
    "Violation",
    "evaluate_build",
    "flight_time_min",
    "mass_breakdown",
    "solve_hover",
]
