"""Entry point — resolves HubConfig, selects hw/null implementations, starts App."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="BearHub — FRC hub manager (team 4068)")
    parser.add_argument("--hub", choices=["red", "blue"], help="Force hub config")
    parser.add_argument(
        "--no-hardware",
        action="store_true",
        help="Disable all hardware (LEDs, GPIO) — use null stubs",
    )
    args = parser.parse_args()

    from src.config import (
        ENABLE_GPIO,
        ENABLE_LEDS,
        LED_COUNT,
        resolve_hub,
    )
    from src.modbus import ModbusServer
    from src.nt_client import NTClient
    from src.sacn_receiver import SACNReceiver

    hub = resolve_hub(args.hub)
    use_hw = not args.no_hardware

    log.info("Starting BearHub — hub=%s, hardware=%s", hub.name, use_hw)

    # LED strip
    if use_hw and ENABLE_LEDS:
        from src.leds import LedStrip

        leds = LedStrip(LED_COUNT)
    else:
        from src.leds import NullLedStrip

        leds = NullLedStrip()

    # GPIO
    if use_hw and ENABLE_GPIO:
        from src.ball_counter import BallCounter
        from src.motors import Motors

        ball_counter = BallCounter()
        motors = Motors()
    else:
        from src.ball_counter import NullBallCounter
        from src.motors import NullMotors

        ball_counter = NullBallCounter()
        motors = NullMotors()

    modbus = ModbusServer()
    nt_client = NTClient()
    sacn_receiver = SACNReceiver()

    from src.app import App

    application = App(
        hub=hub,
        leds=leds,
        ball_counter=ball_counter,
        motors=motors,
        modbus=modbus,
        nt_client=nt_client,
        sacn_receiver=sacn_receiver,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler() -> None:
        loop.create_task(application.shutdown())

    loop.add_signal_handler(signal.SIGINT, _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    try:
        loop.run_until_complete(application.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
