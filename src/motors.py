"""Motor control via sysfs hardware PWM.

Uses the Pi 5 kernel PWM subsystem (/sys/class/pwm/) for a jitter-free
50 Hz signal. Requires dtoverlay=pwm-2chan in /boot/firmware/config.txt,
which maps GPIO 12 → pwm0 and GPIO 13 → pwm1 on pwmchip0.

throttle is a float in [-1.0, 1.0]; positive = forward, negative = reverse.

REV Spark Max expects a 50 Hz RC PWM signal:
  - 1,000,000 ns (1.0 ms) — full reverse
  - 1,500,000 ns (1.5 ms) — neutral / stopped
  - 2,000,000 ns (2.0 ms) — full forward
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.config import MOTOR_PINS, MOTOR_PWM_CHANNELS, PWM_CHIP

_PERIOD_NS:  int = 20_000_000  # 20 ms = 50 Hz
_NEUTRAL_NS: int =  1_500_000  # 1.5 ms — Spark Max neutral
_RANGE_NS:   int =    500_000  # ±0.5 ms → spans 1.0 ms–2.0 ms


class MotorsProtocol(Protocol):
    def set_throttle(self, index: int, throttle: float) -> None: ...
    def stop_all(self) -> None: ...


class Motors:
    """Real motor controller — uses kernel sysfs hardware PWM.

    ``pwm_root`` is injectable so tests can redirect to a temp directory
    instead of touching real hardware.
    """

    def __init__(
        self,
        pins: list[int] = MOTOR_PINS,
        pwm_root: str | Path = "/sys/class/pwm",
    ) -> None:
        self._pins = pins
        self._channels = MOTOR_PWM_CHANNELS
        self._chip = Path(pwm_root) / f"pwmchip{PWM_CHIP}"
        self._active_pins: set[int] = set()
        self._current_duty_ns: dict[int, int] = {}

    # ── sysfs helpers ────────────────────────────────────────────────────

    def _pwm_path(self, pin: int) -> Path:
        return self._chip / f"pwm{self._channels[pin]}"

    def _init_channel(self, pin: int) -> None:
        """Export the PWM channel and configure it at neutral."""
        ch = self._channels[pin]
        try:
            (self._chip / "export").write_text(str(ch))
        except OSError:
            pass  # already exported from a previous run
        p = self._pwm_path(pin)
        (p / "enable").write_text("0")
        (p / "period").write_text(str(_PERIOD_NS))
        (p / "duty_cycle").write_text(str(_NEUTRAL_NS))
        (p / "enable").write_text("1")

    def _release_channel(self, pin: int) -> None:
        """Park at neutral, disable, and unexport the PWM channel."""
        ch = self._channels[pin]
        p = self._pwm_path(pin)
        (p / "duty_cycle").write_text(str(_NEUTRAL_NS))
        (p / "enable").write_text("0")
        try:
            (self._chip / "unexport").write_text(str(ch))
        except OSError:
            pass

    # ── Public interface ─────────────────────────────────────────────────

    def set_throttle(self, index: int, throttle: float) -> None:
        pin = self._pins[index]
        throttle = max(-1.0, min(1.0, throttle))
        duty_ns = int(_NEUTRAL_NS + throttle * _RANGE_NS)

        if pin not in self._active_pins:
            self._init_channel(pin)
            self._active_pins.add(pin)
            self._current_duty_ns[pin] = _NEUTRAL_NS  # written by _init_channel

        if self._current_duty_ns.get(pin) != duty_ns:
            # Only write when duty changes — rewriting on every poll cycle
            # would restart the hardware waveform and cause ESC jitter.
            (self._pwm_path(pin) / "duty_cycle").write_text(str(duty_ns))
            self._current_duty_ns[pin] = duty_ns

    def stop_all(self) -> None:
        """Park all active motors at neutral and release hardware PWM channels."""
        for pin in self._active_pins:
            self._release_channel(pin)
        self._active_pins.clear()
        self._current_duty_ns.clear()


class NullMotors:
    """No-op motor controller used when running without hardware."""

    def set_throttle(self, index: int, throttle: float) -> None:
        pass

    def stop_all(self) -> None:
        pass
