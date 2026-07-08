#!/usr/bin/env python3
"""Agent that flies a Mission IR file via the deterministic executor.

Used by run.sh so a hand-written JSON mission flies against any backend:

    ./run.sh tier2 agents/fly_mission.py            # mock
    ./run.sh tier3 agents/fly_mission.py            # real Betaflight SITL
    NIMBUS_MISSION=path/to/mission.json ./run.sh tier3 agents/fly_mission.py

Non-interactive by design (run.sh has no TTY). For a confirm prompt, use
`python -m mission <file>` directly.
"""
from __future__ import annotations

import os

from nimbusos_sdk import NimbusClient

from mission.executor import MissionExecutor
from mission.ir import load_mission_file
from mission.validate import compile_mission, preview

DEFAULT_MISSION = "mission/examples/forward_up_hover.json"


def run() -> None:
    path = os.environ.get("NIMBUS_MISSION", DEFAULT_MISSION)
    mission = compile_mission(load_mission_file(path))
    print("\n".join(preview(mission)))
    with NimbusClient() as client:
        MissionExecutor(client).run(mission)


if __name__ == "__main__":
    run()
