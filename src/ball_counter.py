"""Ball counter — detects beam-break events on GPIO falling edges.

Each sensor channel posts its index to the asyncio queue on a falling edge
(beam broken = ball scored). lgpio callbacks run in a separate thread; we
bridge into the event loop via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from src.config import BALL_DEBOUNCE_MS, BALL_SENSOR_PINS


class BallCounterProtocol(Protocol):
    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[int]) -> None: ...
    def stop(self) -> None: ...


class BallCounter:
    """Real ball counter — uses lgpio GPIO callbacks."""

    def __init__(self, pins: list[int] = BALL_SENSOR_PINS) -> None:
        self._pins = pins
        self._handle: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[int] | None = None
        # Per-channel last-trigger timestamp for software debounce
        self._last_trigger: dict[int, float] = {}

    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[int]) -> None:
        import lgpio  # type: ignore[import]

        self._loop = loop
        self._queue = queue
        self._handle = lgpio.gpiochip_open(0)

        for pin in self._pins:
            lgpio.gpio_claim_input(self._handle, pin)
            lgpio.gpio_set_debounce_micros(self._handle, pin, BALL_DEBOUNCE_MS * 1000)
            lgpio.callback(self._handle, pin, lgpio.FALLING_EDGE, self._on_edge)

    def _on_edge(self, chip: int, gpio: int, level: int, tick: int) -> None:
        now = time.monotonic()
        last = self._last_trigger.get(gpio, 0.0)
        if (now - last) * 1000 < BALL_DEBOUNCE_MS:
            return
        self._last_trigger[gpio] = now

        channel = self._pins.index(gpio) if gpio in self._pins else gpio
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, channel)

    def stop(self) -> None:
        if self._handle is not None:
            import lgpio  # type: ignore[import]

            lgpio.gpiochip_close(self._handle)
            self._handle = None


class NullBallCounter:
    """No-op ball counter used when running without hardware."""

    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[int]) -> None:
        pass

    def stop(self) -> None:
        pass
