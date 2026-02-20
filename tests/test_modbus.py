"""Tests for ModbusServer — _TrackedHoldingRegisters and is_plc_active."""

from __future__ import annotations

import time

from src.modbus import ModbusServer, _TrackedHoldingRegisters


class TestTrackedHoldingRegisters:
    def test_last_read_time_starts_at_zero(self):
        block = _TrackedHoldingRegisters(0, [0] * 10)
        assert block.last_read_time == 0.0

    def test_get_values_stamps_monotonic_time(self):
        block = _TrackedHoldingRegisters(0, [0] * 10)
        before = time.monotonic()
        block.getValues(0, 1)
        after = time.monotonic()
        assert before <= block.last_read_time <= after

    def test_get_values_returns_correct_data(self):
        block = _TrackedHoldingRegisters(0, [42, 7, 99])
        assert block.getValues(0, 1) == [42]
        assert block.getValues(1, 2) == [7, 99]

    def test_each_call_updates_time(self):
        block = _TrackedHoldingRegisters(0, [0] * 10)
        block.getValues(0, 1)
        first = block.last_read_time
        time.sleep(0.01)
        block.getValues(0, 1)
        assert block.last_read_time > first


class TestModbusServerIsPlcActive:
    def test_is_plc_active_false_initially(self):
        server = ModbusServer()
        assert not server.is_plc_active

    def test_is_plc_active_true_after_recent_read(self):
        server = ModbusServer()
        server._hr.last_read_time = time.monotonic()
        assert server.is_plc_active

    def test_is_plc_active_false_when_stale(self):
        server = ModbusServer()
        server._hr.last_read_time = time.monotonic() - 2.0  # 2s ago > 1s timeout
        assert not server.is_plc_active

    def test_set_ball_count_does_not_trigger_is_plc_active(self):
        """Writing registers (Pi→PLC direction) should not count as a PLC read."""
        server = ModbusServer()
        server.set_ball_count(0, 42)
        assert not server.is_plc_active
