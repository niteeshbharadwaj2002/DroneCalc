"""Physics sanity tests (project doc, section 3.6.4): scaling laws and plausibility ranges."""

import pytest

from dronecalc.core import atmosphere, battery_temp_factor, evaluate_build
from dronecalc.core.constants import G
from dronecalc.core.evaluate import flight_time_min, solve_hover
from dronecalc.core.propulsion import prop_power_w, prop_speed_rps


def test_shaft_power_scales_with_inverse_sqrt_density(db):
    prop = db.get("props", "generic-12x4.5")
    thrust = 10.0
    p = []
    for rho in (1.225, 1.225 / 4):
        n = prop_speed_rps(prop, thrust, rho)
        p.append(prop_power_w(prop, n, rho))
    assert p[1] / p[0] == pytest.approx(2.0, rel=1e-9)  # P ~ rho^-1/2


def test_hover_power_scales_with_mass_to_the_three_halves(db):
    prop = db.get("props", "generic-12x4.5")
    rho = 1.225
    powers = []
    for thrust in (5.0, 10.0):
        n = prop_speed_rps(prop, thrust, rho)
        powers.append(prop_power_w(prop, n, rho))
    assert powers[1] / powers[0] == pytest.approx(2**1.5, rel=1e-9)  # P ~ T^3/2


def test_high_altitude_costs_power_and_time(small_build, assumptions):
    sea = solve_hover(small_build, 0.2, atmosphere(0), assumptions)
    high = solve_hover(small_build, 0.2, atmosphere(3000), assumptions)
    assert high.battery_power_w > sea.battery_power_w
    assert high.throttle > sea.throttle


def test_hot_day_costs_power(small_build, assumptions):
    std = solve_hover(small_build, 0.2, atmosphere(0, 0), assumptions)
    hot = solve_hover(small_build, 0.2, atmosphere(0, 25), assumptions)
    assert hot.battery_power_w > std.battery_power_w


def test_cold_weather_derates_flight_time(assumptions):
    warm = flight_time_min(5.0, 20.0, atmosphere(0, 5), assumptions)
    cold = flight_time_min(5.0, 20.0, atmosphere(0, -25), assumptions)
    assert cold < warm
    ratio = battery_temp_factor(atmosphere(0, -25).temperature_c) / battery_temp_factor(
        atmosphere(0, 5).temperature_c
    )
    assert cold / warm == pytest.approx(ratio)


def test_flight_time_formula(assumptions):
    atm = atmosphere(0, 5)  # 20 C -> factor 1.0
    t = flight_time_min(5.0, 20.0, atm, assumptions)
    assert t == pytest.approx(60 * 5.0 * 0.80 * 1.0 * 0.90 / 20.0)


def test_figure_of_merit_range_for_seed_props(db):
    for prop in db.props.values():
        assert 0.55 <= prop.figure_of_merit <= 0.75


def test_result_internal_consistency(small_build, assumptions, constraints):
    atm = atmosphere(500)
    r = evaluate_build(small_build, 0.3, atm, assumptions)
    assert r.thrust_per_rotor_n * 4 == pytest.approx(r.total_mass_kg * G)
    assert r.hover_battery_power_w == pytest.approx(
        r.hover_battery_current_a * r.hover_pack_voltage_v
    )
    assert r.hover_efficiency_g_per_w == pytest.approx(
        r.total_mass_kg * 1000 / r.hover_battery_power_w
    )
    assert r.hover_pack_voltage_v < small_build.battery.voltage_v
    assert r.hover_shaft_power_w < r.hover_battery_power_w
    assert r.masses.wiring_kg == pytest.approx(0.05 * r.masses.dry_kg)
    assert r.to_dict()["label"] == "predicted, unverified"


def test_heavier_payload_needs_more_power(small_build, assumptions):
    atm = atmosphere(0)
    light = solve_hover(small_build, 0.0, atm, assumptions)
    heavy = solve_hover(small_build, 0.5, atm, assumptions)
    assert heavy.battery_power_w > light.battery_power_w
    assert heavy.masses.total_kg - light.masses.total_kg == pytest.approx(0.5)
