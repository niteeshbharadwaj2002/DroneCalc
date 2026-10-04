VENV := .venv
PY := $(VENV)/bin/python

.PHONY: setup run test lint format clean

setup:
	./scripts/setup.sh

run:
	$(PY) -m dronecalc

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

clean:
	rm -rf .pytest_cache .ruff_cache build dist src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
