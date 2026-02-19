"""WS2812b LED strip control over SPI (MOSI line bit-banging at 6.5 MHz).

Each WS2812b bit is encoded as 8 SPI bits:
  1 → 0b1111_1100 (T1H ≈ 924 ns)
  0 → 0b1100_0000 (T0H ≈ 308 ns)

Each 24-bit GRB pixel becomes 24 bytes of SPI data.
Buffer layout: 42 zero-byte preamble + led_count × 24 bytes.
"""

from __future__ import annotations

from collections import namedtuple
from typing import Protocol

import numpy as np

from src.config import LED_COUNT, SPI_BUS, SPI_DEVICE, SPI_SPEED_HZ

Color = namedtuple("Color", ["r", "g", "b"])


class LedStripProtocol(Protocol):
    def set_pixel_color(self, i: int, color: Color) -> None: ...
    def set_all(self, color: Color) -> None: ...
    def show(self) -> None: ...
    def clear(self) -> None: ...
    def set_brightness(self, brightness: float) -> None: ...


class LedStrip:
    """Real WS2812b LED strip — uses spidev."""

    LED_ZERO: int = 0b1100_0000
    LED_ONE: int = 0b1111_1100
    PREAMBLE: int = 42

    def __init__(self, led_count: int = LED_COUNT) -> None:
        from spidev import SpiDev  # type: ignore[import]

        self._led_count = led_count
        self._brightness: float = 1.0
        self._pixels: list[Color] = [Color(0, 0, 0)] * led_count

        self._device = SpiDev()
        self._device.open(SPI_BUS, SPI_DEVICE)
        self._device.max_speed_hz = SPI_SPEED_HZ
        self._device.mode = 0b00
        self._device.lsbfirst = False

        # Pre-build the "all off" clear buffer
        self._clear_buffer = np.zeros(self.PREAMBLE + led_count * 24, dtype=np.uint8)
        self._clear_buffer[self.PREAMBLE :] = np.full(led_count * 24, self.LED_ZERO, dtype=np.uint8)

        # Working buffer (preamble stays zero)
        self._buffer = np.zeros(self.PREAMBLE + led_count * 24, dtype=np.uint8)

    def set_pixel_color(self, i: int, color: Color) -> None:
        self._pixels[i] = color

    def set_all(self, color: Color) -> None:
        self._pixels = [color] * self._led_count

    def show(self) -> None:
        """Encode pixel list to SPI bytes and write to strip."""
        grb = np.array(
            [
                [
                    int(p.g * self._brightness),
                    int(p.r * self._brightness),
                    int(p.b * self._brightness),
                ]
                for p in self._pixels
            ],
            dtype=np.uint8,
        )
        self._write(grb)

    def _write(self, grb: np.ndarray) -> None:
        """Convert (N, 3) GRB array to SPI buffer and send."""
        color_bits = np.unpackbits(grb.ravel())
        self._buffer[self.PREAMBLE :] = np.where(color_bits == 1, self.LED_ONE, self.LED_ZERO)
        self._device.writebytes2(self._buffer)

    def clear(self) -> None:
        """Reset all LEDs to off immediately."""
        self._pixels = [Color(0, 0, 0)] * self._led_count
        self._device.writebytes2(self._clear_buffer)

    def set_brightness(self, brightness: float) -> None:
        self._brightness = max(0.0, min(1.0, brightness))

    @property
    def led_count(self) -> int:
        return self._led_count


class NullLedStrip:
    """No-op LED strip used when running without hardware."""

    def set_pixel_color(self, i: int, color: Color) -> None:
        pass

    def set_all(self, color: Color) -> None:
        pass

    def show(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def set_brightness(self, brightness: float) -> None:
        pass
