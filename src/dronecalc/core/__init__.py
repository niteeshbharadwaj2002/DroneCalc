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
from dronecalc.core.export import write_results_csv
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
from dronecalc.core.project import Project, ProjectError, load_project, save_project
from dronecalc.core.propulsion import SolveError
from dronecalc.core.serialize import (
    assumptions_from_dict,
    assumptions_to_dict,
    build_from_dict,
    build_to_dict,
    constraints_from_dict,
    constraints_to_dict,
    mission_from_dict,
    mission_to_dict,
)
from dronecalc.core.sizing import (
    ReverseResult,
    SizingCancelled,
    SizingError,
    SizingResult,
    assess_build,
    size_forward,
    size_reverse,
)
from dronecalc.core.sweeps import SweepPoint, sweep_altitude, sweep_payload
from dronecalc.core.validation import ValidationReport, load_reference_points, validate

API_VERSION = "1.1"

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
    "Project",
    "ProjectError",
    "Propeller",
    "ReverseResult",
    "SizingCancelled",
    "SizingError",
    "SizingResult",
    "SolveError",
    "SweepPoint",
    "ValidationReport",
    "Violation",
    "assess_build",
    "assumptions_from_dict",
    "assumptions_to_dict",
    "atmosphere",
    "battery_temp_factor",
    "build_from_dict",
    "build_to_dict",
    "check_constraints",
    "constraints_from_dict",
    "constraints_to_dict",
    "density_altitude_m",
    "estimate_frame_mass_kg",
    "evaluate_build",
    "load_project",
    "load_reference_points",
    "mission_from_dict",
    "mission_to_dict",
    "rank_builds",
    "save_project",
    "size_forward",
    "size_reverse",
    "sweep_altitude",
    "sweep_payload",
    "validate",
    "write_results_csv",
]
