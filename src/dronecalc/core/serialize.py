"""Dict round trips for the input models, used by project files and front ends."""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from dronecalc.core.database import Database
from dronecalc.core.models import Assumptions, Build, Constraints, Mission


def _strict(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ValueError(f"unknown field(s) {unknown} for {cls.__name__}")
    return dict(data)


def _plain(value: Any) -> Any:
    """Tuples to lists so the result is JSON-ready."""
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def mission_to_dict(mission: Mission) -> dict[str, Any]:
    return {k: _plain(v) for k, v in asdict(mission).items()}


def mission_from_dict(data: dict[str, Any]) -> Mission:
    return Mission(**_strict(Mission, data))


def assumptions_to_dict(assumptions: Assumptions) -> dict[str, Any]:
    return {k: _plain(v) for k, v in asdict(assumptions).items()}


def assumptions_from_dict(data: dict[str, Any]) -> Assumptions:
    d = _strict(Assumptions, data)
    if "battery_temp_table" in d:
        d["battery_temp_table"] = tuple((float(t), float(f)) for t, f in d["battery_temp_table"])
    if "fm_range" in d:
        lo, hi = d["fm_range"]
        d["fm_range"] = (float(lo), float(hi))
    return Assumptions(**d)


def constraints_to_dict(constraints: Constraints) -> dict[str, Any]:
    return asdict(constraints)


def constraints_from_dict(data: dict[str, Any]) -> Constraints:
    return Constraints(**_strict(Constraints, data))


def build_to_dict(build: Build) -> dict[str, Any]:
    """A build as component ids plus the frame mass; resolved against a ``Database`` on load."""
    return {
        "motor": build.motor.id,
        "prop": build.prop.id,
        "battery": build.battery.id,
        "esc": build.esc.id,
        "n_rotors": build.n_rotors,
        "frame_mass_kg": build.frame_mass_kg,
    }


def build_from_dict(db: Database, data: dict[str, Any]) -> Build:
    try:
        return Build(
            motor=db.get("motors", data["motor"]),
            prop=db.get("props", data["prop"]),
            battery=db.get("batteries", data["battery"]),
            esc=db.get("escs", data["esc"]),
            n_rotors=int(data["n_rotors"]),
            frame_mass_kg=float(data["frame_mass_kg"]),
        )
    except KeyError as exc:
        raise ValueError(f"cannot restore build: {exc.args[0]}") from exc
