"""CSV export of sizing results."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import IO

from dronecalc.core.evaluate import BuildResult

COLUMNS = [
    "rank",
    "motor",
    "prop",
    "battery",
    "esc",
    "n_rotors",
    "cells",
    "battery_mah",
    "total_mass_g",
    "payload_kg",
    "hover_throttle_pct",
    "hover_power_w",
    "hover_current_a",
    "flight_time_min",
    "thrust_to_weight",
    "figure_of_merit",
    "cost_usd",
    "feasible",
    "label",
]


def result_row(rank: int, r: BuildResult) -> dict[str, object]:
    b = r.build
    return {
        "rank": rank,
        "motor": b.motor.id,
        "prop": b.prop.id,
        "battery": b.battery.id,
        "esc": b.esc.id,
        "n_rotors": b.n_rotors,
        "cells": b.battery.cells,
        "battery_mah": b.battery.capacity_mah,
        "total_mass_g": round(r.total_mass_kg * 1000.0, 1),
        "payload_kg": r.payload_kg,
        "hover_throttle_pct": round(r.hover_throttle * 100.0, 1),
        "hover_power_w": round(r.hover_battery_power_w, 1),
        "hover_current_a": round(r.hover_battery_current_a, 2),
        "flight_time_min": round(r.flight_time_min, 2),
        "thrust_to_weight": round(r.thrust_to_weight, 3),
        "figure_of_merit": round(r.figure_of_merit, 3),
        "cost_usd": round(r.cost_usd, 2),
        "feasible": r.feasible,
        "label": "predicted, unverified",
    }


def write_results_csv(results: Iterable[BuildResult], dest: Path | str | IO[str]) -> int:
    """Write ranked results (best first) to a path or open text file; returns the row count."""

    def _write(fh: IO[str]) -> int:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        n = 0
        for n, r in enumerate(results, 1):
            writer.writerow(result_row(n, r))
        return n

    if hasattr(dest, "write"):
        return _write(dest)  # type: ignore[arg-type]
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        return _write(fh)
