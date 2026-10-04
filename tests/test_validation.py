import csv

import pytest

from dronecalc.core import Database, load_reference_points, validate
from dronecalc.core.validation import (
    COLUMNS,
    REQUIRED_COMBOS,
    ReferencePoint,
    ValidationDataError,
    predict_point,
)


def _write(path, rows):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)


def _synthetic_rows(db, scale=1.0, n_combos=12):
    """Rows generated from the model itself: tests the harness machinery only, NOT the physics."""
    rows = []
    combos = [
        (m, p, v)
        for m in ("sunnysky-x2212-980", "emax-mt2213-935", "sunnysky-x2216-880")
        for p in ("generic-8x4.5", "generic-9x4.7", "generic-10x4.5", "generic-11x4.7")
        for v in (11.1, 14.8)
    ][:n_combos]
    for m, p, v in combos:
        for thrust in (300, 600):
            _, power = predict_point(db, ReferencePoint(m, p, v, thrust, None, 1.0))
            rows.append([m, p, v, thrust, "", f"{power * scale:.3f}", "synthetic self-test"])
    return rows


def test_shipped_reference_file_is_empty_and_criterion_not_met(db):
    report = validate(db)
    assert report.combos_total == 0 and not report.criterion_met
    assert "NOT met" in report.message


def test_harness_passes_on_self_consistent_data(db, tmp_path):
    csv_path = tmp_path / "ref.csv"
    _write(csv_path, _synthetic_rows(db))
    report = validate(db, load_reference_points(csv_path))
    assert report.combos_total >= REQUIRED_COMBOS
    assert report.combos_within_tolerance == report.combos_total
    assert report.criterion_met and report.mean_abs_power_error < 1e-4


def test_harness_flags_out_of_tolerance_data(db, tmp_path):
    csv_path = tmp_path / "ref.csv"
    _write(csv_path, _synthetic_rows(db, scale=1 / 1.3))  # model over-predicts by 30%
    report = validate(db, load_reference_points(csv_path))
    assert report.combos_within_tolerance == 0 and not report.criterion_met
    assert report.mean_abs_power_error == pytest.approx(0.3, abs=1e-3)


def test_combo_needs_all_points_within_tolerance(db, tmp_path):
    rows = _synthetic_rows(db, n_combos=1)
    rows[1][5] = f"{float(rows[1][5]) * 2:.3f}"  # one bad point spoils the combo
    csv_path = tmp_path / "ref.csv"
    _write(csv_path, rows)
    report = validate(db, load_reference_points(csv_path))
    assert report.combos_total == 1 and report.combos_within_tolerance == 0


def test_loader_errors(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("motor_id,prop_id\nm,p\n")
    with pytest.raises(ValidationDataError, match="missing column"):
        load_reference_points(bad)
    _write(bad, [["m", "p", "11.1", "500", "", "", "x"]])
    with pytest.raises(ValidationDataError, match="current_a and/or power_w"):
        load_reference_points(bad)
    _write(bad, [["m", "p", "abc", "500", "", "50", "x"]])
    with pytest.raises(ValidationDataError):
        load_reference_points(bad)
    assert load_reference_points(tmp_path / "missing.csv") == []


def test_unknown_component_in_reference_data_raises(tmp_path):
    csv_path = tmp_path / "ref.csv"
    _write(csv_path, [["nope", "generic-10x4.5", "11.1", "500", "", "50", "x"]])
    with pytest.raises(KeyError):
        validate(Database.load(include_custom=False), load_reference_points(csv_path))
