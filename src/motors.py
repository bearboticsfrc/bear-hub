"""Motor control via lgpio hardware PWM.

Hardware PWM on Pi 5 is available on GPIO 12, 13, 18, 19.
throttle is a float in [-1.0, 1.0]; positive = forward, negative = reverse.

REV Spark Max expects a 50 Hz RC PWM signal:
  - 1000 µs (5.0% duty)  — full reverse
  - 1500 µs (7.5% duty)  — neutral / stopped
  - 2000 µs (10.0% duty) — full forward
"""

from __future__ import annotations

from typing import Protocol

from src.config import MOTOR_PINS

PWM_FREQUENCY: int = 50  # Hz (standard servo/ESC frequency)
_DUTY_NEUTRAL: float = 7.5  # 1500 µs at 50 Hz — Spark Max neutral
_DUTY_RANGE: float = 2.5    # ±2.5% → spans 1000–2000 µs


class MotorsProtocol(Protocol):
    def set_throttle(self, index: int, throttle: float) -> None: ...
    def stop_all(self) -> None: ...


class Motors:
    """Real motor controller — uses lgpio hardware PWM.

    ``index`` maps to the GPIO pin at ``pins[index]``.  The two Spark Max
    controllers wired to those pins receive a 50 Hz PWM signal whose pulse
    width encodes throttle.
    """

    def __init__(self, pins: list[int] = MOTOR_PINS) -> None:
        import lgpio  # type: ignore[import]

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._pins = pins
        self._active_pins: set[int] = set()

    def set_throttle(self, index: int, throttle: float) -> None:
        pin = self._pins[index]
        throttle = max(-1.0, min(1.0, throttle))
        # Map [-1, 1] → [5.0%, 10.0%] duty cycle (1 ms – 2 ms pulse at 50 Hz)
        duty = _DUTY_NEUTRAL + throttle * _DUTY_RANGE
        if pin not in self._active_pins:
            self._lgpio.gpio_claim_output(self._handle, pin)
            self._active_pins.add(pin)
        self._lgpio.tx_pwm(self._handle, pin, PWM_FREQUENCY, duty)

    def stop_all(self) -> None:
        """Park all active motors at neutral (1500 µs) and release their pins."""
        for pin in self._active_pins:
            self._lgpio.tx_pwm(self._handle, pin, PWM_FREQUENCY, _DUTY_NEUTRAL)
        self._active_pins.clear()


class NullMotors:
    """No-op motor controller used when running without hardware."""

    def set_throttle(self, index: int, throttle: float) -> None:
        pass

    def stop_all(self) -> None:
        pass
