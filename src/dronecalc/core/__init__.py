"""DroneCalc sizing core: UI-independent physics, database and sizing logic.

The names in ``__all__`` are the frozen Phase 1 public API (see docs/API.md). Front ends (CLI,
future desktop UI or web) must import from here only.
"""

from dronecalc.core.database import Database, DatabaseError
from dronecalc.core.environment import (
    Atmosphere,
    atmosphere,
    battery_temp_factor,
    density_altitude_m,
)
from dronecalc.core.evaluate import BuildResult, MassBreakdown, Violation, evaluate_build
from dronecalc.core.feasibility import SCORERS, check_constraints, rank_builds
from dronecalc.core.frame import estimate_frame_mass_kg
from dronecalc.core.models import (
    ESC,
    Assumptions,
    Battery,
    Build,
    Constraints,
    Mission,
    Motor,
    Propeller,
)
from dronecalc.core.propulsion import SolveError
from dronecalc.core.sizing import (
    ReverseResult,
    SizingError,
    SizingResult,
    assess_build,
    size_forward,
    size_reverse,
)
from dronecalc.core.validation import ValidationReport, load_reference_points, validate

API_VERSION = "1.0"

__all__ = [
    "API_VERSION",
    "ESC",
    "SCORERS",
    "Assumptions",
    "Atmosphere",
    "Battery",
    "Build",
    "BuildResult",
    "Constraints",
    "Database",
    "DatabaseError",
    "MassBreakdown",
    "Mission",
    "Motor",
    "Propeller",
    "ReverseResult",
    "SizingError",
    "SizingResult",
    "SolveError",
    "ValidationReport",
    "Violation",
    "assess_build",
    "atmosphere",
    "battery_temp_factor",
    "check_constraints",
    "density_altitude_m",
    "estimate_frame_mass_kg",
    "evaluate_build",
    "load_reference_points",
    "rank_builds",
    "size_forward",
    "size_reverse",
    "validate",
]
