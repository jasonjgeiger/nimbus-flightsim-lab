#!/usr/bin/env python3
"""TCP <-> WebSocket proxy so the Betaflight web App can reach SITL.

Betaflight SITL exposes UART1 (MSP/CLI) as a *raw TCP* server on port 5761.
The current Betaflight App (app.betaflight.com, 2025.12+) is a browser PWA, and
its "Betaflight SITL" connection uses a *WebSocket* (subprotocols
``["binary", "wsSerial"]``) -- browsers cannot open raw TCP sockets. This proxy
bridges the two: it serves a WebSocket that forwards every binary frame to SITL's
TCP port and streams SITL's bytes back as binary frames.

Usage
-----
    # 1. start SITL (or `./run.sh tier3`, which supervises it)
    # 2. run this proxy
    .venv/bin/python tier3/sitl_ws_proxy.py            # ws://localhost:5762 -> tcp 127.0.0.1:5761
    .venv/bin/python tier3/sitl_ws_proxy.py --ws-port 5762 --tcp-port 5761

Then in https://app.betaflight.com (Chrome/Edge):
    Options (gear) -> enable "Enable manual connection mode"
    Port dropdown  -> "Manual" -> address:  ws://localhost:5762  -> Connect

Note: SITL keeps UART1 (5761) open the whole time, and the Tier 3 bridge only
uses it briefly for one-time config, so you can run this proxy and watch the
quad fly live in the App while `bridge.py` drives it over UDP.
"""
from __future__ import annotations

import argparse
import asyncio

try:
    import websockets
    from websockets.server import serve
except ImportError:  # pragma: no cover - friendly hint
    raise SystemExit(
        "The 'websockets' package is required: .venv/bin/python -m pip install websockets"
    )


async def _pump_tcp_to_ws(reader: asyncio.StreamReader, ws) -> None:
    """Forward raw SITL bytes to the browser as binary WebSocket frames."""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            await ws.send(data)
    except (asyncio.CancelledError, websockets.ConnectionClosed):
        pass


async def _pump_ws_to_tcp(ws, writer: asyncio.StreamWriter) -> None:
    """Forward browser WebSocket frames to SITL's raw TCP port."""
    try:
        async for message in ws:
            if isinstance(message, str):
                message = message.encode()  # SITL speaks bytes; be lenient
            writer.write(message)
            await writer.drain()
    except websockets.ConnectionClosed:
        pass


def _make_handler(tcp_host: str, tcp_port: int):
    async def handler(ws) -> None:
        peer = getattr(ws, "remote_address", None)
        print(f"[ws-proxy] browser connected {peer}; dialing {tcp_host}:{tcp_port}")
        # SITL briefly drops 5761 while the Tier 3 bridge does its one-time
        # config (BF saves -> exits -> restarts). Retry so a Connect during that
        # window doesn't hard-fail.
        reader = writer = None
        last_exc = None
        for _ in range(10):  # ~5 s
            try:
                reader, writer = await asyncio.open_connection(tcp_host, tcp_port)
                break
            except OSError as exc:
                last_exc = exc
                await asyncio.sleep(0.5)
        if writer is None:
            print(f"[ws-proxy] cannot reach SITL at {tcp_host}:{tcp_port}: {last_exc}")
            await ws.close(code=1011, reason="SITL unreachable")
            return

        t2w = asyncio.create_task(_pump_tcp_to_ws(reader, ws))
        w2t = asyncio.create_task(_pump_ws_to_tcp(ws, writer))
        try:
            done, pending = await asyncio.wait(
                {t2w, w2t}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            print("[ws-proxy] session closed")

    return handler


async def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ws-host", default="localhost", help="WebSocket bind host")
    ap.add_argument("--ws-port", type=int, default=5762, help="WebSocket listen port")
    ap.add_argument("--tcp-host", default="127.0.0.1", help="SITL TCP host")
    ap.add_argument("--tcp-port", type=int, default=5761, help="SITL UART1 TCP port")
    args = ap.parse_args()

    handler = _make_handler(args.tcp_host, args.tcp_port)
    # The App requests the "binary"/"wsSerial" subprotocols; echo one back so the
    # browser's WebSocket handshake succeeds and frames arrive as binary.
    async with serve(
        handler,
        args.ws_host,
        args.ws_port,
        subprotocols=["binary", "wsSerial"],
    ):
        print(
            f"[ws-proxy] ws://{args.ws_host}:{args.ws_port}  ->  "
            f"tcp://{args.tcp_host}:{args.tcp_port}  (SITL)"
        )
        print("[ws-proxy] In app.betaflight.com: enable manual mode, connect to "
              f"ws://{args.ws_host}:{args.ws_port}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n[ws-proxy] stopped.")
