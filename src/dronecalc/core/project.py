"""Project files (``.dronecalc.json``): the inputs of a session, never its results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dronecalc.core.models import Assumptions, Constraints, Mission
from dronecalc.core.serialize import (
    assumptions_from_dict,
    assumptions_to_dict,
    constraints_from_dict,
    constraints_to_dict,
    mission_from_dict,
    mission_to_dict,
)

PROJECT_FORMAT = "dronecalc-project"
PROJECT_VERSION = 1


class ProjectError(Exception):
    """Unreadable or incompatible project file."""


@dataclass
class Project:
    mission: Mission
    assumptions: Assumptions = field(default_factory=Assumptions)
    constraints: Constraints = field(default_factory=Constraints)
    mode: str = "forward"  # "forward" or "reverse"
    scorer: str = "flight_time"
    top_n: int = 10
    allow: dict[str, list[str] | None] = field(default_factory=dict)  # forward-mode filters
    reverse_build: dict[str, Any] | None = None  # component ids, see serialize.build_to_dict
    compare_builds: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "mode": self.mode,
            "scorer": self.scorer,
            "top_n": self.top_n,
            "mission": mission_to_dict(self.mission),
            "assumptions": assumptions_to_dict(self.assumptions),
            "constraints": constraints_to_dict(self.constraints),
            "allow": {k: (None if v is None else sorted(v)) for k, v in self.allow.items()},
            "reverse_build": self.reverse_build,
            "compare_builds": list(self.compare_builds),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
            raise ProjectError("not a DroneCalc project file")
        if int(data.get("version", 0)) > PROJECT_VERSION:
            raise ProjectError(
                f"project version {data.get('version')} is newer than this app supports"
            )
        try:
            return cls(
                mission=mission_from_dict(data["mission"]),
                assumptions=assumptions_from_dict(data.get("assumptions", {})),
                constraints=constraints_from_dict(data.get("constraints", {})),
                mode=data.get("mode", "forward"),
                scorer=data.get("scorer", "flight_time"),
                top_n=int(data.get("top_n", 10)),
                allow={
                    k: (None if v is None else list(v)) for k, v in data.get("allow", {}).items()
                },
                reverse_build=data.get("reverse_build"),
                compare_builds=list(data.get("compare_builds", [])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid project content: {exc}") from exc


def save_project(path: Path | str, project: Project) -> None:
    Path(path).write_text(json.dumps(project.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_project(path: Path | str) -> Project:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{path}: invalid JSON ({exc})") from exc
    return Project.from_dict(data)
