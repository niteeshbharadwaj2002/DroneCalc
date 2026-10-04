"""Entry point: `python -m dronecalc` or the `dronecalc` command."""

import sys

from dronecalc.cli import main

if __name__ == "__main__":
    sys.exit(main())
