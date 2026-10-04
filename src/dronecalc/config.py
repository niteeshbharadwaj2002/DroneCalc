"""Central, OS-independent configuration and paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = two levels above this file (src/dronecalc/config.py).
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

load_dotenv(ROOT_DIR / ".env")

DEBUG = os.getenv("DRONECALC_DEBUG", "0") == "1"
