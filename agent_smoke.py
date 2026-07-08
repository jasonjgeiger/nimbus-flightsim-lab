#!/usr/bin/env python3
"""Tier 1 smoke agent (README Section 5).

Publishes a minimal, known-good command sequence. Pair it with sink.py to see
the raw command frames, or with mock_nimbus.py for a full closed loop. This
exercises command sequencing and argument validation (no feedback required).
"""
from __future__ import annotations

from nimbusos_sdk import NimbusClient


def run() -> None:
    with NimbusClient() as client:
        client.publish_arm_state(True)
        client.publish_waypoint_speed(0.45)  # 0.05-0.75 m/s
        client.publish_autonomy_request("takeoff")
        client.publish_relative_waypoint(
            forward=1.5, right=0.0, down=0.0, mode="override"
        )
        client.publish_autonomy_request("land")
        client.publish_arm_state(False)
        print("[smoke] command sequence published: arm -> takeoff -> waypoint -> land -> disarm")


if __name__ == "__main__":
    run()
