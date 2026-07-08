"""FastAPI backend for Nimbus Mission Control (M1).

Turns English -> Mission IR -> (human confirm) -> flight, reusing the mission/
package. The app itself is the *agent*: it connects a NimbusClient to whatever
backend is already listening on the ZMQ endpoints (start one first, e.g.
`python mock_nimbus.py` for Tier 2 or `python tier3/bridge.py` for Betaflight
SITL). Switching sim<->real drone is an endpoint swap, nothing here changes.

Run:
    uvicorn webui.app:app --reload      # from the repo root
Then open http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mission.executor import MissionExecutor
from mission.nl import NLCompileError, get_compiler
from mission.validate import MissionValidationError, compile_mission, preview

# Sensible local defaults so NimbusClient talks to the local world.
os.environ.setdefault("DF_ZMQ_PUB_ENDPOINT", "tcp://127.0.0.1:7771")
os.environ.setdefault("DF_ZMQ_SUB_ENDPOINT", "tcp://127.0.0.1:7772")

_STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Nimbus Mission Control")


class CompileRequest(BaseModel):
    text: str
    backend: str | None = None  # "rules" | "llm"; default from env


class IRRequest(BaseModel):
    ir: dict[str, Any]


def _validated_preview(ir: dict[str, Any]) -> dict[str, Any]:
    """Validate an IR doc and return preview + validity, without flying."""
    try:
        mission = compile_mission(ir)
        return {"valid": True, "error": None, "preview": preview(mission)}
    except MissionValidationError as exc:
        return {"valid": False, "error": str(exc), "preview": []}
    except Exception as exc:  # structural / schema errors
        return {"valid": False, "error": str(exc), "preview": []}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "nl_backend": os.environ.get("NIMBUS_NL_BACKEND", "rules"),
        "pub": os.environ["DF_ZMQ_PUB_ENDPOINT"],
        "sub": os.environ["DF_ZMQ_SUB_ENDPOINT"],
    }


@app.post("/api/compile")
def api_compile(req: CompileRequest) -> dict[str, Any]:
    """English -> IR, then validate. Always returns the parsed IR so the user can
    see/edit it even when validation fails."""
    try:
        ir = get_compiler(req.backend).compile(req.text)
    except NLCompileError as exc:
        return {"ir": None, "valid": False, "error": f"could not understand: {exc}", "preview": []}
    except Exception as exc:  # noqa: BLE001 - surface backend errors (e.g. LLM down)
        return {"ir": None, "valid": False, "error": str(exc), "preview": []}
    result = _validated_preview(ir)
    result["ir"] = ir
    return result


@app.post("/api/preview")
def api_preview(req: IRRequest) -> dict[str, Any]:
    """Validate a (possibly hand-edited) IR doc."""
    return _validated_preview(req.ir)


@app.websocket("/ws/fly")
async def ws_fly(ws: WebSocket) -> None:
    """Receive an IR doc, validate, then fly it — streaming log lines live."""
    await ws.accept()
    try:
        msg = await ws.receive_json()
    except Exception:
        await ws.close()
        return

    ir = msg.get("ir")
    if not isinstance(ir, dict):
        await ws.send_json({"type": "error", "message": "missing 'ir'"})
        await ws.close()
        return

    try:
        mission = compile_mission(ir)
    except (MissionValidationError, Exception) as exc:  # noqa: BLE001
        await ws.send_json({"type": "error", "message": f"rejected: {exc}"})
        await ws.close()
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(line: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "log", "line": line})

    def fly() -> None:
        try:
            from nimbusos_sdk import NimbusClient

            with NimbusClient() as client:
                MissionExecutor(client, log=emit).run(mission)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})
        except Exception as exc:  # noqa: BLE001 - report to browser
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": str(exc)}
            )

    await ws.send_json({"type": "log", "line": "[web] connecting to backend and flying…"})
    thread = threading.Thread(target=fly, daemon=True)
    thread.start()

    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
            if event["type"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await ws.close()


# static assets (js/css) under /static
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
