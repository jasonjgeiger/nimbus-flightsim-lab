"""CLI: compile a Mission IR JSON file, preview it, and (optionally) fly it.

    python -m mission mission/examples/forward_up_hover.json            # preview + confirm + fly
    python -m mission mission/examples/forward_up_hover.json --dry-run  # no drone, just log
    python -m mission mission/examples/forward_up_hover.json --yes      # skip confirmation

Point it at a running backend first:
    ./run.sh tier3   (real Betaflight SITL)   or   ./run.sh tier2   (mock)
"""
from __future__ import annotations

import argparse
import sys

from mission.executor import DryRunClient, MissionExecutor
from mission.ir import load_mission_file
from mission.validate import MissionValidationError, compile_mission, preview


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m mission", description=__doc__)
    p.add_argument("mission_file", help="path to a Mission IR JSON file")
    p.add_argument("--dry-run", action="store_true", help="log calls, do not fly")
    p.add_argument("--yes", "-y", action="store_true", help="skip confirmation prompt")
    p.add_argument(
        "--leg-timeout", type=float, default=20.0,
        help="seconds to wait for each leg to reach & hold (default 20)",
    )
    args = p.parse_args(argv)

    try:
        doc = load_mission_file(args.mission_file)
        mission = compile_mission(doc)
    except MissionValidationError as exc:
        print(f"mission rejected: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface load/parse errors cleanly
        print(f"could not load mission: {exc}", file=sys.stderr)
        return 2

    print("\n".join(preview(mission)))

    if args.dry_run:
        print("\n--- dry run ---")
        MissionExecutor(DryRunClient()).run(mission)
        return 0

    if not args.yes:
        try:
            resp = input("\nFly this mission? [y/N] ").strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("aborted (not confirmed)")
            return 1

    from nimbusos_sdk import NimbusClient

    with NimbusClient() as client:
        MissionExecutor(client, leg_timeout_s=args.leg_timeout).run(mission)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
