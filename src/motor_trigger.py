"""Motor trigger sensor — Banner QN18VN6LP (NPN, polarized retroreflective).

The white wire (NPN output) connects to MOTOR_TRIGGER_PIN. The internal
pull-up is enabled via lgpio SET_PULL_UP — no external resistor needed.

When the sensor activates it sinks the line to GND (falling edge). Each
falling edge posts None to the trigger queue. App consumes the queue to
auto-run motors in demo mode.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from src.config import BALL_REARM_MS, MOTOR_TRIGGER_PIN


class MotorTriggerProtocol(Protocol):
    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[None]) -> None: ...
    def stop(self) -> None: ...


class MotorTrigger:
    """Real motor trigger sensor — uses lgpio GPIO callback on a falling edge."""

    def __init__(self, pin: int = MOTOR_TRIGGER_PIN, rearm_ms: int = BALL_REARM_MS) -> None:
        self._pin = pin
        self._rearm_ms = rearm_ms
        self._handle: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[None] | None = None
        self._callbacks: list = []
        self._last_trigger_time: float = 0.0

    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[None]) -> None:
        import lgpio  # type: ignore[import]

        self._lgpio = lgpio
        self._loop = loop
        self._queue = queue
        self._handle = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_alert(self._handle, self._pin, lgpio.FALLING_EDGE, lgpio.SET_PULL_UP)
        cb = lgpio.callback(self._handle, self._pin, lgpio.FALLING_EDGE, self._on_edge)
        self._callbacks.append(cb)

    def _on_edge(self, chip: int, gpio: int, level: int, tick: int) -> None:
        now = time.monotonic()
        if (now - self._last_trigger_time) * 1000 < self._rearm_ms:
            return
        self._last_trigger_time = now
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    def stop(self) -> None:
        for cb in self._callbacks:
            cb.cancel()
        self._callbacks.clear()
        if self._handle is not None:
            import lgpio  # type: ignore[import]

            lgpio.gpiochip_close(self._handle)
            self._handle = None


class NullMotorTrigger:
    """No-op trigger used when running without hardware."""

    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[None]) -> None:
        pass

    def stop(self) -> None:
        pass
