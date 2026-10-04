# DroneCalc

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
make test     # pytest
make lint     # ruff check
```

## Layout

```
src/dronecalc/   application code (import as `import dronecalc`)
tests/           pytest tests
data/            input/output data files
scripts/         setup and helper scripts
docs/            documentation
```

## Portability notes

- `.venv/` is git-ignored: virtual envs are OS-specific, so each machine builds its own via `scripts/setup.sh`.
- Dependencies are declared in `pyproject.toml` / `requirements*.txt`; add every new library there.
- Use `pathlib` and `dronecalc.config.ROOT_DIR` / `DATA_DIR` for file paths — no hardcoded `/Users/...` paths.
- `.gitattributes` forces LF line endings. Linux file names are case-sensitive: match import and file name case exactly.
- Configuration lives in `.env` (copy from `.env.example`; never committed).
