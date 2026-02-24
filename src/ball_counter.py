"""Ball counter — detects beam-break events on GPIO falling edges.

Each sensor channel posts its index to the asyncio queue on a falling edge
(beam broken = ball scored). lgpio callbacks run in a separate thread; we
bridge into the event loop via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from src.config import BALL_SENSOR_PINS


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
        self._callbacks: list = []  # must hold references or lgpio GCs them
        self._beam_broken: dict[int, bool] = {}  # True while beam is currently interrupted

    def start(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[int]) -> None:
        import lgpio  # type: ignore[import]

        self._lgpio = lgpio
        self._loop = loop
        self._queue = queue
        self._handle = lgpio.gpiochip_open(0)

        for pin in self._pins:
            lgpio.gpio_claim_alert(self._handle, pin, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP)
            cb = lgpio.callback(self._handle, pin, lgpio.BOTH_EDGES, self._on_edge)
            self._callbacks.append(cb)

    def _on_edge(self, chip: int, gpio: int, level: int, tick: int) -> None:
        is_low = (self._lgpio.gpio_read(self._handle, gpio) == 0)
        if is_low:
            if not self._beam_broken.get(gpio, False):
                self._beam_broken[gpio] = True
                channel = self._pins.index(gpio) if gpio in self._pins else gpio
                if self._loop and self._queue:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, channel)
        else:  # beam restored — re-arm for the next ball
            self._beam_broken[gpio] = False

    def stop(self) -> None:
        for cb in self._callbacks:
            cb.cancel()
        self._callbacks.clear()
        self._beam_broken.clear()
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
