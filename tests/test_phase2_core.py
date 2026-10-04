"""Tests for the Phase 2 additive core API: filters, progress/cancel, serialization, sweeps,
CSV export, project files, custom-entry deletion and the no-Qt rule."""

import ast
import csv
import io
import json
from pathlib import Path

import pytest

import dronecalc.core as core
from dronecalc.core import (
    Assumptions,
    Build,
    Constraints,
    Database,
    DatabaseError,
    Mission,
    Project,
    ProjectError,
    SizingCancelled,
    assumptions_from_dict,
    assumptions_to_dict,
    build_from_dict,
    build_to_dict,
    load_project,
    mission_from_dict,
    mission_to_dict,
    save_project,
    size_forward,
    size_reverse,
    sweep_altitude,
    sweep_payload,
    write_results_csv,
)
from dronecalc.core.export import COLUMNS

MISSION = Mission(target_flight_time_min=15, payload_kg=0.5)


def test_api_version_bumped():
    assert core.API_VERSION == "1.1"


# ---- forward filters, progress, cancel -----------------------------------------------------


def test_allow_none_matches_unfiltered(db):
    a = size_forward(MISSION, db, top_n=50)
    b = size_forward(MISSION, db, top_n=50, allow={"motors": None, "props": None})
    assert [r.build.motor.id for r in a.ranked] == [r.build.motor.id for r in b.ranked]
    assert a.n_feasible == b.n_feasible


def test_allow_restricts_components(db):
    res = size_forward(
        MISSION,
        db,
        top_n=50,
        allow={"motors": ["tmotor-mn4006-380"], "props": ["generic-15x5.0"]},
    )
    assert res.ranked
    assert {r.build.motor.id for r in res.ranked} == {"tmotor-mn4006-380"}
    assert {r.build.prop.id for r in res.ranked} == {"generic-15x5.0"}


def test_allow_battery_and_esc_filters(db):
    res = size_forward(
        MISSION,
        db,
        top_n=50,
        allow={"batteries": ["liion-6s4p-16000"], "escs": ["generic-esc-60a-6s"]},
    )
    assert res.ranked
    assert {r.build.battery.id for r in res.ranked} == {"liion-6s4p-16000"}
    assert {r.build.esc.id for r in res.ranked} == {"generic-esc-60a-6s"}


def test_empty_allow_gives_no_candidates(db):
    res = size_forward(MISSION, db, allow={"motors": []})
    assert res.ranked == [] and res.n_candidates == 0


def test_progress_reports_monotonically_to_total(db):
    calls = []
    size_forward(MISSION, db, progress=lambda d, t: calls.append((d, t)))
    assert calls and calls[-1][0] == calls[-1][1]
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)
    assert len({t for _, t in calls}) == 1


def test_cancel_raises(db):
    with pytest.raises(SizingCancelled):
        size_forward(MISSION, db, cancel=lambda: True)


# ---- serialization -------------------------------------------------------------------------


def test_mission_round_trip():
    m = Mission(
        target_flight_time_min=22,
        payload_kg=1.2,
        altitude_m=1500,
        temp_offset_c=-10,
        n_rotors=6,
        max_mass_kg=8,
        max_budget_usd=900,
        payload_power_w=12,
        frame_mass_override_g=700,
    )
    assert mission_from_dict(json.loads(json.dumps(mission_to_dict(m)))) == m


def test_assumptions_round_trip_through_json():
    a = Assumptions(depth_of_discharge=0.7, avionics_power_w=9.0, fm_range=(0.5, 0.8))
    back = assumptions_from_dict(json.loads(json.dumps(assumptions_to_dict(a))))
    assert back == a
    assert isinstance(back.battery_temp_table, tuple)
    assert isinstance(back.battery_temp_table[0], tuple)


def test_unknown_field_rejected():
    with pytest.raises(ValueError, match="unknown field"):
        mission_from_dict({"target_flight_time_min": 10, "bogus": 1})


def test_build_round_trip(small_build, db):
    assert build_from_dict(db, build_to_dict(small_build)) == small_build


def test_build_from_dict_unknown_component(db, small_build):
    d = build_to_dict(small_build)
    d["motor"] = "nope"
    with pytest.raises(ValueError, match="cannot restore build"):
        build_from_dict(db, d)


# ---- sweeps --------------------------------------------------------------------------------


def test_sweep_payload_matches_direct_evaluation(small_build):
    pts = sweep_payload(small_build, [0.0, 0.5, 1.0], altitude_m=500)
    rev = size_reverse(small_build, payload_kg=0.5, altitude_m=500)
    assert pts[1].flight_time_min == pytest.approx(rev.result.flight_time_min)
    assert pts[0].flight_time_min > pts[1].flight_time_min > pts[2].flight_time_min
    assert pts[0].total_mass_kg < pts[2].total_mass_kg


def test_sweep_payload_flags_limits(small_build):
    pts = sweep_payload(small_build, [0.0, 50.0])
    assert pts[0].within_limits
    assert not pts[1].within_limits or pts[1].flight_time_min is None


def test_sweep_altitude_density_effect(small_build):
    pts = sweep_altitude(small_build, [0, 2000, 4000], payload_kg=0.2)
    assert pts[0].hover_power_w < pts[1].hover_power_w < pts[2].hover_power_w


# ---- CSV export ----------------------------------------------------------------------------


def test_csv_export_rows_match_results(db):
    res = size_forward(MISSION, db, top_n=5)
    buf = io.StringIO()
    n = write_results_csv(res.ranked, buf)
    assert n == len(res.ranked) == 5
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert list(rows[0].keys()) == COLUMNS
    assert rows[0]["motor"] == res.ranked[0].build.motor.id
    assert float(rows[0]["flight_time_min"]) == pytest.approx(
        res.ranked[0].flight_time_min, abs=0.01
    )
    assert rows[0]["label"] == "predicted, unverified"


def test_csv_export_to_path(db, tmp_path):
    res = size_forward(MISSION, db, top_n=3)
    out = tmp_path / "r.csv"
    assert write_results_csv(res.ranked, out) == 3
    assert out.read_text().splitlines()[0].startswith("rank,motor")


# ---- project files -------------------------------------------------------------------------


def test_project_round_trip(tmp_path, small_build):
    proj = Project(
        mission=Mission(target_flight_time_min=18, payload_kg=0.7, altitude_m=900),
        assumptions=Assumptions(flight_time_derate=0.2),
        constraints=Constraints(min_thrust_to_weight=2.5),
        mode="reverse",
        scorer="efficiency",
        top_n=7,
        allow={"motors": ["a", "b"], "props": None},
        reverse_build=build_to_dict(small_build),
        compare_builds=[build_to_dict(small_build)],
    )
    path = tmp_path / "p.dronecalc.json"
    save_project(path, proj)
    back = load_project(path)
    assert back.mission == proj.mission
    assert back.assumptions == proj.assumptions
    assert back.constraints == proj.constraints
    assert (back.mode, back.scorer, back.top_n) == ("reverse", "efficiency", 7)
    assert back.allow == {"motors": ["a", "b"], "props": None}
    assert back.reverse_build == proj.reverse_build
    assert back.compare_builds == proj.compare_builds


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"format": "other"}', '{"format": "dronecalc-project", "version": 99}'],
)
def test_bad_project_files(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(ProjectError):
        load_project(path)


def test_project_missing_file(tmp_path):
    with pytest.raises(ProjectError):
        load_project(tmp_path / "missing.json")


# ---- custom entries ------------------------------------------------------------------------

ESC = {"id": "my-esc", "name": "My ESC", "max_current_a": 50, "max_cells": 6, "mass_g": 40}


def test_delete_custom_removes_entry_and_file_row(tmp_path):
    db = Database.load(custom_dir=tmp_path)
    db.add_custom("escs", ESC, tmp_path)
    assert db.is_custom("escs", "my-esc")
    db.delete_custom("escs", "my-esc", tmp_path)
    assert "my-esc" not in db.escs
    assert json.loads((tmp_path / "escs.json").read_text()) == []
    assert "my-esc" not in Database.load(custom_dir=tmp_path).escs


def test_delete_custom_restores_overridden_seed_entry(tmp_path):
    db = Database.load(custom_dir=tmp_path)
    original = db.escs["generic-esc-20a-4s"]
    db.update_custom("escs", {**ESC, "id": "generic-esc-20a-4s", "name": "tweaked"}, tmp_path)
    assert db.escs["generic-esc-20a-4s"].name == "tweaked"
    db.delete_custom("escs", "generic-esc-20a-4s", tmp_path)
    assert db.escs["generic-esc-20a-4s"] == original


def test_delete_seed_entry_refused(tmp_path):
    db = Database.load(custom_dir=tmp_path)
    with pytest.raises(DatabaseError, match="not a custom entry"):
        db.delete_custom("escs", "generic-esc-20a-4s", tmp_path)


def test_battery_groups_allowed_ids(db):
    groups = db.battery_groups(["lipo-4s-5000"])
    assert sum(len(v) for v in groups.values()) == 1


# ---- architecture rule ---------------------------------------------------------------------


def test_core_has_no_gui_imports():
    root = Path(core.__file__).parent
    banned = ("PySide6", "PyQt5", "PyQt6", "pyqtgraph", "tkinter")
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith(banned), f"{py.name} imports {n}"
    assert Build  # keep import used
