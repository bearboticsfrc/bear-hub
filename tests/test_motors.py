"""Tests for Motors — sysfs hardware PWM duty cycle encoding and lifecycle."""

from __future__ import annotations

from src.motors import NullMotors, _NEUTRAL_NS, _PERIOD_NS, _RANGE_NS


class TestNullMotors:
    def test_set_throttle_is_noop(self):
        motors = NullMotors()
        motors.set_throttle(0, 1.0)   # must not raise
        motors.set_throttle(1, -1.0)

    def test_stop_all_is_noop(self):
        motors = NullMotors()
        motors.stop_all()  # must not raise


class TestMotors:
    def _chip(self, fake_pwm):
        from src.config import PWM_CHIP
        return fake_pwm / f"pwmchip{PWM_CHIP}"

    # ── Initialisation ───────────────────────────────────────────────────

    def test_no_channels_exported_before_set_throttle(self, fake_pwm):
        from src.motors import Motors
        Motors(pins=[12, 13], pwm_root=fake_pwm)
        assert self._chip(fake_pwm).joinpath("export").read_text() == ""

    def test_set_throttle_exports_channel_on_first_use(self, fake_pwm):
        from src.config import MOTOR_PWM_CHANNELS
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 0.0)
        assert self._chip(fake_pwm).joinpath("export").read_text() == str(MOTOR_PWM_CHANNELS[12])

    def test_set_throttle_sets_period(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 0.0)
        assert self._chip(fake_pwm).joinpath("pwm0/period").read_text() == str(_PERIOD_NS)

    def test_set_throttle_enables_channel(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 0.0)
        assert self._chip(fake_pwm).joinpath("pwm0/enable").read_text() == "1"

    # ── Duty cycle encoding ──────────────────────────────────────────────

    def test_neutral_throttle_produces_1500us(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 0.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == str(_NEUTRAL_NS)

    def test_full_forward_produces_2000us(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 1.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "2000000"

    def test_full_reverse_produces_1000us(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, -1.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "1000000"

    def test_throttle_clamped_above_1(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 2.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "2000000"

    def test_throttle_clamped_below_minus_1(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, -5.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "1000000"

    def test_intermediate_throttle(self, fake_pwm):
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(0, 0.5)
        expected = str(int(_NEUTRAL_NS + 0.5 * _RANGE_NS))
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == expected

    # ── Write-only-on-change ─────────────────────────────────────────────

    def test_duty_cycle_not_rewritten_when_unchanged(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 0.5)
        # Corrupt the file to detect any unwanted write
        self._chip(fake_pwm).joinpath("pwm0/duty_cycle").write_text("SENTINEL")
        motors.set_throttle(0, 0.5)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "SENTINEL"

    def test_duty_cycle_rewritten_when_changed(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 0.5)
        motors.set_throttle(0, 1.0)
        assert self._chip(fake_pwm).joinpath("pwm0/duty_cycle").read_text() == "2000000"

    def test_channel_not_re_exported_on_second_call(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 0.5)
        # Corrupt export file to detect any unwanted write
        self._chip(fake_pwm).joinpath("export").write_text("SENTINEL")
        motors.set_throttle(0, 0.8)
        assert self._chip(fake_pwm).joinpath("export").read_text() == "SENTINEL"

    # ── Second motor ─────────────────────────────────────────────────────

    def test_second_motor_uses_second_channel(self, fake_pwm):
        from src.config import MOTOR_PWM_CHANNELS
        from src.motors import Motors

        Motors(pins=[12, 13], pwm_root=fake_pwm).set_throttle(1, 0.0)
        chip = self._chip(fake_pwm)
        assert chip.joinpath("export").read_text() == str(MOTOR_PWM_CHANNELS[13])
        assert chip.joinpath("pwm1/duty_cycle").read_text() == str(_NEUTRAL_NS)

    # ── stop_all ─────────────────────────────────────────────────────────

    def test_stop_all_parks_motors_at_neutral(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 1.0)
        motors.set_throttle(1, -1.0)
        motors.stop_all()
        chip = self._chip(fake_pwm)
        assert chip.joinpath("pwm0/duty_cycle").read_text() == str(_NEUTRAL_NS)
        assert chip.joinpath("pwm1/duty_cycle").read_text() == str(_NEUTRAL_NS)

    def test_stop_all_disables_channels(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 1.0)
        motors.set_throttle(1, -1.0)
        motors.stop_all()
        chip = self._chip(fake_pwm)
        assert chip.joinpath("pwm0/enable").read_text() == "0"
        assert chip.joinpath("pwm1/enable").read_text() == "0"

    def test_stop_all_clears_active_so_next_call_reinits(self, fake_pwm):
        from src.motors import Motors

        motors = Motors(pins=[12, 13], pwm_root=fake_pwm)
        motors.set_throttle(0, 1.0)
        motors.stop_all()
        # Corrupt export to detect re-init
        self._chip(fake_pwm).joinpath("export").write_text("")
        motors.set_throttle(0, 0.0)
        from src.config import MOTOR_PWM_CHANNELS
        assert self._chip(fake_pwm).joinpath("export").read_text() == str(MOTOR_PWM_CHANNELS[12])
