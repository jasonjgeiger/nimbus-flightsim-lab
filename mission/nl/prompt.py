"""System prompt for the LLM NL->IR backend, built from the IR grammar."""
from __future__ import annotations

import json

from mission.ir import load_schema

_GRAMMAR = """\
You translate a drone mission described in English into Mission IR: a strict
JSON object. Output ONLY the JSON object — no prose, no markdown, no code fences.

Mission IR shape:
{
  "version": 1,
  "name": "<short label>",
  "units_in": "imperial" | "si",   // the unit system the STEP numbers use
  "defaults": {"speed_mps": 0.35, "threshold_m": 0.15, "hold_time_s": 0.5},
  "safety": {"max_altitude_m": 120, "geofence_radius_m": 100, "max_speed_mps": 0.75},
  "steps": [ ... ]
}

Steps (op + fields). Distances/angles are in units_in (imperial = feet, ft/s,
degrees; si = meters, m/s, degrees):
  {"op":"arm"} {"op":"disarm"} {"op":"takeoff"} {"op":"land"}
  {"op":"set_speed","speed":<n>}
  {"op":"goto_relative","forward":<n>,"right":<n>,"up":<n>,"hold":<s>}   // OR "down", never both up+down; right<0 = left; omit unused axes
  {"op":"climb","up":<n>}   // or "down":<n>
  {"op":"yaw_turn","degrees":<n>}   // + = clockwise/right, - = left
  {"op":"hover","seconds":<n>}
  {"op":"return_to_start"}
Reserved (use ONLY when the mission references a perceived object by name):
  {"op":"goto_target","target":"tree"}
  {"op":"hover_in_front_of","target":"tree","distance":<n>,"seconds":<n>}
  {"op":"goto_top_of","target":"tree"}

Rules:
- Always start with {"op":"arm"} then {"op":"takeoff"} if the drone must fly, and
  end with {"op":"land"} then {"op":"disarm"} unless the user clearly wants to
  stay airborne.
- "up N" means climb; "go up 100 ft" -> {"op":"climb","up":100}.
- Preserve the user's units; set units_in accordingly (default imperial).
- Do not invent safety numbers beyond the defaults unless the user states them.
- If a step cannot be expressed with the vocabulary above, use the closest
  reserved op rather than inventing a new op.
"""


def build_system_prompt() -> str:
    schema = json.dumps(load_schema(), separators=(",", ":"))
    return _GRAMMAR + "\n\nThe JSON MUST validate against this JSON Schema:\n" + schema
