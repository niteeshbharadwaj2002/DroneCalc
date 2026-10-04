import pytest

from dronecalc.core import (
    Assumptions,
    Build,
    Constraints,
    Mission,
    atmosphere,
    estimate_frame_mass_kg,
    rank_builds,
    size_forward,
    size_reverse,
)
from dronecalc.core.feasibility import check_constraints
from dronecalc.core.sizing import SizingError, size_continuous_battery


@pytest.fixture(scope="module")
def mission():
    return Mission(target_flight_time_min=20, payload_kg=0.5, altitude_m=500)


@pytest.fixture(scope="module")
def forward(db, mission):
    return size_forward(mission, db, top_n=10)


def test_forward_returns_ranked_feasible_builds(forward, mission):
    assert forward.ranked and forward.n_feasible >= len(forward.ranked)
    times = [r.flight_time_min for r in forward.ranked]
    assert times == sorted(times, reverse=True)  # default scorer: flight time
    for r in forward.ranked:
        assert r.feasible
        assert r.flight_time_min >= mission.target_flight_time_min
        assert r.hover_throttle <= 0.70 and r.thrust_to_weight >= 2.0
        assert r.payload_kg == mission.payload_kg


def test_forward_builds_are_independently_valid(forward, mission):
    for r in forward.ranked:
        violations = check_constraints(
            r,
            Constraints(),
            max_mass_kg=mission.max_mass_kg,
            target_flight_time_min=mission.target_flight_time_min,
        )
        assert violations == []
        b = r.build
        assert b.motor.min_cells <= b.battery.cells <= b.motor.max_cells
        assert b.esc.min_cells <= b.battery.cells <= b.esc.max_cells
        assert b.motor.prop_min_in <= b.prop.diameter_in <= b.motor.prop_max_in
        assert b.esc.max_current_a >= b.motor.max_current_a


def test_forward_reports_rejection_reasons(forward):
    assert forward.n_candidates > 0
    assert forward.rejections  # at least some candidates are rejected with a reason


def test_mass_converges_within_tolerance(db, mission):
    motor = db.get("motors", "tmotor-mn3508-380")
    prop = db.get("props", "generic-13x4.4")
    esc = db.get("escs", "generic-esc-40a-6s")
    group = db.battery_groups()[("lipo", 6)]
    atm = atmosphere(mission.altitude_m)
    assumptions = Assumptions()
    frame = estimate_frame_mass_kg(prop.diameter_in, 4)
    cont = size_continuous_battery(motor, prop, esc, group, mission, atm, assumptions, frame)
    assert cont.iterations < assumptions.max_mass_iterations
    # Re-derive the required capacity at the converged mass: the mass residual is within tol.
    from dronecalc.core.sizing import _pseudo_battery

    se = db.group_specific_energy(group)
    batt = _pseudo_battery(group, 6, "lipo", cont.mass_kg, se)
    build = Build(motor, prop, batt, esc, 4, frame)
    from dronecalc.core.evaluate import solve_hover

    hover = solve_hover(build, mission.payload_kg, atm, assumptions)
    assert hover.masses.total_kg == pytest.approx(cont.total_mass_kg)
    from dronecalc.core.environment import battery_temp_factor

    usable = 0.8 * battery_temp_factor(atm.temperature_c) * 0.9
    needed_kg = hover.battery_current_a * (20 / 60) / usable * batt.voltage_v / se
    assert abs(needed_kg - cont.mass_kg) / hover.masses.total_kg < 0.001 * 1.1


def test_cannot_hover_is_reported(db):
    huge = Mission(target_flight_time_min=10, payload_kg=30.0)
    motor = db.get("motors", "emax-mt2213-935")
    prop = db.get("props", "generic-10x4.5")
    esc = db.get("escs", "generic-esc-20a-4s")
    group = db.battery_groups()[("lipo", 4)]
    with pytest.raises(SizingError):
        size_continuous_battery(motor, prop, esc, group, huge, atmosphere(0), Assumptions(), 0.3)


def test_impossible_mission_returns_empty_with_reasons(db):
    res = size_forward(Mission(target_flight_time_min=240, payload_kg=20.0), db)
    assert res.ranked == [] and res.n_feasible == 0
    assert res.rejections


def test_max_mass_and_budget_are_enforced(db):
    capped = size_forward(
        Mission(target_flight_time_min=15, payload_kg=0.3, max_mass_kg=2.0, max_budget_usd=400), db
    )
    for r in capped.ranked:
        assert r.total_mass_kg <= 2.0 and r.cost_usd <= 400


def test_hexacopter_is_supported(db):
    res = size_forward(Mission(target_flight_time_min=15, payload_kg=0.5, n_rotors=6), db)
    assert res.ranked and all(r.build.n_rotors == 6 for r in res.ranked)


def test_pluggable_scorer(db, mission):
    by_cost = size_forward(mission, db, scorer="cheapest", top_n=5)
    costs = [r.cost_usd for r in by_cost.ranked]
    assert costs == sorted(costs)
    custom = size_forward(mission, db, scorer=lambda r: -r.hover_battery_power_w, top_n=5)
    powers = [r.hover_battery_power_w for r in custom.ranked]
    assert powers == sorted(powers)
    assert rank_builds([], "flight_time") == []
    with pytest.raises(ValueError, match="unknown scorer"):
        rank_builds([], "nonsense")


def test_cold_high_altitude_mission_is_harder(db):
    easy = size_forward(Mission(target_flight_time_min=20, payload_kg=0.5), db)
    hard = size_forward(
        Mission(target_flight_time_min=20, payload_kg=0.5, altitude_m=3500, temp_offset_c=-20), db
    )
    assert hard.n_feasible <= easy.n_feasible
    assert hard.atmosphere.density < easy.atmosphere.density


# ---- reverse mode ------------------------------------------------------------------------


def test_reverse_max_payload_sits_on_the_limit(small_build):
    rev = size_reverse(small_build, payload_kg=0.1)
    assert rev.can_fly_empty and rev.max_payload_kg > 0.1
    assert rev.limiting_factor in ("hover_throttle", "thrust_to_weight")

    atm, assumptions, constraints = atmosphere(0), Assumptions(), Constraints()
    from dronecalc.core import assess_build

    ok = assess_build(small_build, rev.max_payload_kg - 1e-4, atm, assumptions, constraints)
    over = assess_build(small_build, rev.max_payload_kg + 1e-3, atm, assumptions, constraints)
    codes_ok = {v.code for v in ok.violations} & {"hover_throttle", "thrust_to_weight"}
    codes_over = {v.code for v in over.violations} & {"hover_throttle", "thrust_to_weight"}
    assert not codes_ok and codes_over
    assert rev.limiting_factor in codes_over


def test_reverse_payload_falls_with_altitude_and_heat_when_voltage_limited(db):
    prop = db.get("props", "generic-8x4.5")
    build = Build(
        db.get("motors", "sunnysky-x2212-980"),
        prop,
        db.get("batteries", "lipo-3s-2200"),
        db.get("escs", "generic-esc-30a-4s"),
        4,
        estimate_frame_mass_kg(prop.diameter_in, 4),
    )
    sea = size_reverse(build)
    assert sea.result.peak_limited_by == "voltage"
    assert size_reverse(build, altitude_m=3000).max_payload_kg < sea.max_payload_kg
    assert size_reverse(build, temp_offset_c=25).max_payload_kg < sea.max_payload_kg


def test_current_limited_build_is_density_independent_but_loses_endurance(small_build):
    """At the current limit thrust = (Ct/Cp) 2 pi Q / D, independent of density; the
    penalty of thin air shows up in hover throttle and flight time instead."""
    sea = size_reverse(small_build, payload_kg=0.2)
    high = size_reverse(small_build, payload_kg=0.2, altitude_m=3000)
    assert sea.result.peak_limited_by == "current"
    assert high.max_payload_kg == pytest.approx(sea.max_payload_kg, rel=1e-6)
    assert high.result.hover_throttle > sea.result.hover_throttle
    assert high.result.flight_time_min < sea.result.flight_time_min


def test_reverse_flight_time_falls_with_payload(small_build):
    t0 = size_reverse(small_build, payload_kg=0.0).result.flight_time_min
    t1 = size_reverse(small_build, payload_kg=0.4).result.flight_time_min
    assert t1 < t0


def test_forward_to_reverse_round_trip(forward, mission):
    top = forward.ranked[0]
    rev = size_reverse(top.build, payload_kg=mission.payload_kg, altitude_m=mission.altitude_m)
    assert rev.result.flight_time_min == pytest.approx(top.flight_time_min)
    assert rev.result.total_mass_kg == pytest.approx(top.total_mass_kg)
    assert rev.max_payload_kg >= mission.payload_kg  # the build was sized to carry it


def test_reverse_build_that_cannot_fly_empty(db):
    prop = db.get("props", "generic-8x4.5")
    build = Build(
        db.get("motors", "emax-mt2213-935"),
        prop,
        db.get("batteries", "lipo-4s-10000"),
        db.get("escs", "generic-esc-20a-4s"),
        4,
        2.0,  # a very heavy frame
    )
    rev = size_reverse(build)
    assert not rev.can_fly_empty and rev.max_payload_kg == 0.0
