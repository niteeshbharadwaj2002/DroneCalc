"""ISA atmosphere with temperature offset, density altitude, and battery cold derating."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from dronecalc.core.constants import (
    H_MAX_M,
    H_MIN_M,
    H_TROPOPAUSE_M,
    LAPSE_K_PER_M,
    P0_PA,
    R_AIR,
    T0_K,
    G,
)

# (temperature degC, usable-capacity fraction). Linear interpolation, clamped at the ends.
# Conservative hobbyist-grade values for LiPo/Li-ion; override through Assumptions.
DEFAULT_BATTERY_TEMP_TABLE: tuple[tuple[float, float], ...] = (
    (-20.0, 0.65),
    (-10.0, 0.78),
    (0.0, 0.88),
    (10.0, 0.95),
    (20.0, 1.00),
)

_T_TROPOPAUSE_K = T0_K - LAPSE_K_PER_M * H_TROPOPAUSE_M


def _check_altitude(h_m: float) -> None:
    if not (H_MIN_M <= h_m <= H_MAX_M):
        raise ValueError(f"altitude {h_m} m outside supported range [{H_MIN_M}, {H_MAX_M}] m")


def isa_temperature_k(h_m: float) -> float:
    _check_altitude(h_m)
    if h_m <= H_TROPOPAUSE_M:
        return T0_K - LAPSE_K_PER_M * h_m
    return _T_TROPOPAUSE_K


def isa_pressure_pa(h_m: float) -> float:
    _check_altitude(h_m)
    if h_m <= H_TROPOPAUSE_M:
        return P0_PA * (isa_temperature_k(h_m) / T0_K) ** (G / (R_AIR * LAPSE_K_PER_M))
    p11 = isa_pressure_pa(H_TROPOPAUSE_M)
    return p11 * math.exp(-G * (h_m - H_TROPOPAUSE_M) / (R_AIR * _T_TROPOPAUSE_K))


def isa_density(h_m: float) -> float:
    return isa_pressure_pa(h_m) / (R_AIR * isa_temperature_k(h_m))


def density_altitude_m(rho: float) -> float:
    """Altitude at which the ISA density equals ``rho`` (bisection; density falls with height)."""
    lo, hi = H_MIN_M, H_MAX_M
    if not (isa_density(hi) <= rho <= isa_density(lo)):
        raise ValueError(f"density {rho} kg/m^3 outside the ISA range")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if isa_density(mid) > rho:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class Atmosphere:
    altitude_m: float
    temp_offset_c: float
    temperature_k: float
    pressure_pa: float
    density: float
    density_altitude_m: float

    @property
    def temperature_c(self) -> float:
        return self.temperature_k - 273.15


def atmosphere(altitude_m: float = 0.0, temp_offset_c: float = 0.0) -> Atmosphere:
    """ISA pressure at ``altitude_m`` with the temperature shifted by ``temp_offset_c`` (ISA+dT)."""
    temperature = isa_temperature_k(altitude_m) + temp_offset_c
    if temperature <= 0.0:
        raise ValueError("temperature offset gives a non-physical absolute temperature")
    pressure = isa_pressure_pa(altitude_m)
    rho = pressure / (R_AIR * temperature)
    return Atmosphere(
        altitude_m=altitude_m,
        temp_offset_c=temp_offset_c,
        temperature_k=temperature,
        pressure_pa=pressure,
        density=rho,
        density_altitude_m=density_altitude_m(rho),
    )


def battery_temp_factor(
    temp_c: float, table: Sequence[tuple[float, float]] = DEFAULT_BATTERY_TEMP_TABLE
) -> float:
    """Usable-capacity fraction at ``temp_c`` (battery assumed at ambient temperature)."""
    pts = sorted(table)
    if temp_c <= pts[0][0]:
        return pts[0][1]
    if temp_c >= pts[-1][0]:
        return pts[-1][1]
    for (t0, f0), (t1, f1) in zip(pts, pts[1:]):
        if t0 <= temp_c <= t1:
            return f0 + (f1 - f0) * (temp_c - t0) / (t1 - t0)
    raise AssertionError("unreachable")  # pragma: no cover
