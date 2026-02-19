"""Motor control via lgpio hardware PWM.

Hardware PWM on Pi 5 is available on GPIO 12, 13, 18, 19.
throttle is a float in [-1.0, 1.0]; positive = forward, negative = reverse.
"""

from __future__ import annotations

from typing import Protocol

PWM_FREQUENCY: int = 50  # Hz (standard servo/ESC frequency)


class MotorsProtocol(Protocol):
    def set_throttle(self, pin: int, throttle: float) -> None: ...
    def stop_all(self) -> None: ...


class Motors:
    """Real motor controller — uses lgpio hardware PWM."""

    def __init__(self) -> None:
        import lgpio  # type: ignore[import]

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._active_pins: set[int] = set()

    def set_throttle(self, pin: int, throttle: float) -> None:
        throttle = max(-1.0, min(1.0, throttle))
        # Map [-1, 1] → [5%, 10%] duty cycle (1 ms–2 ms pulse at 50 Hz)
        duty = 7.5 + throttle * 2.5  # 5.0 to 10.0
        if pin not in self._active_pins:
            self._lgpio.gpio_claim_output(self._handle, pin)
            self._active_pins.add(pin)
        self._lgpio.tx_pwm(self._handle, pin, PWM_FREQUENCY, duty)

    def stop_all(self) -> None:
        for pin in self._active_pins:
            self._lgpio.tx_pwm(self._handle, pin, PWM_FREQUENCY, 0)
        self._active_pins.clear()


class MockMotors:
    """Mock motor controller — prints calls instead of driving hardware."""

    def set_throttle(self, pin: int, throttle: float) -> None:
        print(f"[MockMotors] set_throttle(pin={pin}, throttle={throttle:.3f})")

    def stop_all(self) -> None:
        print("[MockMotors] stop_all()")
