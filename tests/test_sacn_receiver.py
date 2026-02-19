"""Tests for SACNReceiver — sACN universe callback bridging into asyncio."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.leds import Color


class TestSACNReceiver:
    def test_start_creates_receiver_and_starts_it(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()

        receiver.start(loop, queue)

        mock_sacn.start.assert_called_once()
        loop.close()

    def test_start_registers_callback_on_correct_universe(self, mock_sacn):
        from src.config import SACN_UNIVERSE
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()

        receiver.start(loop, queue)

        mock_sacn.listen_on.assert_called_once_with("universe", universe=SACN_UNIVERSE)
        loop.close()

    def test_stop_calls_receiver_stop(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()

        receiver.start(loop, queue)
        receiver.stop()

        mock_sacn.stop.assert_called_once()
        assert receiver._receiver is None
        loop.close()

    def test_stop_is_noop_before_start(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        receiver.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_on_packet_posts_rgb_color_to_queue(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()
        receiver.start(loop, queue)

        packet = MagicMock()
        packet.dmxData = [255, 128, 64]
        receiver._on_packet(packet)

        await asyncio.sleep(0)
        assert queue.get_nowait() == Color(255, 128, 64)

    @pytest.mark.asyncio
    async def test_on_packet_handles_short_packet(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()
        receiver.start(loop, queue)

        packet = MagicMock()
        packet.dmxData = [100]  # only R channel present
        receiver._on_packet(packet)

        await asyncio.sleep(0)
        assert queue.get_nowait() == Color(100, 0, 0)

    @pytest.mark.asyncio
    async def test_on_packet_handles_empty_packet(self, mock_sacn):
        from src.sacn_receiver import SACNReceiver

        receiver = SACNReceiver()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Color] = asyncio.Queue()
        receiver.start(loop, queue)

        packet = MagicMock()
        packet.dmxData = []
        receiver._on_packet(packet)

        await asyncio.sleep(0)
        assert queue.get_nowait() == Color(0, 0, 0)
