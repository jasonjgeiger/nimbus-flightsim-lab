#!/usr/bin/env python3
"""Tier 1 raw command sink (README Section 5).

A tiny observer that binds the command endpoint (7771) and prints every command
frame the SDK publishes. Use it to verify your agent's command sequencing and
argument validation without any simulator or feedback.

Run this in its own terminal, then run agent_smoke.py (or any agent) in another.
"""
from __future__ import annotations

import zmq

PUB_ENDPOINT = "tcp://127.0.0.1:7771"  # SDK connects here to publish commands


def main() -> None:
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.bind(PUB_ENDPOINT)  # bind where the SDK will connect to publish
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    print(f"[sink] listening for agent commands on {PUB_ENDPOINT} ... (Ctrl-C to stop)")
    try:
        while True:
            parts = sock.recv_multipart()
            topic = parts[0].decode(errors="replace")
            payload = parts[1] if len(parts) > 1 else b""
            print(f"[sink] CMD topic={topic:<18} bytes={len(payload)}")
    except KeyboardInterrupt:
        print("\n[sink] stopped.")


if __name__ == "__main__":
    main()
