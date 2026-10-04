"""Propeller, motor and battery-pack physics for a single operating point.

Propeller:  T = Ct rho n^2 D^4,  P = Cp rho n^3 D^5   (n in rev/s, SI units)
Motor:      Ke = Kt = 60 / (2 pi Kv),  I = Q / Kt + I0,  V = Ke w + I Rm
Pack:       V_loaded = V_oc - I_bat R_pack, solved by fixed-point iteration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from dronecalc.core.constants import TWO_PI
from dronecalc.core.models import ESC, Battery, Motor, Propeller


class SolveError(RuntimeError):
    """The operating point has no solution (e.g. the pack cannot deliver the power)."""


# ---- propeller -----------------------------------------------------------------------------


def prop_speed_rps(prop: Propeller, thrust_n: float, rho: float) -> float:
    return math.sqrt(thrust_n / (prop.ct * rho * prop.diameter_m**4))


def prop_thrust_n(prop: Propeller, n_rps: float, rho: float) -> float:
    return prop.ct * rho * n_rps**2 * prop.diameter_m**4


def prop_power_w(prop: Propeller, n_rps: float, rho: float) -> float:
    return prop.cp * rho * n_rps**3 * prop.diameter_m**5


def prop_torque_nm(prop: Propeller, n_rps: float, rho: float) -> float:
    return prop.cp * rho * n_rps**2 * prop.diameter_m**5 / TWO_PI


# ---- motor ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MotorPoint:
    n_rps: float
    thrust_n: float
    shaft_power_w: float
    torque_nm: float
    current_a: float
    voltage_v: float  # voltage across the motor terminals (after the ESC)

    @property
    def rpm(self) -> float:
        return self.n_rps * 60.0

    @property
    def electrical_power_w(self) -> float:
        return self.voltage_v * self.current_a

    @property
    def efficiency(self) -> float:
        return self.shaft_power_w / self.electrical_power_w


def motor_point_at_speed(motor: Motor, prop: Propeller, n_rps: float, rho: float) -> MotorPoint:
    torque = prop_torque_nm(prop, n_rps, rho)
    ke = motor.ke_v_s_per_rad
    current = torque / ke + motor.no_load_current_a
    voltage = ke * TWO_PI * n_rps + current * motor.resistance_ohm
    return MotorPoint(
        n_rps=n_rps,
        thrust_n=prop_thrust_n(prop, n_rps, rho),
        shaft_power_w=prop_power_w(prop, n_rps, rho),
        torque_nm=torque,
        current_a=current,
        voltage_v=voltage,
    )


def motor_point_for_thrust(
    motor: Motor, prop: Propeller, thrust_n: float, rho: float
) -> MotorPoint:
    return motor_point_at_speed(motor, prop, prop_speed_rps(prop, thrust_n, rho), rho)


def speed_for_voltage(motor: Motor, prop: Propeller, rho: float, voltage_v: float) -> float:
    """Prop speed (rev/s) at which the motor terminal voltage equals ``voltage_v`` (closed form)."""
    ke = motor.ke_v_s_per_rad
    a = motor.resistance_ohm * prop.cp * rho * prop.diameter_m**5 / (TWO_PI * ke)
    b = ke * TWO_PI
    c = motor.resistance_ohm * motor.no_load_current_a - voltage_v
    disc = b * b - 4.0 * a * c
    return (-b + math.sqrt(disc)) / (2.0 * a)


def speed_for_current(motor: Motor, prop: Propeller, rho: float, current_a: float) -> float:
    """Prop speed (rev/s) at which the motor current equals ``current_a``."""
    if current_a <= motor.no_load_current_a:
        return 0.0
    ke = motor.ke_v_s_per_rad
    q = (current_a - motor.no_load_current_a) * ke
    return math.sqrt(q * TWO_PI / (prop.cp * rho * prop.diameter_m**5))


# ---- battery pack --------------------------------------------------------------------------


def solve_pack(
    power_w: float,
    v_oc: float,
    r_pack: float,
    tol: float = 1e-10,
    max_iter: int = 500,
) -> tuple[float, float]:
    """Battery current and loaded voltage for a constant-power load.

    Fixed-point iteration ``I <- P / (V_oc - I R)``. It converges while the pack sag stays below
    half of ``V_oc``; otherwise the load is beyond what the pack can deliver and ``SolveError``
    is raised.
    """
    if power_w < 0:
        raise ValueError("power must be non-negative")
    current = power_w / v_oc
    for _ in range(max_iter):
        v_loaded = v_oc - current * r_pack
        if v_loaded <= 0.0:
            raise SolveError("battery voltage collapses under load")
        new_current = power_w / v_loaded
        if abs(new_current - current) <= tol * max(1.0, current):
            return new_current, v_oc - new_current * r_pack
        current = new_current
    raise SolveError("battery loaded-voltage iteration did not converge")


@dataclass(frozen=True)
class MaxThrustPoint:
    thrust_per_rotor_n: float
    n_rps: float
    motor_current_a: float
    motor_voltage_v: float
    battery_current_a: float
    pack_voltage_v: float
    limited_by: str  # "voltage" (full throttle) or "current" (motor/ESC current limit)


def max_thrust_point(
    motor: Motor,
    prop: Propeller,
    esc: ESC,
    battery: Battery,
    rho: float,
    n_rotors: int,
    esc_efficiency: float,
    aux_power_w: float = 0.0,
    tol: float = 1e-9,
    max_iter: int = 500,
) -> MaxThrustPoint:
    """Thrust per rotor at full throttle with pack sag, capped by the motor and ESC current.

    The pack voltage depends on the battery current, which depends on the speed reached at that
    voltage, so the loaded voltage is found with a damped fixed-point iteration.
    """
    v_oc = battery.voltage_v
    r_pack = battery.resistance_ohm
    i_limit = min(motor.max_current_a, esc.max_current_a)
    n_current = speed_for_current(motor, prop, rho, i_limit)

    v_pack = v_oc
    for _ in range(max_iter):
        n_voltage = speed_for_voltage(motor, prop, rho, v_pack)
        n_rps = min(n_voltage, n_current)
        pt = motor_point_at_speed(motor, prop, n_rps, rho)
        p_bat = n_rotors * pt.electrical_power_w / esc_efficiency + aux_power_w
        i_bat = p_bat / v_pack
        v_new = v_oc - i_bat * r_pack
        if v_new <= 0.0:
            raise SolveError("battery voltage collapses at full throttle")
        if abs(v_new - v_pack) <= tol * v_oc:
            return MaxThrustPoint(
                thrust_per_rotor_n=pt.thrust_n,
                n_rps=n_rps,
                motor_current_a=pt.current_a,
                motor_voltage_v=pt.voltage_v,
                battery_current_a=i_bat,
                pack_voltage_v=v_pack,
                limited_by="current" if n_current < n_voltage else "voltage",
            )
        v_pack = 0.5 * (v_pack + v_new)
    raise SolveError("full-throttle pack-voltage iteration did not converge")
