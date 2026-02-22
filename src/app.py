"""Central application orchestrator.

Owns all subsystems, wires asyncio queues, and drives the main loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from src.config import (
    MOTOR_SPEED,
    NT_SERVER_ADDRESS,
    STATE_FILE,
    WEB_HOST,
    WEB_PORT,
    HubConfig,
)

if TYPE_CHECKING:
    from src.ball_counter import BallCounterProtocol
    from src.leds import Color, LedStripProtocol
    from src.modbus import ModbusServer
    from src.motors import MotorsProtocol
    from src.nt_client import NTClient
    from src.sacn_receiver import SACNReceiver

log = logging.getLogger(__name__)


@dataclass
class AppState:
    mode: str = "demo"
    active_count: int = 0
    auto_count: int = 0
    inactive_count: int = 0
    nt_connected: bool = False
    modbus_active: bool = False
    fms_period: str = "disabled"
    hub_is_active: bool = True
    simulator_enabled: bool = False
    nt_server_address: str = NT_SERVER_ADDRESS
    sacn_active: bool = False
    seconds_until_inactive: float = -1.0
    motors_running: bool = False
    motor_speed: float = MOTOR_SPEED
    led_color: tuple[int, int, int] = (0, 0, 0)


class App:
    def __init__(
        self,
        hub: HubConfig,
        leds: LedStripProtocol,
        ball_counter: BallCounterProtocol,
        motors: MotorsProtocol,
        modbus: ModbusServer,
        nt_client: NTClient,
        sacn_receiver: SACNReceiver,
    ) -> None:
        self.hub = hub
        self._leds = leds
        self._ball_counter = ball_counter
        self._motors = motors
        self._modbus = modbus
        self._nt = nt_client
        self._sacn = sacn_receiver

        self.state = AppState()
        self._ball_queue: asyncio.Queue[int] = asyncio.Queue()
        self._led_queue: asyncio.Queue[Color] = asyncio.Queue()
        self._shutdown_event = asyncio.Event()
        self._auto_grace_until: float = 0.0  # monotonic deadline for auto grace period
        self._hub_grace_until: float = 0.0   # monotonic deadline for hub-active grace period
        self._demo_flash_task: asyncio.Task | None = None

        self._load_state()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        # Wire web server back-reference
        from src.web import server as web_server

        web_server.app_instance = self

        # Start Modbus server
        await self._modbus.start()

        # Apply persisted mode
        await self._apply_mode(self.state.mode, loop)

        # Start web server
        config = uvicorn.Config(
            web_server.app,
            host=WEB_HOST,
            port=WEB_PORT,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        # Background tasks
        asyncio.create_task(self._process_balls())
        asyncio.create_task(self._process_leds())
        asyncio.create_task(self._status_poll())
        asyncio.create_task(self._practice_led_task())
        asyncio.create_task(self._motor_poll())

        log.info("BearHub (%s) running — web at http://%s:%d", self.hub.name, WEB_HOST, WEB_PORT)

        await self._shutdown_event.wait()

        # Graceful shutdown
        server.should_exit = True
        await server_task
        await self._do_shutdown()

    async def shutdown(self) -> None:
        log.info("Shutdown requested")
        self._shutdown_event.set()

    async def _do_shutdown(self) -> None:
        self._ball_counter.stop()
        self._motors.stop_all()
        self._sacn.stop()
        self._nt.stop()
        self._leds.clear()
        await self._modbus.stop()
        self._save_state()
        log.info("Shutdown complete")

    # ── Mode management ──────────────────────────────────────────────────

    async def set_mode(self, mode: str) -> None:
        if mode == self.state.mode:
            return
        log.info("Mode change: %s → %s", self.state.mode, mode)
        loop = asyncio.get_running_loop()

        # Stop mode-specific subsystems
        old_mode = self.state.mode
        if old_mode == "fms":
            self._sacn.stop()
            self.state.modbus_active = False
        if old_mode in ("robot_teleop", "robot_practice"):
            self._nt.stop()
            self.state.nt_connected = False

        self.state.mode = mode
        await self._apply_mode(mode, loop)
        self._save_state()
        await self._broadcast_state()

    async def _apply_mode(self, mode: str, loop: asyncio.AbstractEventLoop) -> None:
        if mode == "fms":
            try:
                self._sacn.start(loop, self._led_queue)
            except Exception:
                log.warning("sACN unavailable (dev machine?) — FMS LED control disabled")
        elif mode in ("robot_teleop", "robot_practice"):
            try:
                self._nt.start(self.state.nt_server_address, "bear-hub")
            except Exception:
                log.warning("NT unavailable (dev machine?) — robot connection disabled")
            self.state.nt_connected = False  # updated by poll

        # Ball counter always active
        self._ball_counter.start(loop, self._ball_queue)

    # ── Ball processing ──────────────────────────────────────────────────

    async def _process_balls(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                _channel = await asyncio.wait_for(self._ball_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            mode = self.state.mode
            if mode == "demo":
                self.state.active_count += 1
            else:
                fms_period = self.state.fms_period
                hub_active = self.state.hub_is_active
                if fms_period == "auto":
                    self.state.auto_count += 1
                    self.state.active_count += 1
                elif not hub_active:
                    self.state.inactive_count += 1
                else:
                    self.state.active_count += 1

            # Publish to Modbus/NT
            active_total = self.state.active_count
            if mode == "fms":
                fms_total = self.state.active_count + self.state.inactive_count
                self._modbus.set_ball_count(self.hub.modbus_ball_count_register, fms_total)
            elif mode in ("robot_teleop", "robot_practice"):
                self._nt.publish_count(active_total)

            # Update LEDs for local modes
            if mode == "demo":
                if self._demo_flash_task and not self._demo_flash_task.done():
                    self._demo_flash_task.cancel()
                self._demo_flash_task = asyncio.create_task(self._flash_demo_leds())
            elif mode == "robot_teleop":
                self._update_score_leds(active_total)

            await self._broadcast_state()

    # ── LED processing ───────────────────────────────────────────────────

    async def _process_leds(self) -> None:

        while not self._shutdown_event.is_set():
            try:
                color = await asyncio.wait_for(self._led_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._leds.set_all(color)
            self._leds.show()
            new_color = (color.r, color.g, color.b)
            if new_color != self.state.led_color:
                self.state.led_color = new_color
                await self._broadcast_state()

    def _update_score_leds(self, count: int) -> None:
        from src.config import THRESHOLD_ENERGIZED, THRESHOLD_SUPERCHARGED
        from src.leds import Color

        if count >= THRESHOLD_SUPERCHARGED:
            color = Color(0, 207, 255)  # electric blue
        elif count >= THRESHOLD_ENERGIZED:
            color = Color(255, 179, 0)  # amber
        else:
            r, g, b = self.hub.led_idle_color
            color = Color(r, g, b)
        self.state.led_color = (color.r, color.g, color.b)
        self._leds.set_all(color)
        self._leds.show()

    async def _flash_demo_leds(self) -> None:
        """Flash LEDs for 1 second on each ball scored in demo mode."""
        from src.leds import Color
        try:
            self.state.led_color = self.hub.led_idle_color
            self._leds.set_all(Color(*self.hub.led_idle_color))
            self._leds.show()
            await self._broadcast_state()
            await asyncio.sleep(1.0)
            self.state.led_color = (0, 0, 0)
            self._leds.clear()
            await self._broadcast_state()
        except asyncio.CancelledError:
            self.state.led_color = (0, 0, 0)
            self._leds.clear()
            raise

    # ── Practice LED task ────────────────────────────────────────────────

    async def _practice_led_task(self) -> None:
        """Drive LEDs in robot_practice mode at 250 ms resolution (2 Hz blink).

        Writes to LEDs directly, bypassing the led_queue. The queue is only used
        in fms mode to receive sACN colours — the two paths never overlap because
        sACN is stopped and this task sleeps whenever the mode is not robot_practice.
        """
        from src.leds import Color

        blink_on = False
        # Local grace-period timestamps give 250 ms resolution,
        # independent of the 1 s _status_poll cycle.
        auto_grace_until = 0.0
        hub_grace_until = 0.0

        while not self._shutdown_event.is_set():
            if self.state.mode != "robot_practice":
                blink_on = False
                auto_grace_until = 0.0
                hub_grace_until = 0.0
                await asyncio.sleep(0.25)
                continue

            hub_color = Color(*self.hub.led_idle_color)
            now = time.monotonic()
            control = self._nt.get_fms_control_data()

            # Period with 3 s auto grace period
            if control == self._nt.FMS_CONTROL_DATA_AUTO:
                auto_grace_until = now + 3.0
                fms_period = "auto"
            elif now < auto_grace_until:
                fms_period = "auto"
            elif control == self._nt.FMS_CONTROL_DATA_TELEOP:
                fms_period = "teleop"
            else:
                fms_period = "disabled"

            # Hub active with 3 s grace period
            if self._nt.get_practice_hub_active():
                hub_grace_until = now + 3.0
                hub_active = True
            else:
                hub_active = now < hub_grace_until

            if fms_period == "auto" or (fms_period == "teleop" and hub_active):
                seconds_left = self._nt.get_seconds_until_inactive()
                should_blink = fms_period == "teleop" and 0 <= seconds_left <= 3
                if should_blink:
                    blink_on = not blink_on
                    active_color = hub_color if blink_on else Color(0, 0, 0)
                    self._leds.set_all(active_color)
                    new_led_color = (active_color.r, active_color.g, active_color.b)
                else:
                    blink_on = False
                    self._leds.set_all(hub_color)
                    new_led_color = (hub_color.r, hub_color.g, hub_color.b)
                self._leds.show()
            else:
                blink_on = False
                self._leds.clear()
                new_led_color = (0, 0, 0)

            if new_led_color != self.state.led_color:
                self.state.led_color = new_led_color
                await self._broadcast_state()

            await asyncio.sleep(0.25)

    # ── Status polling ───────────────────────────────────────────────────

    async def _status_poll(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1.0)

            if self.state.mode in ("robot_teleop", "robot_practice"):
                connected = self._nt.is_connected
                if connected != self.state.nt_connected:
                    self.state.nt_connected = connected
                    await self._broadcast_state()

                hub_active = self._nt.get_hub_active()

                if self.state.mode == "robot_practice":
                    now = time.monotonic()
                    control = self._nt.get_fms_control_data()

                    # Period detection with 3s auto grace period
                    if control == self._nt.FMS_CONTROL_DATA_AUTO:
                        self._auto_grace_until = now + 3.0
                        fms_period = "auto"
                    elif now < self._auto_grace_until:
                        fms_period = "auto"
                    elif control == self._nt.FMS_CONTROL_DATA_TELEOP:
                        fms_period = "teleop"
                    else:
                        fms_period = "disabled"

                    # Hub active with 3s grace period
                    if self._nt.get_practice_hub_active():
                        self._hub_grace_until = now + 3.0
                        hub_active = True
                    else:
                        hub_active = now < self._hub_grace_until

                else:
                    fms_period = self._nt.get_fms_mode()

                changed = (
                    fms_period != self.state.fms_period or hub_active != self.state.hub_is_active
                )
                self.state.fms_period = fms_period
                self.state.hub_is_active = hub_active

                if changed:
                    await self._broadcast_state()

            # Modbus PLC activity — green only when a holding register was read
            # within the past second (i.e. the FMS PLC is actively polling)
            modbus_active = self._modbus.is_plc_active
            if modbus_active != self.state.modbus_active:
                self.state.modbus_active = modbus_active
                await self._broadcast_state()

            # sACN activity (only meaningful in fms mode, but always poll)
            sacn_active = self._sacn.is_active
            if sacn_active != self.state.sacn_active:
                self.state.sacn_active = sacn_active
                await self._broadcast_state()

            # Seconds until inactive — broadcast each time the integer value changes
            new_seconds = (
                self._nt.get_seconds_until_inactive()
                if self.state.mode == "robot_practice"
                else -1.0
            )
            if int(new_seconds) != int(self.state.seconds_until_inactive):
                self.state.seconds_until_inactive = new_seconds
                await self._broadcast_state()

    # ── Motor polling ────────────────────────────────────────────────────

    async def _motor_poll(self) -> None:
        """Drive motors at 20 Hz from Modbus coils (fms) or NT (robot modes).

        Coil map (MOTOR_COIL_BASE + offset) — both motors share one coil pair:
          offset 0: enable  (True = run both motors)
          offset 1: forward (True = forward, False = reverse)
        NT topics: BearHub/motor{N}Throttle (double, -1.0 to 1.0)
        """
        from src.config import MOTOR_COIL_BASE, MOTOR_PINS

        num_motors = len(MOTOR_PINS)
        while not self._shutdown_event.is_set():
            await asyncio.sleep(0.05)  # 20 Hz

            throttles = [0.0] * num_motors

            if self.state.mode == "fms":
                enable = self._modbus.get_coil(MOTOR_COIL_BASE)
                forward = self._modbus.get_coil(MOTOR_COIL_BASE + 1)
                shared_throttle = (1.0 if forward else -1.0) if enable else 0.0
                throttles = [shared_throttle] * num_motors

            elif self.state.mode in ("robot_teleop", "robot_practice"):
                for i in range(num_motors):
                    throttles[i] = self._nt.get_motor_throttle(i)

            elif self.state.motors_running:
                throttles = [self.state.motor_speed] * num_motors

            for i, throttle in enumerate(throttles):
                self._motors.set_throttle(i, throttle)

    # ── Counts reset ─────────────────────────────────────────────────────

    async def reset_counts(self) -> None:
        self.state.active_count = 0
        self.state.auto_count = 0
        self.state.inactive_count = 0
        self.state.led_color = (0, 0, 0)
        if self.state.mode == "fms":
            self._modbus.set_ball_count(self.hub.modbus_ball_count_register, 0)
        elif self.state.mode in ("robot_teleop", "robot_practice"):
            self._nt.publish_count(0)
        self._leds.clear()
        await self._broadcast_state()

    # ── NT server address ────────────────────────────────────────────────

    async def set_nt_server_address(self, address: str) -> None:
        self.state.nt_server_address = address
        log.info("NT server address set to %s", address)
        if self.state.mode in ("robot_teleop", "robot_practice"):
            self._nt.stop()
            self.state.nt_connected = False
            try:
                self._nt.start(address, "bear-hub")
            except Exception:
                log.warning("NT unavailable — robot connection disabled")
        self._save_state()
        await self._broadcast_state()

    # ── Ball simulator ───────────────────────────────────────────────────

    async def toggle_simulator(self) -> bool:
        """Toggle the simulator button on/off. Returns the new state."""
        self.state.simulator_enabled = not self.state.simulator_enabled
        log.info("Ball simulator %s", "enabled" if self.state.simulator_enabled else "disabled")
        await self._broadcast_state()
        return self.state.simulator_enabled

    # ── Motors ───────────────────────────────────────────────────────────

    async def toggle_motors(self) -> bool:
        """Toggle motors on/off manually. Returns the new state."""
        self.state.motors_running = not self.state.motors_running
        log.info("Motors %s", "started" if self.state.motors_running else "stopped")
        await self._broadcast_state()
        return self.state.motors_running

    async def set_motor_speed(self, speed: float) -> None:
        """Set manual motor speed (0.0 – 1.0) and persist it."""
        self.state.motor_speed = max(0.0, min(1.0, speed))
        log.info("Motor speed set to %.2f", self.state.motor_speed)
        self._save_state()
        await self._broadcast_state()

    # ── State broadcast ──────────────────────────────────────────────────

    async def _broadcast_state(self) -> None:
        from src.web.server import _build_state_message, broadcast

        await broadcast(_build_state_message(self))

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_state(self) -> None:
        path = Path(STATE_FILE)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self.state.mode = data.get("mode", "demo")
            self.state.nt_server_address = data.get("nt_server_address", NT_SERVER_ADDRESS)
            self.state.motor_speed = float(data.get("motor_speed", MOTOR_SPEED))
        except Exception:
            log.warning("Could not load state from %s", STATE_FILE)

    def _save_state(self) -> None:
        path = Path(STATE_FILE)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "mode": self.state.mode,
                "nt_server_address": self.state.nt_server_address,
                "motor_speed": self.state.motor_speed,
            }))
        except Exception:
            log.warning("Could not save state to %s", STATE_FILE)
