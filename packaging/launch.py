"""Entry point used by PyInstaller to start the DroneCalc desktop app.

``DroneCalc --self-check`` runs a headless sizing to prove the bundled data and physics work.
"""

import sys


def self_check() -> int:
    from dronecalc.core import Database, Mission, size_forward

    db = Database.load()
    res = size_forward(Mission(target_flight_time_min=20, payload_kg=0.5), db)
    print(
        f"self-check: {len(db.motors)} motors, {len(db.props)} props, {len(db.batteries)} "
        f"batteries, {len(db.escs)} ESCs; {res.n_feasible} feasible builds; "
        f"best {res.ranked[0].build.motor.id} {res.ranked[0].flight_time_min:.1f} min"
    )
    return 0 if res.ranked else 1


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(self_check())
    from dronecalc.ui.app import main

    sys.exit(main())
