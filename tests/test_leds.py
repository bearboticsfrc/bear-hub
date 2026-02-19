"""Tests for LedStrip — SPI buffer encoding, GRB byte order, preamble."""

from __future__ import annotations

import numpy as np

from src.leds import Color, NullLedStrip


class TestNullLedStrip:
    def test_all_methods_are_noop(self):
        strip = NullLedStrip()
        strip.set_pixel_color(0, Color(255, 0, 0))
        strip.set_all(Color(0, 255, 0))
        strip.show()
        strip.clear()
        strip.set_brightness(0.5)


class TestLedStrip:
    def test_preamble_is_42_zero_bytes(self, mock_spidev):
        from src.leds import LedStrip

        strip = LedStrip(led_count=1)
        assert strip._buffer[: LedStrip.PREAMBLE].sum() == 0
        assert len(strip._buffer) == LedStrip.PREAMBLE + 1 * 24

    def test_buffer_length_scales_with_led_count(self, mock_spidev):
        from src.leds import LedStrip

        for n in (1, 10, 300):
            strip = LedStrip(led_count=n)
            assert len(strip._buffer) == LedStrip.PREAMBLE + n * 24

    def test_show_sends_grb_byte_order(self, mock_spidev):
        from src.leds import LedStrip

        strip = LedStrip(led_count=1)
        strip.set_pixel_color(0, Color(r=255, g=0, b=0))
        strip.show()

        # The SPI device writebytes2 should have been called
        mock_spidev.writebytes2.assert_called()
        buf = mock_spidev.writebytes2.call_args[0][0]
        buf = np.array(buf, dtype=np.uint8)

        # Byte 0–7 in the pixel section (after preamble) encode the G channel = 0
        # All bits of G=0 → all LED_ZERO bytes
        pixel_start = LedStrip.PREAMBLE
        g_bytes = buf[pixel_start : pixel_start + 8]
        assert all(b == LedStrip.LED_ZERO for b in g_bytes), "G channel should be 0 → all LED_ZERO"

        # Bytes 8–15 encode R channel = 255
        r_bytes = buf[pixel_start + 8 : pixel_start + 16]
        assert all(b == LedStrip.LED_ONE for b in r_bytes), "R channel should be 255 → all LED_ONE"

    def test_clear_writes_clear_buffer(self, mock_spidev):
        from src.leds import LedStrip

        strip = LedStrip(led_count=4)
        strip.clear()

        mock_spidev.writebytes2.assert_called_with(strip._clear_buffer)

    def test_set_brightness_clamps_to_unit_interval(self, mock_spidev):
        from src.leds import LedStrip

        strip = LedStrip(led_count=1)
        strip.set_brightness(1.5)
        assert strip._brightness == 1.0

        strip.set_brightness(-0.5)
        assert strip._brightness == 0.0

        strip.set_brightness(0.5)
        assert strip._brightness == 0.5

    def test_brightness_scales_output(self, mock_spidev):
        from src.leds import LedStrip

        strip = LedStrip(led_count=1)
        strip.set_brightness(0.0)
        strip.set_pixel_color(0, Color(255, 255, 255))
        strip.show()

        buf = np.array(mock_spidev.writebytes2.call_args[0][0], dtype=np.uint8)
        pixel_start = LedStrip.PREAMBLE
        # With brightness=0, all pixel bytes should be LED_ZERO
        assert all(b == LedStrip.LED_ZERO for b in buf[pixel_start:])

    def test_led_one_and_led_zero_constants(self):
        from src.leds import LedStrip

        assert LedStrip.LED_ONE == 0b1111_1100
        assert LedStrip.LED_ZERO == 0b1100_0000
