#!/usr/bin/env bash
# Build a double-clickable desktop app with PyInstaller.
#   macOS  -> dist/DroneCalc.app
#   Linux  -> dist/DroneCalc/DroneCalc
# Usage: ./scripts/build_app.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "error: run ./scripts/setup.sh first" >&2; exit 1; }

"$PY" -m pip install --quiet pyinstaller

"$PY" -m PyInstaller --noconfirm --clean --windowed \
  --name DroneCalc \
  --paths src \
  --add-data "data/seed:data/seed" \
  --add-data "data/validation:data/validation" \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick \
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtMultimedia \
  --exclude-module matplotlib --exclude-module tkinter \
  packaging/launch.py

echo
if [ "$(uname)" = "Darwin" ]; then
  echo "Built dist/DroneCalc.app  (double-click it, or: open dist/DroneCalc.app)"
else
  echo "Built dist/DroneCalc/DroneCalc"
fi
