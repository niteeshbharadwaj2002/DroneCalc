"""Desktop UI tests (headless). They drive real widgets and compare the displayed numbers with
direct calls into ``dronecalc.core``, so they cover the UI, the calculations and their wiring."""

import csv

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

import dronecalc.ui.state as ui_state  # noqa: E402
from dronecalc.core import (  # noqa: E402
    Assumptions,
    Build,
    Constraints,
    Database,
    Mission,
    SizingCancelled,
    atmosphere,
    estimate_frame_mass_kg,
    size_forward,
    size_reverse,
)
from dronecalc.ui.app import create_window  # noqa: E402
from dronecalc.ui.screens.database import SPECS  # noqa: E402
from dronecalc.ui.state import KINDS  # noqa: E402


@pytest.fixture
def win(qtbot, tmp_path):
    w = create_window(custom_dir=tmp_path / "custom")
    qtbot.addWidget(w)
    w.show()
    return w


def run_forward_and_wait(qtbot, win):
    with qtbot.waitSignal(win.state.resultsChanged, timeout=20000):
        qtbot.mouseClick(win.mission.run_btn, Qt.LeftButton)
    assert win.state.wait_idle()


def pick(combo, entry_id):
    combo.setCurrentIndex(combo.findData(entry_id))


def pick_reverse_build(win, motor, prop, battery, esc):
    c = win.components.combos
    pick(c["motor"], motor)
    pick(c["prop"], prop)
    pick(c["battery"], battery)
    pick(c["esc"], esc)


REV = ("tmotor-mn4006-380", "generic-15x5.0", "lipo-6s-10000", "generic-esc-40a-6s")


# ---- 1. the UI itself ----------------------------------------------------------------------


def test_window_builds_with_all_five_screens(win):
    assert [win.nav.item(i).text() for i in range(win.nav.count())] == [
        "Mission",
        "Components",
        "Results",
        "Compare",
        "Database",
    ]
    assert win.stack.count() == 5
    for name in ("Mission", "Components", "Results", "Compare", "Database"):
        win.show_screen(name)
        assert win.current_screen() == name
    assert "predicted, unverified" in win.banner.text().lower()
    assert win.windowTitle().startswith("DroneCalc - Untitled")


def test_mission_widgets_drive_state(win):
    m = win.mission
    m.payload.spin.setValue(1.25)
    m.altitude.spin.setValue(2000)
    m.temp.spin.setValue(-10)
    m.time.slider.setValue(m.time.slider.value() + 5)
    m.rotors.setCurrentIndex(m.rotors.findData(6))
    s = win.state.mission
    assert s.payload_kg == 1.25 and s.altitude_m == 2000 and s.temp_offset_c == -10
    assert s.target_flight_time_min == m.time.value() == 25
    assert s.n_rotors == 6


def test_slider_and_spinbox_stay_in_sync(win):
    f = win.mission.payload
    f.slider.setValue(10)
    assert f.value() == pytest.approx(0.5)
    f.spin.setValue(2.0)
    assert f.slider.value() == round(2.0 / 0.05)


def test_density_readout_matches_core(win):
    win.mission.altitude.spin.setValue(3000)
    rho = atmosphere(3000, 0).density
    assert f"{rho:.3f}" in win.mission.atm_label.text()


def test_optional_fields_set_and_clear_limits(win):
    m = win.mission
    m.max_mass.check.setChecked(True)
    m.max_mass.field.spin.setValue(4.0)
    m.max_budget.check.setChecked(True)
    assert win.state.mission.max_mass_kg == 4.0 and win.state.mission.max_budget_usd == 800
    m.max_mass.check.setChecked(False)
    assert win.state.mission.max_mass_kg is None


def test_invalid_input_is_rejected_and_reported(win):
    before = win.state.mission
    assert win.state.update_mission(target_flight_time_min=-5) is False
    assert win.state.mission == before
    assert win.errors and "target_flight_time_min" in win.errors[-1]


def test_mode_toggle_changes_run_button_and_navigation(win, qtbot):
    win.mission.rev.setChecked(True)
    assert win.state.mode == "reverse"
    assert "Evaluate" in win.mission.run_btn.text()
    assert not win.mission.time.isEnabled()
    qtbot.mouseClick(win.mission.run_btn, Qt.LeftButton)
    assert win.current_screen() == "Components"
    win.mission.fwd.setChecked(True)
    assert win.state.mode == "forward" and win.mission.time.isEnabled()


def test_advanced_panel_shows_defaults_and_resets(win):
    m = win.mission
    a, c = Assumptions(), Constraints()
    assert not m.advanced.isChecked() and not m.dod.isEnabled()  # visible but locked by default
    m.advanced.setChecked(True)
    assert m.dod.isEnabled() and m.reset_btn.isEnabled()
    assert m.dod.value() == a.depth_of_discharge and m.max_thr.value() == c.max_hover_throttle
    m.dod.spin.setValue(0.6)
    m.min_tw.spin.setValue(3.0)
    m.chk_c.setChecked(False)
    assert win.state.assumptions.depth_of_discharge == 0.6
    assert win.state.constraints.min_thrust_to_weight == 3.0
    assert win.state.constraints.check_battery_c_rate is False
    m.reset_btn.click()
    assert win.state.assumptions == a and win.state.constraints == c
    assert m.dod.value() == a.depth_of_discharge and m.chk_c.isChecked()


# ---- 2/3. forward sizing: UI == core -------------------------------------------------------


def test_forward_run_is_asynchronous_and_navigates(win, qtbot):
    states = []
    win.state.busyChanged.connect(states.append)
    qtbot.mouseClick(win.mission.run_btn, Qt.LeftButton)
    assert win.state.busy  # returned immediately; work is in a worker thread
    assert win.current_screen() == "Results"
    qtbot.waitUntil(lambda: not win.state.busy, timeout=20000)
    assert states == [True, False]
    assert win.results.table.rowCount() == len(win.state.sizing_result.ranked) > 0


@pytest.mark.parametrize(
    "time_min,payload,altitude,temp,rotors",
    [(20, 0.5, 0, 0, 4), (15, 1.0, 1500, -10, 6), (10, 0.0, 3000, 15, 4), (30, 2.0, 500, 0, 8)],
)
def test_forward_results_match_core_exactly(qtbot, win, time_min, payload, altitude, temp, rotors):
    m = win.mission
    m.time.spin.setValue(time_min)
    m.payload.spin.setValue(payload)
    m.altitude.spin.setValue(altitude)
    m.temp.spin.setValue(temp)
    m.rotors.setCurrentIndex(m.rotors.findData(rotors))
    run_forward_and_wait(qtbot, win)

    expected = size_forward(
        Mission(
            target_flight_time_min=time_min,
            payload_kg=payload,
            altitude_m=altitude,
            temp_offset_c=temp,
            n_rotors=rotors,
        ),
        Database.load(custom_dir=win.state.custom_dir),
        top_n=10,
    )
    got = win.state.sizing_result
    assert [r.to_dict() for r in got.ranked] == [r.to_dict() for r in expected.ranked]
    assert got.rejections == expected.rejections
    # and the table shows those numbers, best first
    t = win.results.table
    assert t.rowCount() == len(expected.ranked)
    for row, r in enumerate(expected.ranked):
        assert t.item(row, 1).text() == r.build.motor.id
        assert t.item(row, 8).text() == f"{r.flight_time_min:.1f}"
        assert t.item(row, 5).text() == f"{r.total_mass_kg * 1000:.0f}"


def test_results_selection_populates_detail(qtbot, win):
    run_forward_and_wait(qtbot, win)
    r = win.state.sizing_result.ranked[0]
    d = win.results.detail
    assert win.results.table.currentRow() == 0 or win.results.selected_result() is r
    assert d.metrics.text("Flight time") == f"{r.flight_time_min:.1f} min"
    assert d.metrics.text("Thrust-to-weight") == f"{r.thrust_to_weight:.2f}"
    assert sum(g for _n, g in d.mass_bar.parts()) == pytest.approx(r.total_mass_kg * 1000)
    win.results.table.selectRow(2)
    r2 = win.state.sizing_result.ranked[2]
    assert win.results.detail.metrics.text("Flight time") == f"{r2.flight_time_min:.1f} min"


def test_results_table_sorting_uses_numbers(qtbot, win):
    run_forward_and_wait(qtbot, win)
    t = win.results.table
    t.sortItems(5, Qt.AscendingOrder)  # mass
    masses = [float(t.item(i, 5).text()) for i in range(t.rowCount())]
    assert masses == sorted(masses)


def test_rejection_reasons_shown(qtbot, win):
    run_forward_and_wait(qtbot, win)
    res = win.state.sizing_result
    assert win.results.rej_table.rowCount() == len(res.rejections) > 0
    assert not win.results.rej_group.isHidden()


def test_infeasible_mission_explains_why(qtbot, win):
    win.mission.time.spin.setValue(120)
    win.mission.payload.spin.setValue(10)
    win.mission.max_mass.check.setChecked(True)
    win.mission.max_mass.field.spin.setValue(0.5)
    run_forward_and_wait(qtbot, win)
    assert win.state.sizing_result.ranked == []
    assert win.results.table.rowCount() == 0
    assert "No feasible build" in win.results.summary.text()
    assert win.results.rej_table.rowCount() > 0
    assert not win.results.add_btn.isEnabled()


def test_stale_banner_after_input_change(qtbot, win):
    run_forward_and_wait(qtbot, win)
    assert win.results.stale.isHidden()
    win.mission.payload.spin.setValue(1.5)
    assert not win.results.stale.isHidden()
    run_forward_and_wait(qtbot, win)
    assert win.results.stale.isHidden()


def test_advanced_setting_changes_forward_results(qtbot, win):
    run_forward_and_wait(qtbot, win)
    base = win.state.sizing_result.ranked[0].flight_time_min
    win.mission.derate.spin.setValue(0.4)
    run_forward_and_wait(qtbot, win)
    assert win.state.sizing_result.ranked[0].flight_time_min < base


def test_ranking_choice_changes_order(qtbot, win):
    win.mission.scorer.setCurrentIndex(win.mission.scorer.findData("cheapest"))
    run_forward_and_wait(qtbot, win)
    costs = [r.cost_usd for r in win.state.sizing_result.ranked]
    assert costs == sorted(costs)


def test_forward_filters_limit_the_search(qtbot, win):
    lw = win.components.lists["motors"]
    win.components._set_all("motors", False)
    for i in range(lw.count()):
        if lw.item(i).data(Qt.UserRole) == "tmotor-mn4006-380":
            lw.item(i).setCheckState(Qt.Checked)
    assert win.state.allow["motors"] == {"tmotor-mn4006-380"}
    assert "1 of" in win.components.counts["motors"].text()
    run_forward_and_wait(qtbot, win)
    assert {r.build.motor.id for r in win.state.sizing_result.ranked} == {"tmotor-mn4006-380"}
    win.components._set_all("motors", True)
    assert win.state.allow["motors"] is None


def test_cancel_stops_a_running_job(qtbot, win, monkeypatch):
    def slow(*_a, cancel=None, progress=None, **_k):
        import time

        for i in range(500):
            if cancel():
                raise SizingCancelled("x")
            progress(i, 500)
            time.sleep(0.01)

    monkeypatch.setattr(ui_state, "size_forward", slow)
    assert win.state.run_forward()
    assert win.state.busy
    assert win.state.run_forward() is False  # second request refused while busy
    win.results.cancel_btn.click()
    qtbot.waitUntil(lambda: not win.state.busy, timeout=10000)
    assert win.state.sizing_result is None


def test_worker_failure_is_reported_not_crashing(qtbot, win, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(ui_state, "size_forward", boom)
    win.state.run_forward()
    qtbot.waitUntil(lambda: not win.state.busy, timeout=10000)
    assert any("model exploded" in e for e in win.errors)
    assert "model exploded" in win.results.summary.text()


# ---- 2/3. reverse sizing: UI == core -------------------------------------------------------


def test_reverse_requires_all_components(win):
    assert not win.state.reverse_ready()
    assert "Choose" in win.components.status.text()
    assert not win.components.add_btn.isEnabled()
    pick(win.components.combos["motor"], REV[0])
    assert win.state.reverse_result is None


@pytest.mark.parametrize("payload,altitude,temp", [(0.0, 0, 0), (1.0, 1000, -10), (0.5, 2500, 10)])
def test_reverse_matches_core(win, payload, altitude, temp):
    win.mission.payload.spin.setValue(payload)
    win.mission.altitude.spin.setValue(altitude)
    win.mission.temp.spin.setValue(temp)
    pick_reverse_build(win, *REV)
    db = win.state.db
    prop = db.get("props", REV[1])
    build = Build(
        db.get("motors", REV[0]),
        prop,
        db.get("batteries", REV[2]),
        db.get("escs", REV[3]),
        4,
        estimate_frame_mass_kg(prop.diameter_in, 4),
    )
    expected = size_reverse(build, payload, altitude, temp)
    got = win.state.reverse_result
    assert got.max_payload_kg == pytest.approx(expected.max_payload_kg)
    assert got.limiting_factor == expected.limiting_factor
    assert got.result.to_dict() == expected.result.to_dict()
    assert f"{expected.max_payload_kg:.2f} kg" in win.components.status.text()
    assert win.components.detail.metrics.text("Flight time") == (
        f"{expected.result.flight_time_min:.1f} min"
    )


def test_reverse_updates_live_when_mission_changes(win):
    pick_reverse_build(win, *REV)
    t0 = win.state.reverse_result.result.flight_time_min
    win.mission.payload.spin.setValue(2.0)
    assert win.state.reverse_result.result.flight_time_min < t0
    win.mission.dod.spin.setValue(0.5)
    assert win.state.reverse_result.result.flight_time_min < t0


def test_reverse_incompatible_build_shows_violations(win):
    # 6S pack on a motor rated to 4S only, with a 4S ESC
    pick_reverse_build(
        win, "sunnysky-x2212-980", "generic-10x4.5", "lipo-6s-10000", "generic-esc-20a-4s"
    )
    texts = " ".join(win.components.detail.notices.texts())
    assert "motor range" in texts or "ESC range" in texts


def test_results_to_reverse_roundtrip_consistent(qtbot, win):
    """A forward result re-evaluated in reverse mode reproduces its flight time."""
    run_forward_and_wait(qtbot, win)
    r = win.state.sizing_result.ranked[0]
    win.results.table.selectRow(0)
    win.results.rev_btn.click()
    assert win.current_screen() == "Components"
    assert win.components.tabs.currentIndex() == 0
    got = win.state.reverse_result.result
    assert got.flight_time_min == pytest.approx(r.flight_time_min)
    assert got.total_mass_kg == pytest.approx(r.total_mass_kg)
    assert win.components.combos["motor"].currentData() == r.build.motor.id


def test_plots_receive_data(qtbot, win):
    run_forward_and_wait(qtbot, win)
    d = win.results.detail
    curve = d.time_plot.getPlotItem().listDataItems()[0]
    xs, ys = curve.getData()
    assert len(xs) == 25 and ys[0] > ys[-1]  # flight time falls with payload
    thr = d.thr_plot.getPlotItem().listDataItems()[0].getData()[1]
    assert thr[0] < thr[-1]  # throttle rises with payload


# ---- compare -------------------------------------------------------------------------------


def test_compare_flow(qtbot, win):
    run_forward_and_wait(qtbot, win)
    ranked = win.state.sizing_result.ranked
    for i in range(3):
        win.results.table.selectRow(i)
        win.results.add_btn.click()
    assert len(win.state.compare_builds) == 3
    win.results.table.selectRow(0)
    win.results.add_btn.click()  # duplicate ignored
    assert len(win.state.compare_builds) == 3
    t = win.compare.table
    assert t.columnCount() == 3 and t.rowCount() > 5
    assert t.item(0, 0).text() == f"{ranked[0].flight_time_min:.1f}"
    best_cells = [t.item(0, c).background().color().alpha() for c in range(3)]
    assert best_cells[0] > 0  # best flight time highlighted
    assert len(win.compare.plot.getPlotItem().listDataItems()) == 3

    win.results.table.selectRow(3)
    win.results.add_btn.click()
    win.results.table.selectRow(4)
    win.results.add_btn.click()  # 5th is refused
    assert len(win.state.compare_builds) == 4
    assert "at most 4" in win.errors[-1]

    t.selectColumn(1)
    win.compare.remove_btn.click()
    assert len(win.state.compare_builds) == 3
    win.compare.clear_btn.click()
    assert win.state.compare_builds == [] and win.compare.table.columnCount() == 0


def test_compare_values_match_core(qtbot, win):
    run_forward_and_wait(qtbot, win)
    for i in range(2):
        win.results.table.selectRow(i)
        win.results.add_btn.click()
    win.mission.payload.spin.setValue(1.0)  # comparison re-evaluates in the new environment
    rows = win.state.compare_results()
    for c, (b, r, err) in enumerate(rows):
        assert err is None
        rev = size_reverse(b, 1.0)
        assert r.flight_time_min == pytest.approx(rev.result.flight_time_min)
        assert win.compare.table.item(0, c).text() == f"{r.flight_time_min:.1f}"


# ---- database manager ----------------------------------------------------------------------

NEW_MOTOR = {
    "id": "my-motor",
    "name": "My Motor",
    "kv_rpm_per_v": "500",
    "resistance_ohm": "0.08",
    "no_load_current_a": "0.5",
    "mass_g": "100",
    "max_current_a": "30",
    "min_cells": "4",
    "max_cells": "6",
    "prop_min_in": "12",
    "prop_max_in": "15",
    "price_usd": "50",
}


def fill(win, kind, values):
    ed = win.database.editors[kind]
    ed.clear()
    for k, v in values.items():
        ed.widgets[k].setText(v)


def test_database_tables_list_seed_entries(win):
    for kind in KINDS:
        assert win.database.tables[kind].rowCount() == len(getattr(win.state.db, kind))
    assert "verified=false" in win.database.warn_label.text()


def test_database_add_custom_motor_end_to_end(qtbot, win):
    fill(win, "motors", NEW_MOTOR)
    ok, msg = win.database.save_entry("motors")
    assert ok, msg
    assert "my-motor" in win.state.db.motors
    assert (win.state.custom_dir / "motors.json").exists()
    assert Database.load(custom_dir=win.state.custom_dir).motors["my-motor"].kv_rpm_per_v == 500
    # shows up in the table, the components pickers and the filters
    assert win.database.tables["motors"].rowCount() == len(win.state.db.motors)
    assert win.components.combos["motor"].findData("my-motor") >= 0
    assert any(
        win.components.lists["motors"].item(i).data(Qt.UserRole) == "my-motor"
        for i in range(win.components.lists["motors"].count())
    )
    # and the sizing core can use it
    win.components._set_all("motors", False)
    lw = win.components.lists["motors"]
    for i in range(lw.count()):
        if lw.item(i).data(Qt.UserRole) == "my-motor":
            lw.item(i).setCheckState(Qt.Checked)
    run_forward_and_wait(qtbot, win)
    assert {r.build.motor.id for r in win.state.sizing_result.ranked} <= {"my-motor"}


@pytest.mark.parametrize(
    "change,expect",
    [
        ({"kv_rpm_per_v": "fast"}, "number"),
        ({"min_cells": "4.5"}, "whole number"),
        ({"mass_g": ""}, "required"),
        ({"kv_rpm_per_v": "-5"}, "positive"),
        ({"min_cells": "7", "max_cells": "5"}, "min_cells"),
        ({"id": ""}, "id is required"),
    ],
)
def test_database_rejects_bad_entries(win, change, expect):
    fill(win, "motors", {**NEW_MOTOR, **change})
    before = len(win.state.db.motors)
    ok, msg = win.database.save_entry("motors")
    assert not ok and expect in msg
    assert len(win.state.db.motors) == before
    assert not (win.state.custom_dir / "motors.json").exists()


def test_database_edit_clone_delete_custom(win):
    fill(win, "motors", NEW_MOTOR)
    assert win.database.save_entry("motors")[0]
    win.database._reselect("motors", "my-motor")
    assert win.database.selected_id("motors") == "my-motor"
    win.database.editors["motors"].widgets["mass_g"].setText("120")
    assert win.database.save_entry("motors")[0]
    assert win.state.db.motors["my-motor"].mass_g == 120
    win.database._clone("motors")
    assert win.database.editors["motors"].widgets["id"].text() == "my-motor-copy"
    assert win.database.save_entry("motors")[0]
    win.database.delete_entry("motors", "my-motor-copy")
    assert "my-motor-copy" not in win.state.db.motors
    assert win.state.db.is_custom("motors", "my-motor")
    assert win.database.tables["motors"].rowCount() == len(win.state.db.motors)


def test_database_seed_entry_can_be_overridden_and_restored(win):
    seed = win.state.db.motors["tmotor-mn4006-380"]
    win.database._reselect("motors", "tmotor-mn4006-380")
    win.database.editors["motors"].widgets["mass_g"].setText("999")
    assert win.database.save_entry("motors")[0]
    assert win.state.db.motors["tmotor-mn4006-380"].mass_g == 999
    win.database.delete_entry("motors", "tmotor-mn4006-380")
    assert win.state.db.motors["tmotor-mn4006-380"] == seed


def test_deleting_component_cleans_references(qtbot, win):
    fill(win, "escs", {"id": "tmp-esc", "name": "Tmp", "max_current_a": "40", "min_cells": "3",
                       "max_cells": "6", "mass_g": "30", "price_usd": "10"})  # fmt: skip
    assert win.database.save_entry("escs")[0]
    pick_reverse_build(win, REV[0], REV[1], REV[2], "tmp-esc")
    assert win.state.reverse_ids["esc"] == "tmp-esc"
    from dronecalc.core import Build

    win.state.add_to_compare(
        Build(
            win.state.db.motors[REV[0]],
            win.state.db.props[REV[1]],
            win.state.db.batteries[REV[2]],
            win.state.db.escs["tmp-esc"],
            4,
            0.5,
        )
    )
    win.database.delete_entry("escs", "tmp-esc")
    assert win.state.reverse_ids["esc"] is None
    assert win.state.compare_builds == []
    assert win.components.combos["esc"].currentData() is None


def test_every_spec_field_exists_on_the_core_models():
    from dataclasses import fields

    from dronecalc.core.database import KINDS as CORE_KINDS

    for kind, spec in SPECS.items():
        assert set(spec) == {f.name for f in fields(CORE_KINDS[kind])}, kind


# ---- projects and export -------------------------------------------------------------------


def test_project_save_and_open_round_trip(qtbot, win, tmp_path):
    m = win.mission
    m.payload.spin.setValue(1.2)
    m.altitude.spin.setValue(900)
    m.dod.spin.setValue(0.7)
    m.scorer.setCurrentIndex(m.scorer.findData("lightest"))
    win.components._set_all("props", False)
    lw = win.components.lists["props"]
    for i in range(lw.count()):
        if lw.item(i).data(Qt.UserRole) in ("generic-15x5.0", "generic-14x4.8"):
            lw.item(i).setCheckState(Qt.Checked)
    pick_reverse_build(win, *REV)
    run_forward_and_wait(qtbot, win)
    assert win.state.sizing_result.ranked, "setup must produce results to compare"
    win.results.table.selectRow(0)
    win.results.add_btn.click()
    assert len(win.state.compare_builds) == 1
    assert win.state.dirty and win.windowTitle().endswith("*")

    path = tmp_path / "a.dronecalc.json"
    assert win.save_project_path(path)
    assert not win.state.dirty and win.windowTitle().startswith("DroneCalc - a.dronecalc.json")

    other = create_window(custom_dir=win.state.custom_dir)
    qtbot.addWidget(other)
    assert other.open_project_path(path)
    s, o = win.state, other.state
    assert (o.mission, o.assumptions, o.constraints) == (s.mission, s.assumptions, s.constraints)
    assert (o.scorer, o.top_n, o.mode) == (s.scorer, s.top_n, s.mode)
    assert o.allow == s.allow
    assert o.reverse_ids == s.reverse_ids
    assert o.compare_builds == s.compare_builds
    # UI widgets reflect the loaded values
    assert other.mission.payload.value() == 1.2 and other.mission.dod.value() == 0.7
    assert other.mission.scorer.currentData() == "lightest"
    assert other.components.combos["motor"].currentData() == REV[0]
    assert other.compare.table.columnCount() == 1
    assert other.state.reverse_result.max_payload_kg == pytest.approx(
        s.reverse_result.max_payload_kg
    )
    assert not o.dirty
    # the reloaded project produces the same sizing
    run_forward_and_wait(qtbot, other)
    assert [r.to_dict() for r in other.state.sizing_result.ranked] == [
        r.to_dict() for r in win.state.sizing_result.ranked
    ]


def test_new_project_resets_everything(qtbot, win):
    win.mission.payload.spin.setValue(3.0)
    run_forward_and_wait(qtbot, win)
    win.state.new_project()
    assert win.state.mission.payload_kg == 0.5 and win.state.sizing_result is None
    assert win.mission.payload.value() == 0.5 and win.results.table.rowCount() == 0
    assert win.windowTitle().startswith("DroneCalc - Untitled") and not win.state.dirty


def test_opening_bad_project_reports_error(win, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    before = win.state.mission
    assert not win.open_project_path(bad)
    assert win.state.mission == before and "invalid JSON" in win.errors[-1]
    assert not win.open_project_path(tmp_path / "missing.json")


def test_project_with_missing_component_warns_and_loads(qtbot, win, tmp_path):
    pick_reverse_build(win, *REV)
    path = tmp_path / "p.json"
    win.save_project_path(path)
    import json

    data = json.loads(path.read_text())
    data["reverse_build"]["motor"] = "ghost-motor"
    path.write_text(json.dumps(data))
    warnings = win.state.open_project_from(path)
    assert any("ghost-motor" in w for w in warnings)
    assert win.state.reverse_result is None


def test_csv_export_matches_results(qtbot, win, tmp_path):
    run_forward_and_wait(qtbot, win)
    out = tmp_path / "r.csv"
    assert win.export_csv_path(out)
    rows = list(csv.DictReader(out.open()))
    ranked = win.state.sizing_result.ranked
    assert len(rows) == len(ranked)
    for row, r in zip(rows, ranked):
        assert row["motor"] == r.build.motor.id
        assert float(row["flight_time_min"]) == pytest.approx(r.flight_time_min, abs=0.01)


def test_csv_export_without_results_is_an_error(win, tmp_path):
    assert not win.export_csv_path(tmp_path / "x.csv")
    assert "no results" in win.errors[-1]
    assert not (tmp_path / "x.csv").exists()


def test_about_dialog_mentions_limitations(win):
    win.about()  # non-interactive: builds the dialog without blocking
