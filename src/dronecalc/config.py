"""Central, OS-independent configuration and paths."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Project root = two levels above this file (src/dronecalc/config.py).
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

load_dotenv(ROOT_DIR / ".env")

DEBUG = os.getenv("DRONECALC_DEBUG", "0") == "1"


def user_data_dir() -> Path:
    """Per-user writable data folder (used when the app is not run from a source checkout)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DroneCalc"
    if sys.platform.startswith("win"):
        return Path(os.getenv("APPDATA", str(Path.home()))) / "DroneCalc"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "dronecalc"


def default_custom_dir() -> Path:
    """Where user-defined components are stored.

    ``DRONECALC_CUSTOM_DIR`` wins; in a source checkout (seed data next to this package) it is
    ``data/custom``; for an installed copy it is a per-user folder.
    """
    override = os.getenv("DRONECALC_CUSTOM_DIR")
    if override:
        return Path(override).expanduser()
    if (DATA_DIR / "seed").is_dir():
        return DATA_DIR / "custom"
    return user_data_dir() / "custom"
