"""Offline, deterministic English -> Mission IR parser.

No network, no model. Handles the common geometric mission vocabulary:
take off / land, forward|back|left|right|up|down <distance>, hover [for N s],
turn|rotate [left|right] N degrees, and cruise speed (at N ft/s | N m/s).

Perception phrases ("to the tree", "in front of it", "to the top") and
"return to start" are emitted as their reserved IR ops on purpose, so the
deterministic validator rejects them with a clear "not supported in v1" reason
rather than silently guessing.

Assumes a single unit system per mission; every captured quantity is normalized
to the detected ``units_in`` so step numbers stay consistent. For richer or
ambiguous phrasing, use the LLM backend.
"""
from __future__ import annotations

import re
from typing import Any

from mission.nl.base import (
    DEFAULT_DEFAULTS,
    DEFAULT_HOVER_S,
    DEFAULT_SAFETY,
    NLCompileError,
)

_FT_PER_M = 1.0 / 0.3048

# quantity: number + unit. Compound/metric units first so they win the match.
_QUANTITY = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(ft\s*/\s*s|feet\s+per\s+second|ft\s+per\s+second|"
    r"m\s*/\s*s|met(?:er|re)s?\s+per\s+second|"
    r"ft|feet|foot|'|met(?:er|re)s?|m)\b",
    re.IGNORECASE,
)
_SPEED_UNITS = ("ft/s", "ftpersecond", "feetpersecond", "m/s", "meterspersecond",
                "metrespersecond", "meterpersecond", "metrepersecond")

_VERTICAL_UP = re.compile(r"\b(up|rise|risi|ascend|climb|higher|gain altitude)\w*", re.I)
_VERTICAL_DOWN = re.compile(r"\b(down|descend|lower|drop|sink)\w*", re.I)
_FWD = re.compile(r"\b(forward|forwards|ahead|straight)\b", re.I)
_BACK = re.compile(r"\b(back|backward|backwards|backward|reverse|behind)\b", re.I)
_LEFT = re.compile(r"\bleft\b", re.I)
_RIGHT = re.compile(r"\bright\b", re.I)

_SEPARATORS = re.compile(r"(?:;|,|\bthen\b|\band\b)", re.I)


def _unit_kind(raw: str) -> str:
    key = re.sub(r"\s+", "", raw.lower())
    if key in _SPEED_UNITS:
        return "speed"
    return "distance"


def _is_metric(raw: str) -> bool:
    return raw.strip().lower().startswith("m") or "metre" in raw.lower() or "meter" in raw.lower()


class RuleBasedCompiler:
    """Deterministic English -> Mission IR. Implements the NLCompiler protocol."""

    def compile(self, text: str) -> dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            raise NLCompileError("empty mission text")

        imperial = self._detect_imperial(raw)
        clauses = [c.strip() for c in _SEPARATORS.split(raw) if c.strip()]

        body: list[dict[str, Any]] = []
        for clause in clauses:
            body.extend(self._parse_clause(clause, imperial))

        if not any(self._is_flight_step(s) for s in body):
            raise NLCompileError(
                f"could not parse any flight actions from: {raw!r}"
            )

        steps = self._frame(body)
        return {
            "version": 1,
            "name": (raw[:80]).strip(),
            "units_in": "imperial" if imperial else "si",
            "defaults": dict(DEFAULT_DEFAULTS),
            "safety": dict(DEFAULT_SAFETY),
            "steps": steps,
        }

    # --- helpers ------------------------------------------------------------
    def _detect_imperial(self, text: str) -> bool:
        metric = imperial = 0
        for _num, unit in _QUANTITY.findall(text):
            if _is_metric(unit) and _unit_kind(unit) == "distance":
                metric += 1
            elif _unit_kind(unit) == "distance":
                imperial += 1
        # default to imperial (the human default) on a tie or no units
        return imperial >= metric

    def _quantities(self, clause: str, imperial: bool) -> tuple[list[float], list[float]]:
        """Return (distances, speeds) normalized to the mission's unit system."""
        distances: list[float] = []
        speeds: list[float] = []
        for num, unit in _QUANTITY.findall(clause):
            val = float(num)
            metric = _is_metric(unit)
            # normalize to units_in
            if imperial and metric:
                val *= _FT_PER_M
            elif not imperial and not metric:
                val /= _FT_PER_M
            (speeds if _unit_kind(unit) == "speed" else distances).append(val)
        return distances, speeds

    def _parse_clause(self, clause: str, imperial: bool) -> list[dict[str, Any]]:
        low = clause.lower()

        # 1. perception / unsupported -> emit reserved ops (validator rejects them)
        if "in front of" in low:
            dists, _ = self._quantities(clause, imperial)
            secs = self._seconds(low)
            return [{
                "op": "hover_in_front_of",
                "target": self._target(low) or "target",
                "distance": dists[0] if dists else 1.0,
                "seconds": secs if secs is not None else DEFAULT_HOVER_S,
            }]
        if "top of" in low or "the top" in low:
            return [{"op": "goto_top_of", "target": self._target(low) or "target"}]

        # 2. return to start
        if re.search(r"\breturn\b|back to start|go home|come back|to start", low):
            return [{"op": "return_to_start"}]

        # 3. takeoff / land
        if re.search(r"take\s?off|lift ?off|launch", low):
            return [{"op": "takeoff"}]
        if re.search(r"\bland\b|touch ?down|set down", low):
            return [{"op": "land"}]

        # 4. hover / wait / hold
        if re.search(r"\bhover\b|\bwait\b|\bhold\b", low):
            secs = self._seconds(low)
            return [{"op": "hover", "seconds": secs if secs is not None else DEFAULT_HOVER_S}]

        # 5. yaw turn / rotate
        if re.search(r"\bturn\b|\brotate\b|\byaw\b|\bspin\b", low):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|degree|degrees|°)", low)
            deg = float(m.group(1)) if m else 90.0
            if _LEFT.search(low):
                deg = -abs(deg)
            return [{"op": "yaw_turn", "degrees": deg}]

        dists, speeds = self._quantities(clause, imperial)

        # 6. "to the <noun>" (a named place, not a direction) -> perception
        if re.search(r"\bto the\b", low) and not (
            _VERTICAL_UP.search(low) or _VERTICAL_DOWN.search(low)
            or _FWD.search(low) or _BACK.search(low)
            or _LEFT.search(low) or _RIGHT.search(low)
        ):
            return [{"op": "goto_target", "target": self._target(low) or "target"}]

        # 7. pure speed clause ("at 2 ft/s", "speed 0.5")
        if speeds and not dists and (
            "speed" in low or " at " in f" {low} " or "/s" in low or "per second" in low
        ):
            return [{"op": "set_speed", "speed": speeds[0]}]

        # 8. movement (direction + distance)
        step = self._movement(low, dists, speeds)
        return [step] if step else []

    def _movement(
        self, low: str, dists: list[float], speeds: list[float]
    ) -> dict[str, Any] | None:
        if not dists:
            return None
        d = dists[0]
        step: dict[str, Any] = {}
        if _VERTICAL_UP.search(low):
            step = {"op": "climb", "up": d}
        elif _VERTICAL_DOWN.search(low):
            step = {"op": "climb", "down": d}
        elif _BACK.search(low):
            step = {"op": "goto_relative", "forward": -d}
        elif _RIGHT.search(low):
            step = {"op": "goto_relative", "right": d}
        elif _LEFT.search(low):
            step = {"op": "goto_relative", "right": -d}
        elif _FWD.search(low) or re.search(r"\b(fly|go|move|travel)\b", low):
            step = {"op": "goto_relative", "forward": d}
        else:
            return None
        if speeds:
            step["speed"] = speeds[0]
        return step

    @staticmethod
    def _seconds(low: str) -> float | None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(sec|secs|second|seconds|s)\b", low)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(min|mins|minute|minutes)\b", low)
        if m:
            return float(m.group(1)) * 60.0
        return None

    @staticmethod
    def _target(low: str) -> str | None:
        m = re.search(r"(?:to the|top of|front of)\s+(?:the\s+)?([a-z][a-z0-9\- ]*?)"
                      r"(?:\s+for\b|\s+at\b|$)", low)
        if m:
            return m.group(1).strip().split()[0]
        return None

    @staticmethod
    def _is_flight_step(step: dict[str, Any]) -> bool:
        return step.get("op") not in (None, "arm", "disarm")

    @staticmethod
    def _frame(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        has_takeoff = any(s["op"] == "takeoff" for s in body)
        has_land = any(s["op"] == "land" for s in body)
        steps: list[dict[str, Any]] = [{"op": "arm"}]
        if not has_takeoff:
            steps.append({"op": "takeoff"})
        steps.extend(body)
        if not has_land:
            steps.append({"op": "land"})
        steps.append({"op": "disarm"})
        return steps
