"""Compare model predictions against reference thrust-table points (manufacturer or bench data).

Each reference row describes one motor + prop + supply voltage at one measured thrust, with the
measured battery-side current and/or power. The model predicts those at the same thrust on a
fixed supply (ISA sea level unless the row says otherwise), so errors isolate the propulsion
model. Phase 1 exit criterion (project doc, 3.6): at least 10 motor/prop/voltage combinations
within +/-15% on power.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from dronecalc.config import DATA_DIR
from dronecalc.core.constants import G
from dronecalc.core.database import Database
from dronecalc.core.environment import atmosphere
from dronecalc.core.models import Assumptions
from dronecalc.core.propulsion import motor_point_for_thrust

REFERENCE_CSV = DATA_DIR / "validation" / "reference_points.csv"
REQUIRED_COMBOS = 10
DEFAULT_TOLERANCE = 0.15
COLUMNS = ("motor_id", "prop_id", "voltage_v", "thrust_g", "current_a", "power_w", "source")


class ValidationDataError(Exception):
    pass


@dataclass(frozen=True)
class ReferencePoint:
    motor_id: str
    prop_id: str
    voltage_v: float
    thrust_g: float
    current_a: float | None
    power_w: float | None
    source: str = ""
    altitude_m: float = 0.0
    temp_offset_c: float = 0.0

    @property
    def combo(self) -> tuple[str, str, float]:
        return (self.motor_id, self.prop_id, self.voltage_v)


@dataclass(frozen=True)
class PointComparison:
    point: ReferencePoint
    predicted_current_a: float
    predicted_power_w: float
    power_error: float | None  # (pred - ref) / ref
    current_error: float | None


@dataclass
class ValidationReport:
    comparisons: list[PointComparison]
    tolerance: float
    combos_total: int
    combos_within_tolerance: int
    mean_abs_power_error: float | None
    criterion_met: bool

    @property
    def message(self) -> str:
        if self.combos_total == 0:
            return (
                "No reference points loaded. Phase 1 exit criterion NOT met: needs "
                f">= {REQUIRED_COMBOS} motor/prop/voltage combinations within "
                f"+/-{self.tolerance:.0%}."
            )
        status = "met" if self.criterion_met else "NOT met"
        return (
            f"{self.combos_within_tolerance}/{self.combos_total} combinations within "
            f"+/-{self.tolerance:.0%} on power; exit criterion {status} "
            f"(needs >= {REQUIRED_COMBOS})."
        )


def _opt_float(raw: dict[str, str], key: str) -> float | None:
    value = (raw.get(key) or "").strip()
    return float(value) if value else None


def load_reference_points(path: Path | None = None) -> list[ReferencePoint]:
    path = Path(path) if path is not None else REFERENCE_CSV
    if not path.exists():
        return []
    points: list[ReferencePoint] = []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if line.strip() and not line.startswith("#"))
        if rows.fieldnames is None:
            return []
        missing = [
            c for c in ("motor_id", "prop_id", "voltage_v", "thrust_g") if c not in rows.fieldnames
        ]
        if missing:
            raise ValidationDataError(f"{path}: missing column(s) {missing}")
        for line_no, raw in enumerate(rows, start=2):
            try:
                point = ReferencePoint(
                    motor_id=raw["motor_id"].strip(),
                    prop_id=raw["prop_id"].strip(),
                    voltage_v=float(raw["voltage_v"]),
                    thrust_g=float(raw["thrust_g"]),
                    current_a=_opt_float(raw, "current_a"),
                    power_w=_opt_float(raw, "power_w"),
                    source=(raw.get("source") or "").strip(),
                    altitude_m=_opt_float(raw, "altitude_m") or 0.0,
                    temp_offset_c=_opt_float(raw, "temp_offset_c") or 0.0,
                )
            except (TypeError, ValueError) as exc:
                raise ValidationDataError(f"{path} row {line_no}: {exc}") from exc
            if point.current_a is None and point.power_w is None:
                raise ValidationDataError(f"{path} row {line_no}: need current_a and/or power_w")
            if point.thrust_g <= 0 or point.voltage_v <= 0:
                raise ValidationDataError(f"{path} row {line_no}: thrust and voltage must be > 0")
            points.append(point)
    return points


def predict_point(
    db: Database, point: ReferencePoint, assumptions: Assumptions | None = None
) -> tuple[float, float]:
    """Predicted (battery current A, battery power W) for one reference point."""
    assumptions = assumptions or Assumptions()
    motor = db.get("motors", point.motor_id)
    prop = db.get("props", point.prop_id)
    atm = atmosphere(point.altitude_m, point.temp_offset_c)
    mp = motor_point_for_thrust(motor, prop, point.thrust_g / 1000.0 * G, atm.density)
    power = mp.electrical_power_w / assumptions.esc_efficiency
    return power / point.voltage_v, power


def validate(
    db: Database,
    points: list[ReferencePoint] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    assumptions: Assumptions | None = None,
) -> ValidationReport:
    points = load_reference_points() if points is None else points
    comparisons: list[PointComparison] = []
    for pt in points:
        current, power = predict_point(db, pt, assumptions)
        comparisons.append(
            PointComparison(
                point=pt,
                predicted_current_a=current,
                predicted_power_w=power,
                power_error=(power - pt.power_w) / pt.power_w if pt.power_w else None,
                current_error=(current - pt.current_a) / pt.current_a if pt.current_a else None,
            )
        )

    by_combo: dict[tuple[str, str, float], list[PointComparison]] = {}
    for c in comparisons:
        by_combo.setdefault(c.point.combo, []).append(c)
    within = 0
    for group in by_combo.values():
        errs = [abs(c.power_error) for c in group if c.power_error is not None]
        if errs and max(errs) <= tolerance:
            within += 1
    power_errs = [abs(c.power_error) for c in comparisons if c.power_error is not None]
    return ValidationReport(
        comparisons=comparisons,
        tolerance=tolerance,
        combos_total=len(by_combo),
        combos_within_tolerance=within,
        mean_abs_power_error=mean(power_errs) if power_errs else None,
        criterion_met=within >= REQUIRED_COMBOS,
    )
