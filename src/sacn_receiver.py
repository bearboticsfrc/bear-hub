"""sACN (E1.31) receiver — active only in fms mode.

The FMS lighting system sends DMX512 data encapsulated in sACN packets.
DMX channels 1–3 (R, G, B) set all LEDs to the same solid color.

sacn.sACNreceiver() runs in its own thread; callbacks bridge into the
asyncio event loop via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
import logging
import time

import sacn  # type: ignore[import]

from src.config import SACN_UNIVERSE
from src.leds import Color

log = logging.getLogger(__name__)

SACN_ACTIVE_TIMEOUT = 10.0  # seconds


class SACNReceiver:
    def __init__(self) -> None:
        self._receiver: sacn.sACNreceiver | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._led_queue: asyncio.Queue[Color] | None = None
        self._last_packet_time: float = 0.0

    @property
    def is_active(self) -> bool:
        """True if a packet was received within the last 10 seconds."""
        return (time.monotonic() - self._last_packet_time) < SACN_ACTIVE_TIMEOUT

    def start(self, loop: asyncio.AbstractEventLoop, led_queue: asyncio.Queue[Color]) -> None:
        log.info("Starting sACN receiver on universe %d", SACN_UNIVERSE)
        self._loop = loop
        self._led_queue = led_queue
        self._receiver = sacn.sACNreceiver()
        self._receiver.listen_on("universe", universe=SACN_UNIVERSE)(self._on_packet)
        self._receiver.start()

    def _on_packet(self, packet) -> None:  # noqa: ANN001
        self._last_packet_time = time.monotonic()
        data = packet.dmxData
        r = data[0] if len(data) >= 1 else 0
        g = data[1] if len(data) >= 2 else 0
        b = data[2] if len(data) >= 3 else 0
        if self._loop and self._led_queue:
            self._loop.call_soon_threadsafe(self._led_queue.put_nowait, Color(r, g, b))

    def stop(self) -> None:
        if self._receiver is not None:
            self._receiver.stop()
            self._receiver = None
            log.info("sACN receiver stopped")
