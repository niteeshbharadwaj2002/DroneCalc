# DroneCalc

Multirotor sizing: turns mission requirements into ranked, feasible builds (forward mode) or
predicts flight time and maximum payload for a given component set (reverse mode). Phase 1 is the
UI-independent CLI core; Phase 2 adds the PySide6 desktop app (`dronecalc gui`). Results are **predicted, unverified**. See `docs/PHASE1_PLAN.md`,
`docs/PHASE2_PLAN.md` and `docs/API.md`.

## Setup (macOS or Linux)

```bash
git clone <repo-url> DroneCalc && cd DroneCalc
./scripts/setup.sh          # creates .venv, installs deps, installs package in editable mode
source .venv/bin/activate
```

Linux prerequisite (Debian/Ubuntu): `sudo apt install python3 python3-venv python3-pip`

## Usage

```bash
make run      # python -m dronecalc
make gui      # desktop app (same as: dronecalc gui  or  dronecalc-gui)
make test     # pytest
make lint     # ruff check
```

```bash
dronecalc size --time 20 --payload 0.5 --altitude 500 --top 5        # forward sizing
dronecalc size --time 15 --payload 1 --rotors 6 --temp-offset -20 --json
dronecalc reverse --motor tmotor-mn4006-380 --prop generic-15x5.0 \
    --battery lipo-6s-10000 --esc generic-esc-40a-6s --payload 1.0   # reverse sizing
dronecalc db list motors          # inspect the component database
dronecalc validate                # compare with reference thrust tables (data/validation)
```

## Layout

```
src/dronecalc/core/   UI-independent physics, database and sizing (frozen API, see docs/API.md)
src/dronecalc/cli.py  command-line front end
src/dronecalc/ui/     PySide6 desktop app (state, workers, five screens); imports core only
tests/           pytest tests
data/seed/       curated component database (approximate, verified=false)
data/custom/     user-defined components (override seed entries by id)
data/validation/ reference thrust-table points for `dronecalc validate`
scripts/         setup and helper scripts
docs/            documentation
```

## Portability notes

- `.venv/` is git-ignored: virtual envs are OS-specific, so each machine builds its own via `scripts/setup.sh`.
- Dependencies are declared in `pyproject.toml` / `requirements*.txt`; add every new library there.
- Use `pathlib` and `dronecalc.config.ROOT_DIR` / `DATA_DIR` for file paths — no hardcoded `/Users/...` paths.
- `.gitattributes` forces LF line endings. Linux file names are case-sensitive: match import and file name case exactly.
- Configuration lives in `.env` (copy from `.env.example`; never committed).
