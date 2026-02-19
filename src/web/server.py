"""FastAPI web server — dashboard and admin UI over HTTP + WebSocket."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from src.app import App

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app_instance: App | None = None

app = FastAPI(title="BearHub")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_connections: list[WebSocket] = []


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html)


@app.get("/admin", response_class=HTMLResponse)
async def admin() -> HTMLResponse:
    html = (STATIC_DIR / "admin.html").read_text()
    return HTMLResponse(content=html)


@app.get("/api/status")
async def get_status() -> dict:
    if app_instance is None:
        return {}
    s = app_instance.state
    return {
        "mode": s.mode,
        "active_count": s.active_count,
        "auto_count": s.auto_count,
        "inactive_count": s.inactive_count,
        "nt_connected": s.nt_connected,
        "modbus_active": s.modbus_active,
        "hub_name": app_instance.hub.name,
        "simulator_enabled": s.simulator_enabled,
    }


@app.post("/api/simulate/toggle")
async def simulate_toggle() -> dict:
    if app_instance is None:
        return {"success": False}
    enabled = await app_instance.toggle_simulator()
    return {"success": True, "simulator_enabled": enabled}


@app.post("/api/simulate/ball")
async def simulate_ball() -> dict:
    """Inject one simulated ball event — dev/test only."""
    if app_instance is None:
        return {"success": False}
    await app_instance._ball_queue.put(0)
    return {"success": True}


@app.post("/api/counts/reset")
async def reset_counts() -> dict:
    if app_instance is None:
        return {"success": False}
    await app_instance.reset_counts()
    return {"success": True}


@app.post("/api/mode")
async def set_mode(body: dict) -> dict:
    if app_instance is None:
        return {"success": False}
    mode = body.get("mode", "")
    valid = {"fms", "adhoc", "robot_teleop", "robot_practice"}
    if mode not in valid:
        return {"success": False, "error": f"Invalid mode: {mode}"}
    try:
        await app_instance.set_mode(mode)
    except Exception as exc:
        log.exception("Error switching to mode %s", mode)
        return {"success": False, "error": str(exc)}
    return {"success": True, "mode": mode}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.append(websocket)
    log.debug("WS client connected (total: %d)", len(_connections))

    # Send current state on connect
    if app_instance is not None:
        await websocket.send_json(_build_state_message(app_instance))

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _connections:
            _connections.remove(websocket)
        log.debug("WS client disconnected (total: %d)", len(_connections))


async def broadcast(message: dict) -> None:
    """Broadcast a JSON message to all connected WebSocket clients."""
    dead: list[WebSocket] = []
    for ws in list(_connections):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _connections:
            _connections.remove(ws)


def _build_state_message(a: App) -> dict:
    s = a.state
    return {
        "type": "state",
        "data": {
            "mode": s.mode,
            "active_count": s.active_count,
            "auto_count": s.auto_count,
            "inactive_count": s.inactive_count,
            "nt_connected": s.nt_connected,
            "modbus_active": s.modbus_active,
            "hub_name": a.hub.name,
            "simulator_enabled": s.simulator_enabled,
        },
    }
