"""NetworkTables 4 client for robot communication.

Subscribed topics:
  FMS/mode              (string)  — "auto" | "teleop" | "disabled"
  FMSInfo/FMSControlData (int)   — bitmask; 35 = autonomous+enabled+DS attached
  HubTracker/isActive   (boolean) — true when this hub's cycle is active
  HubPractice/ledColor  (int[])  — [r, g, b] in robot_practice mode

Published topics:
  BearHub/totalCount (integer) — current active ball count
"""

from __future__ import annotations

import logging

from src.config import NT_IDENTITY
from src.leds import Color

log = logging.getLogger(__name__)


class NTClient:
    # FMSControlData bitmask values (enabled + DS attached + period bit)
    FMS_CONTROL_DATA_AUTO   = 35  # autonomous + enabled + DS attached
    FMS_CONTROL_DATA_TELEOP = 33  # teleop     + enabled + DS attached

    def __init__(self) -> None:
        self._inst = None
        self._count_pub = None
        self._fms_mode_sub = None
        self._fms_control_sub = None
        self._hub_active_sub = None
        self._practice_hub_active_sub = None
        self._seconds_until_inactive_sub = None
        self._practice_color_sub = None

    def start(self, server_address: str, identity: str = NT_IDENTITY) -> None:
        import ntcore  # type: ignore[import]  # Pi/robot dependency

        log.info("Starting NT4 client → %s (identity: %s)", server_address, identity)
        self._inst = ntcore.NetworkTableInstance.getDefault()
        self._inst.setServer(server_address)
        self._inst.startClient4(identity)

        nt = self._inst.getTable("BearHub")
        self._count_pub = nt.getIntegerTopic("totalCount").publish()

        fms = self._inst.getTable("FMS")
        self._fms_mode_sub = fms.getStringTopic("mode").subscribe("disabled")

        fms_info = self._inst.getTable("FMSInfo")
        self._fms_control_sub = fms_info.getIntegerTopic("FMSControlData").subscribe(0)

        hub = self._inst.getTable("HubTracker")
        self._hub_active_sub = hub.getBooleanTopic("isActive").subscribe(True)

        self._practice_hub_active_sub = (
            self._inst.getBooleanTopic("/Robot/m_robotContainer/hubTraker/Hub Active")
            .subscribe(False)
        )

        self._seconds_until_inactive_sub = (
            self._inst.getDoubleTopic("/Robot/m_robotContainer/hubTracker/Seconds until inactive")
            .subscribe(-1.0)
        )

        practice = self._inst.getTable("HubPractice")
        self._practice_color_sub = practice.getIntegerArrayTopic("ledColor").subscribe([])

    def stop(self) -> None:
        if self._inst is not None:
            self._inst.stopClient()
            self._inst = None
            log.info("NT4 client stopped")

    def publish_count(self, count: int) -> None:
        if self._count_pub is not None:
            self._count_pub.set(count)

    def get_seconds_until_inactive(self) -> float:
        """Return seconds until hub becomes inactive, or -1 if unavailable."""
        if self._seconds_until_inactive_sub is None:
            return -1.0
        return float(self._seconds_until_inactive_sub.get())

    def get_practice_hub_active(self) -> bool:
        """Return the hub active state from the robot's practice NT topic."""
        if self._practice_hub_active_sub is None:
            return False
        return bool(self._practice_hub_active_sub.get())

    def get_fms_control_data(self) -> int:
        """Return the raw FMSInfo/FMSControlData value (0 if unavailable)."""
        if self._fms_control_sub is None:
            return 0
        return int(self._fms_control_sub.get())

    def get_fms_mode(self) -> str:
        """Return current FMS period: 'auto', 'teleop', or 'disabled'."""
        if self._fms_mode_sub is None:
            return "disabled"
        return self._fms_mode_sub.get()

    def get_hub_active(self) -> bool:
        """Return True when this hub's scoring cycle is active."""
        if self._hub_active_sub is None:
            return True
        return self._hub_active_sub.get()

    def get_practice_led_color(self) -> Color | None:
        """Return [r, g, b] color from robot in practice mode, or None."""
        if self._practice_color_sub is None:
            return None
        arr = self._practice_color_sub.get()
        if len(arr) >= 3:
            return Color(int(arr[0]), int(arr[1]), int(arr[2]))
        return None

    @property
    def is_connected(self) -> bool:
        if self._inst is None:
            return False
        return len(self._inst.getConnections()) > 0
