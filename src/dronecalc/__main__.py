"""Entry point: `python -m dronecalc` or the `dronecalc` command."""

from dronecalc import __version__


def main() -> None:
    print(f"DroneCalc {__version__}")


if __name__ == "__main__":
    main()
