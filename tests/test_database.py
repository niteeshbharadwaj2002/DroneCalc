import json

import pytest

from dronecalc.core import Battery, Database, DatabaseError, Motor, Propeller


def test_seed_loads(db):
    assert len(db.motors) >= 5 and len(db.props) >= 8
    assert len(db.batteries) >= 20 and len(db.escs) >= 4


def test_seed_props_have_plausible_figure_of_merit(db):
    for prop in db.props.values():
        assert 0.55 <= prop.figure_of_merit <= 0.75, prop.id


def test_seed_is_flagged_unverified(db):
    assert all(not m.verified for m in db.motors.values())
    assert any("verified=false" in w for w in db.check())


def test_battery_groups_sorted_and_consistent(db):
    for (chemistry, cells), packs in db.battery_groups().items():
        assert all(p.chemistry == chemistry and p.cells == cells for p in packs)
        caps = [p.capacity_mah for p in packs]
        assert caps == sorted(caps)


def test_battery_derived_properties():
    b = Battery("b", "b", cells=4, capacity_mah=5000, mass_g=450, c_rate_cont=25)
    assert b.voltage_v == pytest.approx(14.8)
    assert b.energy_wh == pytest.approx(74.0)
    assert b.c_rate_burst_eff == 50
    assert b.resistance_ohm == pytest.approx(0.020 * 4 / 5.0)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Motor("m", "m", -1, 0.1, 0.5, 50, 15, 2, 4, 8, 10),
        lambda: Motor("m", "m", 900, 0.1, 0.5, 50, 15, 5, 4, 8, 10),
        lambda: Propeller("p", "p", 10, 4.5, 0.1, 0.0, 10),
        lambda: Battery("b", "b", 0, 5000, 400, 25),
        lambda: Battery("b", "b", 3, 5000, 400, 25, chemistry="mystery"),
    ],
)
def test_models_reject_invalid_values(factory):
    with pytest.raises(ValueError):
        factory()


def test_unknown_field_and_missing_field_errors(tmp_path):
    (tmp_path / "escs.json").write_text(json.dumps([{"id": "e", "name": "e", "oops": 1}]))
    with pytest.raises(DatabaseError, match="unknown field"):
        Database.load(seed_dir=tmp_path, custom_dir=tmp_path / "none")
    (tmp_path / "escs.json").write_text(json.dumps([{"id": "e", "name": "e"}]))
    with pytest.raises(DatabaseError):
        Database.load(seed_dir=tmp_path, custom_dir=tmp_path / "none")


def test_invalid_json_and_duplicate_ids(tmp_path):
    (tmp_path / "escs.json").write_text("{not json")
    with pytest.raises(DatabaseError, match="invalid JSON"):
        Database.load(seed_dir=tmp_path, custom_dir=tmp_path / "none")
    esc = {"id": "e", "name": "e", "max_current_a": 20, "max_cells": 4, "mass_g": 20}
    (tmp_path / "escs.json").write_text(json.dumps([esc, esc]))
    with pytest.raises(DatabaseError, match="duplicate"):
        Database.load(seed_dir=tmp_path, custom_dir=tmp_path / "none")


def test_custom_entry_persists_and_overrides(tmp_path):
    seed = Database.load(include_custom=False)
    entry = {
        "id": "sunnysky-x2212-980",
        "name": "custom override",
        "kv_rpm_per_v": 1000,
        "resistance_ohm": 0.1,
        "no_load_current_a": 0.4,
        "mass_g": 60,
        "max_current_a": 15,
        "min_cells": 2,
        "max_cells": 4,
        "prop_min_in": 8,
        "prop_max_in": 10,
    }
    seed.add_custom("motors", entry, custom_dir=tmp_path)
    assert seed.motors["sunnysky-x2212-980"].name == "custom override"

    reloaded = Database.load(custom_dir=tmp_path)
    assert reloaded.motors["sunnysky-x2212-980"].kv_rpm_per_v == 1000
    assert any("overrides seed" in w for w in reloaded.load_warnings)
    assert "sunnysky-x2212-980" in reloaded.custom_ids["motors"]


def test_add_custom_rejects_bad_entry(tmp_path):
    db = Database()
    with pytest.raises(DatabaseError):
        db.add_custom("motors", {"id": "x"}, custom_dir=tmp_path)
    with pytest.raises(DatabaseError):
        db.add_custom("rockets", {}, custom_dir=tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_get_unknown_id(db):
    with pytest.raises(KeyError, match="no motors entry"):
        db.get("motors", "nope")
