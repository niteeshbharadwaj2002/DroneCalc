import math

import pytest

from dronecalc.core.constants import TWO_PI, G
from dronecalc.core.propulsion import (
    SolveError,
    max_thrust_point,
    motor_point_at_speed,
    motor_point_for_thrust,
    prop_power_w,
    prop_speed_rps,
    prop_thrust_n,
    solve_pack,
    speed_for_current,
    speed_for_voltage,
)

RHO = 1.225


def test_prop_speed_inverts_thrust(db):
    prop = db.get("props", "generic-10x4.5")
    n = prop_speed_rps(prop, 8.0, RHO)
    assert prop_thrust_n(prop, n, RHO) == pytest.approx(8.0)


def test_prop_power_matches_formula(db):
    prop = db.get("props", "generic-10x4.5")
    n = 120.0
    assert prop_power_w(prop, n, RHO) == pytest.approx(prop.cp * RHO * n**3 * (0.254) ** 5)


def test_motor_energy_balance(db):
    """V*I = shaft power + I0 back-EMF power + copper loss (exact for this model)."""
    motor = db.get("motors", "sunnysky-x2212-980")
    prop = db.get("props", "generic-10x4.5")
    mp = motor_point_for_thrust(motor, prop, 7.0, RHO)
    ke = motor.ke_v_s_per_rad
    omega = TWO_PI * mp.n_rps
    losses = ke * omega * motor.no_load_current_a + mp.current_a**2 * motor.resistance_ohm
    assert mp.electrical_power_w == pytest.approx(mp.shaft_power_w + losses, rel=1e-9)
    assert 0.0 < mp.efficiency < 1.0


def test_motor_kv_consistency(db):
    """Unloaded (rho -> 0): speed = Kv * (V - Rm * I0), i.e. Kv * V less the no-load IR drop."""
    motor = db.get("motors", "sunnysky-x2212-980")
    prop = db.get("props", "generic-10x4.5")
    n = speed_for_voltage(motor, prop, 1e-9, 11.1)
    expected = motor.kv_rpm_per_v * (11.1 - motor.resistance_ohm * motor.no_load_current_a)
    assert n * 60 == pytest.approx(expected, rel=1e-6)


def test_closed_form_speeds_are_exact_inverses(db):
    motor = db.get("motors", "tmotor-mn3508-380")
    prop = db.get("props", "generic-13x4.4")
    n_v = speed_for_voltage(motor, prop, RHO, 22.2)
    assert motor_point_at_speed(motor, prop, n_v, RHO).voltage_v == pytest.approx(22.2)
    n_i = speed_for_current(motor, prop, RHO, 15.0)
    assert motor_point_at_speed(motor, prop, n_i, RHO).current_a == pytest.approx(15.0)
    assert speed_for_current(motor, prop, RHO, motor.no_load_current_a) == 0.0


def test_solve_pack_matches_quadratic():
    p, voc, r = 300.0, 22.2, 0.02
    i, v = solve_pack(p, voc, r)
    # Exact: R I^2 - Voc I + P = 0, smaller root
    exact = (voc - math.sqrt(voc**2 - 4 * r * p)) / (2 * r)
    assert i == pytest.approx(exact, rel=1e-8)
    assert v == pytest.approx(voc - exact * r, rel=1e-8)
    assert i * v == pytest.approx(p, rel=1e-8)


def test_solve_pack_zero_resistance_and_overload():
    i, v = solve_pack(100.0, 10.0, 0.0)
    assert (i, v) == (pytest.approx(10.0), pytest.approx(10.0))
    with pytest.raises(SolveError):
        solve_pack(1e5, 10.0, 0.05)  # beyond the maximum power transfer


def test_max_thrust_respects_current_limit(db):
    motor = db.get("motors", "sunnysky-x2212-980")
    prop = db.get("props", "generic-10x4.5")
    esc = db.get("escs", "generic-esc-20a-4s")
    battery = db.get("batteries", "lipo-4s-5000")
    pt = max_thrust_point(motor, prop, esc, battery, RHO, 4, 0.95)
    assert pt.motor_current_a <= min(motor.max_current_a, esc.max_current_a) + 1e-9
    assert pt.limited_by == "current"
    assert pt.pack_voltage_v < battery.voltage_v  # sag


def test_max_thrust_voltage_limited_with_small_prop(db):
    motor = db.get("motors", "sunnysky-x2212-980")
    prop = db.get("props", "generic-8x4.5")
    esc = db.get("escs", "generic-esc-30a-4s")
    battery = db.get("batteries", "lipo-3s-2200")
    pt = max_thrust_point(motor, prop, esc, battery, RHO, 4, 0.95)
    assert pt.limited_by == "voltage"
    assert pt.motor_voltage_v == pytest.approx(pt.pack_voltage_v, rel=1e-6)
    assert pt.thrust_per_rotor_n > 0


def test_hover_thrust_weight_balance(db):
    motor = db.get("motors", "sunnysky-x2212-980")
    prop = db.get("props", "generic-10x4.5")
    mass, n = 1.2, 4
    mp = motor_point_for_thrust(motor, prop, mass * G / n, RHO)
    assert n * mp.thrust_n == pytest.approx(mass * G)
