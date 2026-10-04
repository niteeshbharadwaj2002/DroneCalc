#!/usr/bin/env bash
# Create/refresh the virtual environment. Works on macOS and Linux.
# Usage: ./scripts/setup.sh            (uses python3)
#        PYTHON=python3.12 ./scripts/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found. Install Python >= 3.9 (Linux: sudo apt install python3 python3-venv python3-pip)" >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"error: Python >= 3.9 required, found {sys.version.split()[0]}")
PY

# A venv copied from another OS is broken; rebuild if its python doesn't run here.
if [ -d .venv ] && ! .venv/bin/python -c "" >/dev/null 2>&1; then
  echo "Existing .venv is not usable on this system; recreating."
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv || {
    echo "error: venv creation failed. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1
  }
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .

[ -f .env ] || cp .env.example .env

echo
echo "Done. Activate with: source .venv/bin/activate"
