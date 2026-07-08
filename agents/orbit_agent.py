#!/usr/bin/env python3
"""First agent: a square-orbit flight loop (README Section 8, Step 3).

Shape: arm -> takeoff -> (fly 4 relative legs, turning 90 deg between) -> land -> disarm.

Run against mock_nimbus.py (Tier 2) for a real closed loop with typed telemetry,
or against sink.py (Tier 1) to just watch the commands.
"""
from __future__ import annotations

import math

from nimbusos_sdk import NimbusClient


def run() -> None:
    with NimbusClient() as client:
        # --- launch ---
        client.publish_arm_state(True)
        client.publish_waypoint_speed(0.35)  # 0.05-0.75 m/s
        client.publish_autonomy_request("takeoff")

        # --- act loop: fly a small square as 4 relative legs ---
        legs = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]  # (forward, right) meters
        for i, (forward, right) in enumerate(legs):
            print(f"[orbit] leg {i + 1}/4 -> forward={forward} right={right}")
            client.publish_relative_waypoint(
                forward=forward,
                right=right,
                down=0.0,
                mode="override",
                threshold_m=0.15,
                hold_time_s=0.5,
            )
            # wait for this leg to finish (bounded)
            for status in client.waypoint_status(timeout_sec=15.0):
                if status.reached and status.held:
                    print(f"[orbit]   reached (distance={status.distance_m:.2f} m)")
                    break
            client.publish_yaw_turn_command(math.pi / 2)  # turn 90 deg between legs

        # --- recover ---
        client.publish_autonomy_request("land")
        client.publish_arm_state(False)
        print("[orbit] done: landed and disarmed.")


if __name__ == "__main__":
    run()
