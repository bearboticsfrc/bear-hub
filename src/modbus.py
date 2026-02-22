"""Modbus TCP server — Pi is the slave (server), FMS PLC is the master (client).

Register map:
  Holding register 0 (addr 40001): RedHub ball count (uint16)   — Pi writes, PLC reads
  Holding register 1 (addr 40002): BlueHub ball count (uint16)  — Pi writes, PLC reads

  Coil map (PLC writes, Pi reads) — see config.MOTOR_COIL_BASE:
    coil 0: motor 0 enable  (True = run)
    coil 1: motor 0 forward (True = forward, False = reverse)
    coil 2: motor 1 enable
    coil 3: motor 1 forward
"""

from __future__ import annotations

import asyncio
import logging
import time

from pymodbus.datastore import (  # type: ignore[import]
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer  # type: ignore[import]

from src.config import MODBUS_HOST, MODBUS_PORT, MODBUS_UNIT_ID

log = logging.getLogger(__name__)

MODBUS_ACTIVE_TIMEOUT = 1.0  # seconds


class _TrackedHoldingRegisters(ModbusSequentialDataBlock):
    """Holding register block that records the last time getValues was called."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.last_read_time: float = 0.0

    def getValues(self, address: int, count: int = 1):  # type: ignore[override]
        self.last_read_time = time.monotonic()
        return super().getValues(address, count)


class ModbusServer:
    def __init__(self) -> None:
        self._hr = _TrackedHoldingRegisters(0, [0] * 10)
        hr = self._hr
        co = ModbusSequentialDataBlock(0, [False] * 10)
        store = ModbusDeviceContext(hr=hr, co=co)
        self._context = ModbusServerContext(devices=store, single=True)
        self._server_task: asyncio.Task | None = None
        self._server = None

    async def start(self) -> None:
        log.info("Starting Modbus TCP server on %s:%d", MODBUS_HOST, MODBUS_PORT)
        self._server_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await StartAsyncTcpServer(
                context=self._context,
                address=(MODBUS_HOST, MODBUS_PORT),
            )
        except PermissionError:
            log.error(
                "Cannot bind Modbus server on port %d — permission denied. "
                "Port 502 requires authbind: see INSTALL.md § 'Modbus port 502'.",
                MODBUS_PORT,
            )
        except Exception:
            log.exception("Modbus server error")

    async def stop(self) -> None:
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        log.info("Modbus server stopped")

    @property
    def is_plc_active(self) -> bool:
        """True if a holding register was read within the past second."""
        return (time.monotonic() - self._hr.last_read_time) < MODBUS_ACTIVE_TIMEOUT

    def set_ball_count(self, register: int, count: int) -> None:
        """Write ball count to a holding register (0-based pymodbus address)."""
        self._context[MODBUS_UNIT_ID].setValues(3, register, [count])

    def get_coil(self, address: int) -> bool:
        """Read a single coil written by the FMS PLC."""
        values = self._context[MODBUS_UNIT_ID].getValues(1, address, count=1)
        return bool(values[0]) if values else False
