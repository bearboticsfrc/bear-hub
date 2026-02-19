"""Modbus TCP server — Pi is the slave (server), FMS PLC is the master (client).

Register map:
  Holding register 0 (addr 40001): RedHub ball count (uint16)
  Holding register 1 (addr 40002): BlueHub ball count (uint16)
  Coils: motor commands from PLC (addresses TBD)
"""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import (  # type: ignore[import]
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer  # type: ignore[import]

from src.config import MODBUS_HOST, MODBUS_PORT, MODBUS_UNIT_ID

log = logging.getLogger(__name__)


class ModbusServer:
    def __init__(self) -> None:
        hr = ModbusSequentialDataBlock(0, [0] * 10)
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

    def set_ball_count(self, register: int, count: int) -> None:
        """Write ball count to a holding register (0-based pymodbus address)."""
        self._context[MODBUS_UNIT_ID].setValues(3, register, [count])

    def get_coil(self, address: int) -> bool:
        """Read a single coil written by the FMS PLC."""
        values = self._context[MODBUS_UNIT_ID].getValues(1, address, count=1)
        return bool(values[0]) if values else False
