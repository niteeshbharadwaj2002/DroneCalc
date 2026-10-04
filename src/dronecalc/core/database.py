"""Component database: curated seed JSON plus user-defined custom entries.

Files live in ``data/seed`` (shipped) and ``data/custom`` (user). Each kind is one JSON list:
``motors.json``, ``props.json``, ``batteries.json``, ``escs.json``. A custom entry with the same
``id`` as a seed entry overrides it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, fields
from pathlib import Path
from statistics import median
from typing import Any

from dronecalc.config import DATA_DIR, default_custom_dir
from dronecalc.core.models import ESC, Battery, Motor, Propeller

SEED_DIR = DATA_DIR / "seed"
CUSTOM_DIR = default_custom_dir()

KINDS: dict[str, type] = {
    "motors": Motor,
    "props": Propeller,
    "batteries": Battery,
    "escs": ESC,
}


class DatabaseError(Exception):
    """Malformed database content (bad JSON, unknown/missing fields, invalid values)."""


def _build(cls: type, data: dict[str, Any], source: str):
    names = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise DatabaseError(f"{source}: unknown field(s) {unknown} for {cls.__name__}")
    try:
        return cls(**data)
    except TypeError as exc:  # missing required field
        raise DatabaseError(f"{source}: {exc}") from exc
    except ValueError as exc:
        raise DatabaseError(f"{source}: {exc}") from exc


def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatabaseError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, list):
        raise DatabaseError(f"{path}: expected a JSON list of entries")
    return data


class Database:
    def __init__(self) -> None:
        self.motors: dict[str, Motor] = {}
        self.props: dict[str, Propeller] = {}
        self.batteries: dict[str, Battery] = {}
        self.escs: dict[str, ESC] = {}
        self.custom_ids: dict[str, set] = {k: set() for k in KINDS}
        self._seed: dict[str, dict[str, Any]] = {k: {} for k in KINDS}
        self.load_warnings: list[str] = []

    # ---- construction ----------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        seed_dir: Path | None = None,
        custom_dir: Path | None = None,
        include_custom: bool = True,
    ) -> Database:
        db = cls()
        seed_dir = Path(seed_dir) if seed_dir is not None else SEED_DIR
        custom_dir = Path(custom_dir) if custom_dir is not None else CUSTOM_DIR
        for kind, model in KINDS.items():
            db._load_kind(kind, model, seed_dir / f"{kind}.json", custom=False)
            if include_custom:
                db._load_kind(kind, model, custom_dir / f"{kind}.json", custom=True)
        return db

    def _table(self, kind: str) -> dict[str, Any]:
        return getattr(self, kind)

    def _load_kind(self, kind: str, model: type, path: Path, custom: bool) -> None:
        table = self._table(kind)
        for i, raw in enumerate(_read_list(path)):
            item = _build(model, raw, f"{path.name}[{i}]")
            if item.id in table:
                if not custom:
                    raise DatabaseError(f"{path.name}: duplicate id {item.id!r}")
                self.load_warnings.append(f"custom {kind} entry {item.id!r} overrides seed entry")
            table[item.id] = item
            if custom:
                self.custom_ids[kind].add(item.id)
            else:
                self._seed[kind][item.id] = item

    # ---- queries ---------------------------------------------------------------------------

    def get(self, kind: str, entry_id: str):
        try:
            return self._table(kind)[entry_id]
        except KeyError:
            raise KeyError(f"no {kind} entry with id {entry_id!r}") from None

    def battery_groups(
        self, allowed_ids: Iterable[str] | None = None
    ) -> dict[tuple[str, int], list[Battery]]:
        """Batteries grouped by (chemistry, cell count), each sorted by ascending capacity.

        ``allowed_ids`` restricts the packs considered (``None`` means all).
        """
        allowed = None if allowed_ids is None else set(allowed_ids)
        groups: dict[tuple[str, int], list[Battery]] = {}
        for b in self.batteries.values():
            if allowed is not None and b.id not in allowed:
                continue
            groups.setdefault((b.chemistry, b.cells), []).append(b)
        for packs in groups.values():
            packs.sort(key=lambda b: (b.capacity_mah, b.id))
        return groups

    @staticmethod
    def group_specific_energy(packs: list[Battery]) -> float:
        return median(b.specific_energy_wh_per_kg for b in packs)

    # ---- custom entries --------------------------------------------------------------------

    def add_custom(self, kind: str, entry: dict[str, Any], custom_dir: Path | None = None) -> Any:
        """Validate and add a user-defined component, persisting it under ``data/custom``."""
        if kind not in KINDS:
            raise DatabaseError(f"unknown kind {kind!r}; choose from {sorted(KINDS)}")
        item = _build(KINDS[kind], entry, f"custom {kind} entry")
        self._table(kind)[item.id] = item
        self.custom_ids[kind].add(item.id)

        path = Path(custom_dir) if custom_dir is not None else CUSTOM_DIR
        path.mkdir(parents=True, exist_ok=True)
        file = path / f"{kind}.json"
        entries = [e for e in _read_list(file) if e.get("id") != item.id]
        entries.append(asdict(item))
        file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        return item

    def update_custom(
        self, kind: str, entry: dict[str, Any], custom_dir: Path | None = None
    ) -> Any:
        """Replace a custom entry with the same ``id`` (alias of ``add_custom``)."""
        return self.add_custom(kind, entry, custom_dir)

    def is_custom(self, kind: str, entry_id: str) -> bool:
        return entry_id in self.custom_ids[kind]

    def delete_custom(self, kind: str, entry_id: str, custom_dir: Path | None = None) -> None:
        """Remove a user-defined entry. A seed entry it overrode is restored; seed-only ids fail."""
        if kind not in KINDS:
            raise DatabaseError(f"unknown kind {kind!r}; choose from {sorted(KINDS)}")
        if entry_id not in self.custom_ids[kind]:
            raise DatabaseError(f"{kind} entry {entry_id!r} is not a custom entry")
        path = Path(custom_dir) if custom_dir is not None else CUSTOM_DIR
        file = path / f"{kind}.json"
        entries = [e for e in _read_list(file) if e.get("id") != entry_id]
        path.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        self.custom_ids[kind].discard(entry_id)
        table = self._table(kind)
        if entry_id in self._seed[kind]:
            table[entry_id] = self._seed[kind][entry_id]
        else:
            table.pop(entry_id, None)

    # ---- checks ----------------------------------------------------------------------------

    def check(self, fm_range: tuple[float, float] = (0.55, 0.75)) -> list[str]:
        """Plausibility warnings: implausible propeller coefficients and unverified entries."""
        warnings = list(self.load_warnings)
        lo, hi = fm_range
        for p in self.props.values():
            fm = p.figure_of_merit
            if not (lo <= fm <= hi):
                warnings.append(f"prop {p.id}: figure of merit {fm:.2f} outside {lo}-{hi}")
        for kind in KINDS:
            n_unverified = sum(1 for e in self._table(kind).values() if not e.verified)
            if n_unverified:
                warnings.append(f"{kind}: {n_unverified} entries flagged verified=false")
        return warnings
