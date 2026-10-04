"""Command-line front end for the DroneCalc sizing core."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from dronecalc import __version__
from dronecalc.core import (
    SCORERS,
    Assumptions,
    Build,
    Constraints,
    Database,
    DatabaseError,
    Mission,
    SolveError,
    check_constraints,
    estimate_frame_mass_kg,
    load_reference_points,
    size_forward,
    size_reverse,
    validate,
)
from dronecalc.core.validation import ValidationDataError

DISCLAIMER = (
    "All results are PREDICTED, UNVERIFIED (physics model; not flight-test validated). "
    "See docs/PHASE1_PLAN.md for assumptions and limits."
)


def _table(headers: Sequence[str], rows: list[Sequence[str]]) -> str:
    widths = (
        [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
        if rows
        else [len(h) for h in headers]
    )
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    lines += [fmt.format(*map(str, r)) for r in rows]
    return "\n".join(lines)


def _add_environment_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--altitude", type=float, default=0.0, help="site altitude, m (default 0)")
    p.add_argument("--temp-offset", type=float, default=0.0, help="ISA temperature offset, K")
    p.add_argument("--rotors", type=int, default=4, choices=[4, 6, 8])


def _add_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-hover-throttle", type=float, default=0.70)
    p.add_argument("--min-tw", type=float, default=2.0, help="minimum thrust-to-weight")
    p.add_argument("--dod", type=float, default=0.80, help="depth of discharge")
    p.add_argument("--derate", type=float, default=0.10, help="extra flight-time derate")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dronecalc", description="Multirotor sizing (Phase 1 CLI core)."
    )
    parser.add_argument("--version", action="version", version=f"DroneCalc {__version__}")
    sub = parser.add_subparsers(dest="command")

    size = sub.add_parser("size", help="forward sizing: mission requirements -> ranked builds")
    size.add_argument("--time", type=float, required=True, help="target flight time, min")
    size.add_argument("--payload", type=float, default=0.0, help="payload mass, kg")
    size.add_argument("--payload-power", type=float, default=0.0, help="payload power draw, W")
    size.add_argument("--max-mass", type=float, help="max takeoff mass, kg")
    size.add_argument("--max-budget", type=float, help="max component cost, USD")
    size.add_argument("--frame-mass", type=float, help="override frame mass, g")
    size.add_argument("--rank", choices=sorted(SCORERS), default="flight_time")
    size.add_argument("--top", type=int, default=10)
    _add_environment_args(size)
    _add_model_args(size)

    rev = sub.add_parser("reverse", help="reverse sizing: components -> flight time, max payload")
    for kind in ("motor", "prop", "battery", "esc"):
        rev.add_argument(f"--{kind}", required=True, help=f"{kind} id from the database")
    rev.add_argument("--payload", type=float, default=0.0, help="payload mass, kg")
    rev.add_argument("--payload-power", type=float, default=0.0, help="payload power draw, W")
    rev.add_argument("--frame-mass", type=float, help="frame mass, g (default: regression)")
    _add_environment_args(rev)
    _add_model_args(rev)

    dbp = sub.add_parser("db", help="inspect the component database")
    dbp.add_argument("action", choices=["list", "check"])
    dbp.add_argument("kind", nargs="?", choices=["motors", "props", "batteries", "escs"])

    sub.add_parser("gui", help="launch the desktop app (needs the 'ui' extra: PySide6, pyqtgraph)")

    val = sub.add_parser("validate", help="compare the model with reference thrust-table data")
    val.add_argument("--csv", help="reference CSV (default data/validation/reference_points.csv)")
    val.add_argument("--tolerance", type=float, default=0.15)
    val.add_argument("--json", action="store_true")
    return parser


def _assumptions(args: argparse.Namespace) -> Assumptions:
    return Assumptions(depth_of_discharge=args.dod, flight_time_derate=args.derate)


def _constraints(args: argparse.Namespace) -> Constraints:
    return Constraints(max_hover_throttle=args.max_hover_throttle, min_thrust_to_weight=args.min_tw)


def _cmd_size(args: argparse.Namespace) -> int:
    db = Database.load()
    mission = Mission(
        target_flight_time_min=args.time,
        payload_kg=args.payload,
        altitude_m=args.altitude,
        temp_offset_c=args.temp_offset,
        n_rotors=args.rotors,
        max_mass_kg=args.max_mass,
        max_budget_usd=args.max_budget,
        payload_power_w=args.payload_power,
        frame_mass_override_g=args.frame_mass,
    )
    res = size_forward(
        mission, db, _assumptions(args), _constraints(args), args.rank, top_n=args.top
    )
    if args.json:
        print(
            json.dumps(
                {
                    "label": "predicted, unverified",
                    "density_altitude_m": res.atmosphere.density_altitude_m,
                    "air_density": res.atmosphere.density,
                    "candidates": res.n_candidates,
                    "feasible": res.n_feasible,
                    "rejections": res.rejections,
                    "builds": [r.to_dict() for r in res.ranked],
                },
                indent=2,
            )
        )
        return 0 if res.ranked else 1

    atm = res.atmosphere
    print(
        f"Mission: {args.time:g} min, {args.payload:g} kg payload, {args.rotors} rotors | "
        f"{atm.altitude_m:g} m, ISA{atm.temp_offset_c:+g} K -> density {atm.density:.3f} kg/m^3 "
        f"(density altitude {round(atm.density_altitude_m):d} m)"
    )
    print(
        f"Candidate configurations: {res.n_candidates}; feasible builds: {res.n_feasible} "
        "(up to 3 real batteries per configuration)\n"
    )
    if not res.ranked:
        print("No feasible build found. Rejection reasons (count):")
        for code, n in sorted(res.rejections.items(), key=lambda kv: -kv[1]):
            print(f"  {code}: {n}")
        print(f"\n{DISCLAIMER}")
        return 1
    rows = []
    for i, r in enumerate(res.ranked, 1):
        b = r.build
        rows.append(
            (
                i,
                b.motor.id,
                b.prop.id,
                f"{b.battery.id}",
                b.esc.id,
                f"{r.total_mass_kg * 1000:.0f}",
                f"{r.hover_throttle:.0%}",
                f"{r.hover_battery_power_w:.0f}",
                f"{r.flight_time_min:.1f}",
                f"{r.thrust_to_weight:.2f}",
                f"{r.cost_usd:.0f}",
            )
        )
    print(
        _table(
            ["#", "motor", "prop", "battery", "esc", "mass g", "hover", "P W", "min", "T/W", "$"],
            rows,
        )
    )
    warns = {w for r in res.ranked for w in r.warnings}
    for w in sorted(warns):
        print(f"warning: {w}")
    print(f"\nRanked by: {args.rank}. {DISCLAIMER}")
    return 0


def _cmd_reverse(args: argparse.Namespace) -> int:
    db = Database.load()
    motor, prop = db.get("motors", args.motor), db.get("props", args.prop)
    battery, esc = db.get("batteries", args.battery), db.get("escs", args.esc)
    assumptions = _assumptions(args)
    frame_kg = estimate_frame_mass_kg(
        prop.diameter_in, args.rotors, assumptions.prop_clearance, args.frame_mass
    )
    build = Build(motor, prop, battery, esc, args.rotors, frame_kg)
    rev = size_reverse(
        build,
        args.payload,
        args.altitude,
        args.temp_offset,
        args.payload_power,
        assumptions,
        _constraints(args),
    )
    r = rev.result
    violations = check_constraints(r, _constraints(args))
    if args.json:
        out = r.to_dict()
        out["violations"] = [v.__dict__ for v in violations]
        out["max_payload_kg"] = rev.max_payload_kg
        out["limiting_factor"] = rev.limiting_factor
        out["flight_time_at_max_payload_min"] = rev.flight_time_at_max_payload_min
        print(json.dumps(out, indent=2))
        return 0
    print(f"Build: {motor.id} + {prop.id} + {battery.id} + {esc.id} ({args.rotors} rotors)")
    print(f"Frame mass {frame_kg * 1000:.0f} g | total mass {r.total_mass_kg * 1000:.0f} g")
    print(
        f"Hover at {args.payload:g} kg payload: throttle {r.hover_throttle:.0%}, "
        f"{r.hover_rpm:.0f} rpm, {r.hover_battery_power_w:.0f} W, "
        f"{r.hover_battery_current_a:.1f} A ({r.hover_c_rate:.1f}C)"
    )
    print(
        f"Flight time {r.flight_time_min:.1f} min | thrust-to-weight {r.thrust_to_weight:.2f} | "
        f"prop FM {r.figure_of_merit:.2f}"
    )
    if rev.can_fly_empty:
        extra = (
            f" (flight time {rev.flight_time_at_max_payload_min:.1f} min)"
            if rev.flight_time_at_max_payload_min is not None
            else ""
        )
        print(f"Max payload {rev.max_payload_kg:.3f} kg, limited by {rev.limiting_factor}{extra}")
    else:
        print(f"Max payload 0: build fails its limits even empty ({rev.limiting_factor})")
    for v in violations:
        print(f"violation: {v.message}")
    for w in r.warnings:
        print(f"warning: {w}")
    print(f"\n{DISCLAIMER}")
    return 0


def _cmd_db(args: argparse.Namespace) -> int:
    db = Database.load()
    if args.action == "check":
        warnings = db.check()
        print(
            f"{len(db.motors)} motors, {len(db.props)} props, {len(db.batteries)} batteries, "
            f"{len(db.escs)} ESCs loaded"
        )
        for w in warnings:
            print(f"warning: {w}")
        return 0
    kinds = [args.kind] if args.kind else ["motors", "props", "batteries", "escs"]
    for kind in kinds:
        items = list(getattr(db, kind).values())
        print(f"{kind} ({len(items)})")
        for it in items:
            print(f"  {it.id:28s} {it.name}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    db = Database.load()
    points = load_reference_points(args.csv)
    report = validate(db, points, args.tolerance)
    if args.json:
        print(
            json.dumps(
                {
                    "combos_total": report.combos_total,
                    "combos_within_tolerance": report.combos_within_tolerance,
                    "mean_abs_power_error": report.mean_abs_power_error,
                    "criterion_met": report.criterion_met,
                    "message": report.message,
                },
                indent=2,
            )
        )
    else:
        for c in report.comparisons:
            p = c.point
            err = f"{c.power_error:+.1%}" if c.power_error is not None else "n/a"
            print(
                f"{p.motor_id} + {p.prop_id} @ {p.voltage_v:g} V, {p.thrust_g:g} g: "
                f"predicted {c.predicted_power_w:.0f} W, power error {err}"
            )
        print(report.message)
    return 0 if report.criterion_met else 2


def _cmd_gui(_args: argparse.Namespace) -> int:
    try:
        from dronecalc.ui.app import main as gui_main
    except ImportError as exc:
        print(
            f"error: the desktop UI needs PySide6 and pyqtgraph ({exc}). "
            'Install with: pip install -e ".[ui]"',
            file=sys.stderr,
        )
        return 2
    return gui_main()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        print(f"DroneCalc {__version__}")
        parser.print_usage()
        return 0
    handlers = {
        "size": _cmd_size,
        "reverse": _cmd_reverse,
        "db": _cmd_db,
        "validate": _cmd_validate,
        "gui": _cmd_gui,
    }
    try:
        return handlers[args.command](args)
    except (DatabaseError, ValidationDataError, KeyError, ValueError, SolveError) as exc:
        print(f"error: {exc.args[0] if isinstance(exc, KeyError) else exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
