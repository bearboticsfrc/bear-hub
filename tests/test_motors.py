"""Tests for Motors — PWM duty cycle encoding, throttle clamping, stop_all."""

from __future__ import annotations

from src.motors import _DUTY_NEUTRAL, _DUTY_RANGE, PWM_FREQUENCY, NullMotors


class TestNullMotors:
    def test_set_throttle_is_noop(self):
        motors = NullMotors()
        motors.set_throttle(0, 1.0)   # must not raise
        motors.set_throttle(1, -1.0)

    def test_stop_all_is_noop(self):
        motors = NullMotors()
        motors.stop_all()  # must not raise


class TestMotors:
    def test_init_opens_gpiochip(self, mock_lgpio):
        from src.motors import Motors

        Motors(pins=[12, 13])
        mock_lgpio.gpiochip_open.assert_called_once_with(0)

    def test_set_throttle_claims_output_on_first_use(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.0)
        mock_lgpio.gpio_claim_output.assert_called_once_with(99, 12)

    def test_set_throttle_does_not_reclaim_on_second_call(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.5)
        motors.set_throttle(0, 0.5)
        # gpio_claim_output should only be called once per pin
        assert mock_lgpio.gpio_claim_output.call_count == 1

    def test_tx_pwm_not_called_again_when_duty_unchanged(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.5)
        mock_lgpio.tx_pwm.reset_mock()
        # Same throttle again — must NOT call tx_pwm (would interrupt the waveform)
        motors.set_throttle(0, 0.5)
        mock_lgpio.tx_pwm.assert_not_called()

    def test_tx_pwm_called_when_duty_changes(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.5)
        mock_lgpio.tx_pwm.reset_mock()
        motors.set_throttle(0, 1.0)
        mock_lgpio.tx_pwm.assert_called_once_with(99, 12, PWM_FREQUENCY, 10.0)

    def test_neutral_throttle_produces_duty_7_5(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.0)
        mock_lgpio.tx_pwm.assert_called_with(99, 12, PWM_FREQUENCY, 7.5)

    def test_full_forward_produces_duty_10(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 1.0)
        mock_lgpio.tx_pwm.assert_called_with(99, 12, PWM_FREQUENCY, 10.0)

    def test_full_reverse_produces_duty_5(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, -1.0)
        mock_lgpio.tx_pwm.assert_called_with(99, 12, PWM_FREQUENCY, 5.0)

    def test_throttle_clamped_above_1(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 2.0)
        # 2.0 clamped to 1.0 → duty = 10.0
        mock_lgpio.tx_pwm.assert_called_with(99, 12, PWM_FREQUENCY, 10.0)

    def test_throttle_clamped_below_minus_1(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, -5.0)
        # -5.0 clamped to -1.0 → duty = 5.0
        mock_lgpio.tx_pwm.assert_called_with(99, 12, PWM_FREQUENCY, 5.0)

    def test_second_motor_uses_second_pin(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(1, 0.5)
        mock_lgpio.gpio_claim_output.assert_called_once_with(99, 13)
        expected_duty = _DUTY_NEUTRAL + 0.5 * _DUTY_RANGE
        mock_lgpio.tx_pwm.assert_called_with(99, 13, PWM_FREQUENCY, expected_duty)

    def test_stop_all_sends_neutral_to_active_pins(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 1.0)
        motors.set_throttle(1, -1.0)

        mock_lgpio.tx_pwm.reset_mock()
        motors.stop_all()

        calls = {call.args[1]: call.args[3] for call in mock_lgpio.tx_pwm.call_args_list}
        assert calls[12] == _DUTY_NEUTRAL
        assert calls[13] == _DUTY_NEUTRAL

    def test_stop_all_clears_active_pins(self, mock_lgpio):
        from src.motors import Motors

        motors = Motors(pins=[12, 13])
        motors.set_throttle(0, 0.5)
        motors.stop_all()

        mock_lgpio.gpio_claim_output.reset_mock()
        mock_lgpio.tx_pwm.reset_mock()

        # After stop_all the pin is no longer tracked — next set_throttle re-claims it
        motors.set_throttle(0, 0.0)
        mock_lgpio.gpio_claim_output.assert_called_once_with(99, 12)
