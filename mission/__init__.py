"""Nimbus Mission Control — deterministic mission compiler + executor.

Pipeline: Mission IR (JSON) -> validate/normalize (SI + safety) -> execute via
NimbusClient. See docs/mission-control/ for the design and IR spec.

M0: no LLM, no web UI. Hand-written IR flies against Betaflight SITL (./run.sh
tier3) or the Tier 2 mock (./run.sh tier2), because the executor only ever talks
to nimbusos_sdk.NimbusClient.
"""

from mission.ir import (
    FEET_TO_M,
    NormalizedMission,
    NormalizedStep,
    load_mission_file,
    validate_structure,
)
from mission.validate import MissionValidationError, compile_mission, preview

__all__ = [
    "FEET_TO_M",
    "NormalizedMission",
    "NormalizedStep",
    "load_mission_file",
    "validate_structure",
    "MissionValidationError",
    "compile_mission",
    "preview",
]
