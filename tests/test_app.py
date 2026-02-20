"""Tests for App — ball categorization, mode transitions, threshold detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import RED_HUB


def _make_app(hub=RED_HUB):
    """Build an App with all null/mock dependencies."""
    from src.app import App
    from src.ball_counter import NullBallCounter
    from src.leds import NullLedStrip
    from src.motors import MockMotors

    modbus = MagicMock()
    modbus.start = AsyncMock()
    modbus.stop = AsyncMock()
    modbus.set_ball_count = MagicMock()

    nt = MagicMock()
    nt.start = MagicMock()
    nt.stop = MagicMock()
    nt.publish_count = MagicMock()
    nt.is_connected = False
    nt.get_fms_mode = MagicMock(return_value="disabled")
    nt.get_hub_active = MagicMock(return_value=True)
    nt.get_practice_led_color = MagicMock(return_value=None)
    nt.get_fms_control_data = MagicMock(return_value=0)
    nt.get_practice_hub_active = MagicMock(return_value=False)
    nt.get_seconds_until_inactive = MagicMock(return_value=-1.0)
    nt.FMS_CONTROL_DATA_AUTO = 35
    nt.FMS_CONTROL_DATA_TELEOP = 33

    sacn = MagicMock()
    sacn.start = MagicMock()
    sacn.stop = MagicMock()

    app = App(
        hub=hub,
        leds=NullLedStrip(),
        ball_counter=NullBallCounter(),
        motors=MockMotors(),
        modbus=modbus,
        nt_client=nt,
        sacn_receiver=sacn,
    )
    # Start in demo mode, no persistence I/O
    app.state.mode = "demo"
    return app


# ── Ball categorization ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_mode_all_balls_go_to_active():
    app = _make_app()
    app.state.mode = "demo"

    # Inject 3 balls
    for _ in range(3):
        await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        # Process one at a time
        for _ in range(3):
            task = asyncio.create_task(app._process_balls())
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert app.state.active_count == 3
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 0


@pytest.mark.asyncio
async def test_auto_period_increments_both_active_and_auto():
    app = _make_app()
    app.state.mode = "robot_teleop"
    app.state.fms_period = "auto"

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.active_count == 1
    assert app.state.auto_count == 1
    assert app.state.inactive_count == 0


@pytest.mark.asyncio
async def test_teleop_hub_active_increments_active_only():
    app = _make_app()
    app.state.mode = "robot_teleop"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = True

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.active_count == 1
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 0


@pytest.mark.asyncio
async def test_teleop_hub_inactive_increments_inactive_only():
    app = _make_app()
    app.state.mode = "robot_teleop"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = False

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.active_count == 0
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 1


# ── Mode transitions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_mode_changes_state():
    app = _make_app()
    app.state.mode = "demo"

    with (
        patch("src.app.App._broadcast_state", new_callable=AsyncMock),
        patch("src.app.App._save_state"),
        patch("src.app.App._apply_mode", new_callable=AsyncMock),
    ):
        await app.set_mode("fms")

    assert app.state.mode == "fms"


@pytest.mark.asyncio
async def test_set_mode_noop_when_same():
    app = _make_app()
    app.state.mode = "demo"

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock) as bc:
        await app.set_mode("demo")

    bc.assert_not_called()


# ── Reset counts ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_counts_zeroes_all_counts():
    app = _make_app()
    app.state.active_count = 42
    app.state.auto_count = 15
    app.state.inactive_count = 8

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        await app.reset_counts()

    assert app.state.active_count == 0
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 0


# ── Modbus / NT publish ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fms_mode_writes_to_modbus():
    app = _make_app()
    app.state.mode = "fms"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = True

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app._modbus.set_ball_count.assert_called_with(RED_HUB.modbus_ball_count_register, 1)


@pytest.mark.asyncio
async def test_robot_teleop_mode_publishes_to_nt():
    app = _make_app()
    app.state.mode = "robot_teleop"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = True

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app._nt.publish_count.assert_called_with(1)


@pytest.mark.asyncio
async def test_fms_mode_modbus_total_includes_inactive():
    app = _make_app()
    app.state.mode = "fms"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = False  # inactive cycle

    await app._ball_queue.put(0)

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # active=0, inactive=1 → Modbus should receive 1, not 0
    assert app.state.inactive_count == 1
    assert app.state.active_count == 0
    app._modbus.set_ball_count.assert_called_with(RED_HUB.modbus_ball_count_register, 1)


# ── robot_practice ball categorization ──────────────────────────────────────


async def _process_one_ball(app):
    """Helper: inject one ball and run one _process_balls iteration."""
    await app._ball_queue.put(0)
    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._process_balls())
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_practice_auto_period_increments_auto_and_active():
    app = _make_app()
    app.state.mode = "robot_practice"
    app.state.fms_period = "auto"

    await _process_one_ball(app)

    assert app.state.active_count == 1
    assert app.state.auto_count == 1
    assert app.state.inactive_count == 0


@pytest.mark.asyncio
async def test_practice_teleop_hub_active_increments_active():
    app = _make_app()
    app.state.mode = "robot_practice"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = True

    await _process_one_ball(app)

    assert app.state.active_count == 1
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 0


@pytest.mark.asyncio
async def test_practice_teleop_hub_inactive_increments_inactive():
    app = _make_app()
    app.state.mode = "robot_practice"
    app.state.fms_period = "teleop"
    app.state.hub_is_active = False

    await _process_one_ball(app)

    assert app.state.active_count == 0
    assert app.state.auto_count == 0
    assert app.state.inactive_count == 1


# ── robot_practice grace periods (via _status_poll) ─────────────────────────


@pytest.mark.asyncio
async def test_practice_auto_grace_period_holds_fms_period():
    """fms_period stays 'auto' while _auto_grace_until is in the future."""
    import time

    app = _make_app()
    app.state.mode = "robot_practice"
    app._nt.get_fms_control_data.return_value = 0        # no longer auto
    app._nt.get_practice_hub_active.return_value = False
    app._auto_grace_until = time.monotonic() + 10.0      # grace active

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._status_poll())
        await asyncio.sleep(1.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.fms_period == "auto"


@pytest.mark.asyncio
async def test_practice_hub_grace_period_holds_hub_active():
    """hub_is_active stays True while _hub_grace_until is in the future."""
    import time

    app = _make_app()
    app.state.mode = "robot_practice"
    app._nt.get_fms_control_data.return_value = 33       # teleop
    app._nt.get_practice_hub_active.return_value = False  # hub went inactive
    app._hub_grace_until = time.monotonic() + 10.0       # grace active

    with patch("src.app.App._broadcast_state", new_callable=AsyncMock):
        task = asyncio.create_task(app._status_poll())
        await asyncio.sleep(1.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.hub_is_active is True
