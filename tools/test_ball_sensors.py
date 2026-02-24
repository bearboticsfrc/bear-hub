#!/usr/bin/env python3
"""Standalone beam-break sensor test.

Prints a timestamped line to stdout each time a ball is detected on any channel.
Press Ctrl+C to exit.

Usage:
    python tools/test_ball_sensors.py
    python tools/test_ball_sensors.py --pins 23 24 25 16   # override pins
    python tools/test_ball_sensors.py --debounce 20        # override debounce ms
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

# Default pins from config
DEFAULT_PINS = [23, 24, 25, 16]
DEFAULT_DEBOUNCE_MS = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Beam-break sensor test")
    parser.add_argument(
        "--pins",
        type=int,
        nargs="+",
        default=DEFAULT_PINS,
        metavar="GPIO",
        help=f"GPIO pin numbers to monitor (default: {DEFAULT_PINS})",
    )
    parser.add_argument(
        "--debounce",
        type=int,
        default=DEFAULT_DEBOUNCE_MS,
        metavar="MS",
        help=f"Debounce interval in milliseconds (default: {DEFAULT_DEBOUNCE_MS})",
    )
    args = parser.parse_args()

    try:
        import lgpio  # type: ignore[import]
    except ImportError:
        print("ERROR: lgpio not installed. Run: uv pip install lgpio", file=sys.stderr)
        sys.exit(1)

    pins: list[int] = args.pins
    debounce_ms: int = args.debounce
    last_trigger: dict[int, float] = {}
    counts: dict[int, int] = {i: 0 for i in range(len(pins))}

    handle = lgpio.gpiochip_open(0)

    def on_edge(chip: int, gpio: int, level: int, tick: int) -> None:
        if lgpio.gpio_read(handle, gpio) != 0:
            return  # beam intact
        now = time.monotonic()
        if (now - last_trigger.get(gpio, 0.0)) * 1000 < debounce_ms:
            return
        last_trigger[gpio] = now

        ch = pins.index(gpio) if gpio in pins else gpio
        counts[ch] += 1
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}]  Ball detected — channel {ch}  (GPIO {gpio})  total ch{ch}: {counts[ch]}")

    callbacks = []
    for pin in pins:
        lgpio.gpio_claim_alert(handle, pin, lgpio.BOTH_EDGES)
        callbacks.append(lgpio.callback(handle, pin, lgpio.BOTH_EDGES, on_edge))

    print(f"Monitoring {len(pins)} channel(s) on GPIO pins {pins}")
    print(f"Debounce: {debounce_ms} ms   |   Press Ctrl+C to stop\n")
    print(f"{'Channel':<10} {'GPIO Pin':<12} {'Trigger'}")
    print("-" * 40)
    for i, pin in enumerate(pins):
        print(f"  ch {i:<6} GPIO {pin:<8}")
    print()

    def shutdown(sig, frame):  # noqa: ANN001
        print("\nStopping...")
        for cb in callbacks:
            cb.cancel()
        lgpio.gpiochip_close(handle)
        print("\nFinal counts:")
        for i, pin in enumerate(pins):
            print(f"  ch {i} (GPIO {pin}): {counts[i]} ball(s)")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Block forever — lgpio callbacks run in their own thread
    signal.pause()


if __name__ == "__main__":
    main()
