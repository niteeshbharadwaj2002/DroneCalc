"""Text helpers and display constants shared by the screens."""

from __future__ import annotations

from dronecalc.core import BuildResult

DISCLAIMER = (
    "Predicted, unverified: physics model on approximate seed data; not flight-test validated."
)

REJECTION_TEXT = {
    "no_esc": "No ESC covers the motor current at this cell count",
    "cannot_hover": "Cannot lift its own weight (hover throttle above 100%)",
    "no_solution": "Battery cannot supply the load (no operating point)",
    "mass_limit": "Exceeds the maximum mass",
    "mass_diverged": "Battery sizing did not converge",
    "no_matching_battery": "No real battery is large enough for the required capacity",
    "hover_throttle": "Hover throttle above the limit",
    "thrust_to_weight": "Thrust-to-weight below the minimum",
    "motor_voltage": "Cell count outside the motor's range",
    "esc_voltage": "Cell count outside the ESC's range",
    "prop_size": "Propeller outside the motor's size range",
    "motor_current": "Hover current above the motor limit",
    "esc_current": "Hover current above the ESC rating",
    "motor_power": "Hover power above the motor limit",
    "battery_c_rate": "Hover draw above the battery's continuous C-rate",
    "battery_peak_c_rate": "Full-throttle draw above the battery's burst C-rate",
    "budget": "Over budget",
    "flight_time": "Flight time below the target",
}

LIMITING_TEXT = {
    "hover_throttle": "hover throttle limit",
    "thrust_to_weight": "thrust-to-weight limit",
    "no_solution": "battery cannot supply the load",
    "none_below_cap": "no limit below the 100 kg search cap",
}


def rejection_text(code: str) -> str:
    return REJECTION_TEXT.get(code, code.replace("_", " "))


def limiting_text(code: str) -> str:
    return LIMITING_TEXT.get(code, code.replace("_", " "))


def f(value: float | None, digits: int = 1, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def metrics_for(r: BuildResult) -> list[tuple[str, str]]:
    """Label/value pairs summarising a result, in display order."""
    return [
        ("Flight time", f"{r.flight_time_min:.1f} min"),
        ("Total mass", f"{r.total_mass_kg * 1000:.0f} g"),
        ("Hover throttle", f"{r.hover_throttle:.0%}"),
        ("Hover power", f"{r.hover_battery_power_w:.0f} W"),
        ("Hover current", f"{r.hover_battery_current_a:.1f} A ({r.hover_c_rate:.1f}C)"),
        ("Hover RPM", f"{r.hover_rpm:.0f}"),
        ("Thrust-to-weight", f"{r.thrust_to_weight:.2f}"),
        ("Hover efficiency", f"{r.hover_efficiency_g_per_w:.1f} g/W"),
        ("Propeller FM", f"{r.figure_of_merit:.2f}"),
        ("Peak current", f"{r.peak_battery_current_a:.0f} A ({r.peak_c_rate:.1f}C)"),
        ("Pack voltage (hover)", f"{r.hover_pack_voltage_v:.1f} V"),
        ("Cost", f"${r.cost_usd:.0f}"),
    ]


def mass_parts(r: BuildResult) -> list[tuple[str, float]]:
    m = r.masses
    return [
        ("Frame", m.frame_kg * 1000),
        ("Motors", m.motors_kg * 1000),
        ("Props", m.props_kg * 1000),
        ("ESCs", m.escs_kg * 1000),
        ("Battery", m.battery_kg * 1000),
        ("Avionics", m.avionics_kg * 1000),
        ("Wiring", m.wiring_kg * 1000),
        ("Payload", m.payload_kg * 1000),
    ]
