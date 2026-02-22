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
        "nt_server_address": s.nt_server_address,
        "sacn_active": s.sacn_active,
        "fms_period": s.fms_period,
        "seconds_until_inactive": s.seconds_until_inactive,
        "motors_running": s.motors_running,
        "motor_speed": s.motor_speed,
        "led_color": "#{:02x}{:02x}{:02x}".format(*s.led_color),
    }


@app.get("/api/network/eth0")
async def get_eth0() -> dict:
    from src.network import get_eth0_address
    address = get_eth0_address()
    default = app_instance.hub.default_eth0_address if app_instance else None
    return {"address": address, "default": default}


@app.post("/api/network/eth0")
async def set_eth0(body: dict) -> dict:
    from src.network import set_eth0_address
    cidr = body.get("address", "").strip()
    if not cidr:
        return {"success": False, "error": "Address is required"}
    try:
        set_eth0_address(cidr)
    except RuntimeError as exc:
        log.warning("Failed to set eth0 address: %s", exc)
        return {"success": False, "error": str(exc)}
    return {"success": True, "address": cidr}


@app.post("/api/nt-address")
async def set_nt_address(body: dict) -> dict:
    if app_instance is None:
        return {"success": False}
    address = body.get("address", "").strip()
    if not address:
        return {"success": False, "error": "Address is required"}
    await app_instance.set_nt_server_address(address)
    return {"success": True, "address": address}


@app.post("/api/simulate/toggle")
async def simulate_toggle() -> dict:
    if app_instance is None:
        return {"success": False}
    enabled = await app_instance.toggle_simulator()
    return {"success": True, "simulator_enabled": enabled}


@app.post("/api/motors/speed")
async def motors_speed(body: dict) -> dict:
    if app_instance is None:
        return {"success": False}
    try:
        speed = float(body["speed"])
    except (KeyError, ValueError):
        return {"success": False, "error": "invalid speed"}
    await app_instance.set_motor_speed(speed)
    return {"success": True, "motor_speed": app_instance.state.motor_speed}


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
    valid = {"fms", "demo", "robot_teleop", "robot_practice"}
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
            "nt_server_address": s.nt_server_address,
            "sacn_active": s.sacn_active,
            "fms_period": s.fms_period,
            "seconds_until_inactive": s.seconds_until_inactive,
            "motors_running": s.motors_running,
            "led_color": "#{:02x}{:02x}{:02x}".format(*s.led_color),
        },
    }
