"""Tests for BallCounter — GPIO falling-edge counting and debounce."""

from __future__ import annotations

import asyncio
import time

import pytest


class TestNullBallCounter:
    def test_start_stop_noop(self):
        from src.ball_counter import NullBallCounter

        counter = NullBallCounter()
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[int] = asyncio.Queue()
        counter.start(loop, queue)
        counter.stop()
        assert queue.empty()
        loop.close()


class TestBallCounter:
    def test_start_opens_gpio_and_registers_callbacks(self, mock_lgpio):
        from src.ball_counter import BallCounter

        counter = BallCounter(pins=[23, 24])
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[int] = asyncio.Queue()

        counter.start(loop, queue)

        mock_lgpio.gpiochip_open.assert_called_once_with(0)
        assert mock_lgpio.gpio_claim_alert.call_count == 2
        assert mock_lgpio.callback.call_count == 2
        loop.close()

    def test_stop_closes_gpio(self, mock_lgpio):
        from src.ball_counter import BallCounter

        counter = BallCounter(pins=[23])
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[int] = asyncio.Queue()
        counter.start(loop, queue)
        counter.stop()

        mock_lgpio.gpiochip_close.assert_called_once_with(99)
        loop.close()

    @pytest.mark.asyncio
    async def test_falling_edge_posts_to_queue(self, mock_lgpio):
        from src.ball_counter import BallCounter

        mock_lgpio.gpio_read.return_value = 0  # LOW = beam broken

        counter = BallCounter(pins=[23, 24, 25, 16])
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[int] = asyncio.Queue()
        counter.start(loop, queue)

        # Simulate a falling edge on pin 24 (channel index 1)
        counter._on_edge(chip=0, gpio=24, level=0, tick=0)
        await asyncio.sleep(0)  # yield to let call_soon_threadsafe fire

        assert not queue.empty()
        channel = queue.get_nowait()
        assert channel == 1  # index of pin 24 in the list

    @pytest.mark.asyncio
    async def test_debounce_suppresses_rapid_edges(self, mock_lgpio):
        from src.ball_counter import BallCounter
        from src.config import BALL_DEBOUNCE_MS

        mock_lgpio.gpio_read.return_value = 0  # LOW = beam broken

        counter = BallCounter(pins=[23])
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[int] = asyncio.Queue()
        counter.start(loop, queue)

        # First edge should pass
        counter._on_edge(chip=0, gpio=23, level=0, tick=0)
        await asyncio.sleep(0)
        assert queue.qsize() == 1

        # Second edge within debounce window should be suppressed
        counter._on_edge(chip=0, gpio=23, level=0, tick=0)
        await asyncio.sleep(0)
        assert queue.qsize() == 1  # still 1, not 2

        # Edge after debounce window should pass
        counter._last_trigger[23] = time.monotonic() - (BALL_DEBOUNCE_MS / 1000.0) - 0.001
        counter._on_edge(chip=0, gpio=23, level=0, tick=0)
        await asyncio.sleep(0)
        assert queue.qsize() == 2
