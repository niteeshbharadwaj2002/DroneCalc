import json

import pytest

from dronecalc.cli import main


def test_no_command_prints_version(capsys):
    assert main([]) == 0
    assert "DroneCalc" in capsys.readouterr().out


def test_size_table_output(capsys):
    assert main(["size", "--time", "20", "--payload", "0.5", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "PREDICTED, UNVERIFIED" in out
    assert "tmotor" in out or "sunnysky" in out or "emax" in out
    assert "density altitude" in out


def test_size_json_output(capsys):
    assert main(["size", "--time", "20", "--payload", "0.5", "--top", "2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["label"] == "predicted, unverified"
    assert len(data["builds"]) == 2 and data["builds"][0]["feasible"]


def test_size_infeasible_exit_code_and_reasons(capsys):
    assert main(["size", "--time", "300", "--payload", "25"]) == 1
    out = capsys.readouterr().out
    assert "No feasible build" in out and "Rejection reasons" in out


def test_reverse_output(capsys):
    args = [
        "reverse",
        "--motor", "sunnysky-x2212-980",
        "--prop", "generic-10x4.5",
        "--battery", "lipo-4s-5000",
        "--esc", "generic-esc-30a-4s",
        "--payload", "0.2",
    ]  # fmt: skip
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Max payload" in out and "Flight time" in out
    assert main(args + ["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["max_payload_kg"] > 0.2 and data["limiting_factor"]


def test_reverse_unknown_component_is_a_clean_error(capsys):
    code = main(
        ["reverse", "--motor", "nope", "--prop", "generic-10x4.5",
         "--battery", "lipo-4s-5000", "--esc", "generic-esc-30a-4s"]
    )  # fmt: skip
    assert code == 2
    assert "no motors entry" in capsys.readouterr().err


def test_invalid_value_is_a_clean_error(capsys):
    assert main(["size", "--time", "-5"]) == 2
    assert "error:" in capsys.readouterr().err


def test_db_list_and_check(capsys):
    assert main(["db", "list", "motors"]) == 0
    assert "sunnysky-x2212-980" in capsys.readouterr().out
    assert main(["db", "check"]) == 0
    assert "loaded" in capsys.readouterr().out


def test_validate_reports_criterion_not_met(capsys):
    assert main(["validate"]) == 2
    assert "NOT met" in capsys.readouterr().out


def test_argparse_rejects_bad_rotor_count():
    with pytest.raises(SystemExit):
        main(["size", "--time", "10", "--rotors", "5"])
