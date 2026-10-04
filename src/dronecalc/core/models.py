"""Data models: components, mission, assumptions and constraints.

Component fields use hobbyist units (g, mAh, inch, A) as found on datasheets; derived SI
quantities are exposed as properties. All models validate themselves on construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from dronecalc.core.constants import G_TO_KG, IN_TO_M, TWO_PI
from dronecalc.core.environment import DEFAULT_BATTERY_TEMP_TABLE

SUPPORTED_ROTOR_COUNTS = (4, 6, 8)

# Nominal (mid-discharge) cell voltage per chemistry.
NOMINAL_CELL_V = {"lipo": 3.7, "liion": 3.6}

# Default cell internal resistance scaling, ohm*Ah per cell, used when a pack gives no value.
DEFAULT_CELL_RESISTANCE_OHM_AH = 0.020


def _positive(name: str, value: float) -> None:
    if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a positive number, got {value!r}")


def _non_negative(name: str, value: float) -> None:
    if not (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0):
        raise ValueError(f"{name} must be a non-negative number, got {value!r}")


@dataclass(frozen=True)
class Motor:
    id: str
    name: str
    kv_rpm_per_v: float
    resistance_ohm: float
    no_load_current_a: float
    mass_g: float
    max_current_a: float
    min_cells: int
    max_cells: int
    prop_min_in: float
    prop_max_in: float
    manufacturer: str = ""
    max_power_w: float | None = None
    price_usd: float = 0.0
    verified: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        for n in ("kv_rpm_per_v", "resistance_ohm", "mass_g", "max_current_a", "prop_min_in"):
            _positive(f"Motor {self.id}: {n}", getattr(self, n))
        _positive(f"Motor {self.id}: prop_max_in", self.prop_max_in)
        _non_negative(f"Motor {self.id}: no_load_current_a", self.no_load_current_a)
        _non_negative(f"Motor {self.id}: price_usd", self.price_usd)
        if self.max_power_w is not None:
            _positive(f"Motor {self.id}: max_power_w", self.max_power_w)
        if not (1 <= self.min_cells <= self.max_cells):
            raise ValueError(f"Motor {self.id}: need 1 <= min_cells <= max_cells")
        if self.prop_min_in > self.prop_max_in:
            raise ValueError(f"Motor {self.id}: prop_min_in > prop_max_in")

    @property
    def mass_kg(self) -> float:
        return self.mass_g * G_TO_KG

    @property
    def ke_v_s_per_rad(self) -> float:
        """Back-EMF constant; equals the torque constant Kt (N m / A) in SI."""
        return 60.0 / (TWO_PI * self.kv_rpm_per_v)


@dataclass(frozen=True)
class Propeller:
    id: str
    name: str
    diameter_in: float
    pitch_in: float
    ct: float
    cp: float
    mass_g: float
    blades: int = 2
    price_usd: float = 0.0
    verified: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        for n in ("diameter_in", "pitch_in", "ct", "cp", "mass_g"):
            _positive(f"Propeller {self.id}: {n}", getattr(self, n))
        _non_negative(f"Propeller {self.id}: price_usd", self.price_usd)
        if self.blades < 2:
            raise ValueError(f"Propeller {self.id}: blades must be >= 2")

    @property
    def diameter_m(self) -> float:
        return self.diameter_in * IN_TO_M

    @property
    def mass_kg(self) -> float:
        return self.mass_g * G_TO_KG

    @property
    def figure_of_merit(self) -> float:
        """Static hover figure of merit implied by the coefficients: Ct^1.5 / (sqrt(2) Cp)."""
        return self.ct**1.5 / (math.sqrt(2.0) * self.cp)


@dataclass(frozen=True)
class Battery:
    id: str
    name: str
    cells: int
    capacity_mah: float
    mass_g: float
    c_rate_cont: float
    chemistry: str = "lipo"
    c_rate_burst: float | None = None
    internal_resistance_mohm: float | None = None
    nominal_cell_v: float | None = None
    price_usd: float = 0.0
    verified: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        for n in ("capacity_mah", "mass_g", "c_rate_cont"):
            _positive(f"Battery {self.id}: {n}", getattr(self, n))
        if self.cells < 1:
            raise ValueError(f"Battery {self.id}: cells must be >= 1")
        if self.chemistry not in NOMINAL_CELL_V and self.nominal_cell_v is None:
            raise ValueError(
                f"Battery {self.id}: unknown chemistry {self.chemistry!r}; "
                f"use one of {sorted(NOMINAL_CELL_V)} or set nominal_cell_v"
            )
        for n in ("c_rate_burst", "internal_resistance_mohm", "nominal_cell_v"):
            if getattr(self, n) is not None:
                _positive(f"Battery {self.id}: {n}", getattr(self, n))
        _non_negative(f"Battery {self.id}: price_usd", self.price_usd)

    @property
    def capacity_ah(self) -> float:
        return self.capacity_mah / 1000.0

    @property
    def mass_kg(self) -> float:
        return self.mass_g * G_TO_KG

    @property
    def cell_nominal_v(self) -> float:
        return self.nominal_cell_v or NOMINAL_CELL_V[self.chemistry]

    @property
    def voltage_v(self) -> float:
        return self.cells * self.cell_nominal_v

    @property
    def energy_wh(self) -> float:
        return self.voltage_v * self.capacity_ah

    @property
    def specific_energy_wh_per_kg(self) -> float:
        return self.energy_wh / self.mass_kg

    @property
    def resistance_ohm(self) -> float:
        if self.internal_resistance_mohm is not None:
            return self.internal_resistance_mohm / 1000.0
        return DEFAULT_CELL_RESISTANCE_OHM_AH * self.cells / self.capacity_ah

    @property
    def resistance_ohm_ah_per_cell(self) -> float:
        """Capacity-normalised per-cell resistance, used to scale a continuous battery size."""
        return self.resistance_ohm * self.capacity_ah / self.cells

    @property
    def c_rate_burst_eff(self) -> float:
        """Burst C-rate; defaults to twice the continuous rating when the datasheet gives none."""
        return self.c_rate_burst if self.c_rate_burst is not None else 2.0 * self.c_rate_cont


@dataclass(frozen=True)
class ESC:
    id: str
    name: str
    max_current_a: float
    max_cells: int
    mass_g: float
    min_cells: int = 2
    efficiency: float | None = None
    price_usd: float = 0.0
    verified: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        _positive(f"ESC {self.id}: max_current_a", self.max_current_a)
        _positive(f"ESC {self.id}: mass_g", self.mass_g)
        _non_negative(f"ESC {self.id}: price_usd", self.price_usd)
        if not (1 <= self.min_cells <= self.max_cells):
            raise ValueError(f"ESC {self.id}: need 1 <= min_cells <= max_cells")
        if self.efficiency is not None and not (0.0 < self.efficiency <= 1.0):
            raise ValueError(f"ESC {self.id}: efficiency must be in (0, 1]")

    @property
    def mass_kg(self) -> float:
        return self.mass_g * G_TO_KG


@dataclass(frozen=True)
class Build:
    """A concrete configuration: N identical motor/prop/ESC sets, one battery, one frame."""

    motor: Motor
    prop: Propeller
    battery: Battery
    esc: ESC
    n_rotors: int
    frame_mass_kg: float

    def __post_init__(self) -> None:
        if self.n_rotors not in SUPPORTED_ROTOR_COUNTS:
            raise ValueError(f"n_rotors must be one of {SUPPORTED_ROTOR_COUNTS}")
        _positive("frame_mass_kg", self.frame_mass_kg)


@dataclass(frozen=True)
class Mission:
    target_flight_time_min: float
    payload_kg: float = 0.0
    altitude_m: float = 0.0
    temp_offset_c: float = 0.0
    n_rotors: int = 4
    max_mass_kg: float | None = None
    max_budget_usd: float | None = None
    payload_power_w: float = 0.0
    frame_mass_override_g: float | None = None

    def __post_init__(self) -> None:
        _positive("target_flight_time_min", self.target_flight_time_min)
        _non_negative("payload_kg", self.payload_kg)
        _non_negative("payload_power_w", self.payload_power_w)
        if self.n_rotors not in SUPPORTED_ROTOR_COUNTS:
            raise ValueError(f"n_rotors must be one of {SUPPORTED_ROTOR_COUNTS}")
        for n in ("max_mass_kg", "max_budget_usd", "frame_mass_override_g"):
            if getattr(self, n) is not None:
                _positive(n, getattr(self, n))


@dataclass(frozen=True)
class Assumptions:
    """Model assumptions, all explicit and overridable (project doc, section 3.3)."""

    depth_of_discharge: float = 0.80
    esc_efficiency: float = 0.95
    wiring_fraction: float = 0.05  # of dry mass (everything except payload)
    flight_time_derate: float = 0.10
    avionics_power_w: float = 5.0
    avionics_mass_g: float = 80.0
    prop_clearance: float = 0.10  # tip-to-tip gap between adjacent props, fraction of diameter
    battery_temp_table: tuple[tuple[float, float], ...] = DEFAULT_BATTERY_TEMP_TABLE
    fm_range: tuple[float, float] = (0.55, 0.75)
    # Mass-convergence loop (forward mode)
    mass_tolerance: float = 0.001
    relaxation: float = 0.5
    max_mass_iterations: int = 200
    fallback_specific_energy_wh_per_kg: float = 150.0

    def __post_init__(self) -> None:
        for n in ("depth_of_discharge", "esc_efficiency"):
            if not (0.0 < getattr(self, n) <= 1.0):
                raise ValueError(f"{n} must be in (0, 1]")
        if not (0.0 <= self.flight_time_derate < 1.0):
            raise ValueError("flight_time_derate must be in [0, 1)")
        if not (0.0 < self.relaxation <= 1.0):
            raise ValueError("relaxation must be in (0, 1]")
        _non_negative("wiring_fraction", self.wiring_fraction)
        _non_negative("avionics_power_w", self.avionics_power_w)
        _non_negative("avionics_mass_g", self.avionics_mass_g)
        _non_negative("prop_clearance", self.prop_clearance)
        _positive("mass_tolerance", self.mass_tolerance)
        _positive("fallback_specific_energy_wh_per_kg", self.fallback_specific_energy_wh_per_kg)


@dataclass(frozen=True)
class Constraints:
    """Hard feasibility limits. Defaults are typical hobbyist multirotor practice."""

    max_hover_throttle: float = 0.70
    min_thrust_to_weight: float = 2.0
    check_motor_power: bool = True
    check_battery_c_rate: bool = True

    def __post_init__(self) -> None:
        if not (0.0 < self.max_hover_throttle <= 1.0):
            raise ValueError("max_hover_throttle must be in (0, 1]")
        _positive("min_thrust_to_weight", self.min_thrust_to_weight)
