# BearHub — Raspberry Pi 5 Wiring Diagram

All GPIO assignments come from `src/config.py`.

---

## Raspberry Pi 5 — 40-Pin Header

Pins used by BearHub are annotated.
`[ ]` = unused &nbsp; `[*]` = used by BearHub

```
                    3.3 V  [ 1] [ 2]  5 V
                   GPIO 2  [ 3] [ 4]  5 V
                   GPIO 3  [ 5] [ 6]  GND
                   GPIO 4  [ 7] [ 8]  GPIO 14
                      GND  [ 9] [10]  GPIO 15
                  GPIO 17  [11] [12]  GPIO 18
                  GPIO 27  [13] [14]  GND
                  GPIO 22  [15] [16]  GPIO 23  [*] ← Ball Sensor Ch 0
                   3.3 V  [17] [18]  GPIO 24  [*] ← Ball Sensor Ch 1
SPI MOSI  GPIO 10  [*][19] [20]  GND
                   GPIO 9  [21] [22]  GPIO 25  [*] ← Ball Sensor Ch 2
SPI SCLK  GPIO 11  [*][23] [24]  GPIO 8
                      GND  [25] [26]  GPIO 7
                   GPIO 0  [27] [28]  GPIO 1
                   GPIO 5  [29] [30]  GND
                   GPIO 6  [31] [32]  GPIO 12  [*] ← Motor 0 PWM
Motor 1 PWM  GPIO 13 [*][33] [34]  GND
                  GPIO 19  [35] [36]  GPIO 16  [*] ← Ball Sensor Ch 3
                  GPIO 26  [37] [38]  GPIO 20
                      GND  [39] [40]  GPIO 21
```

---

## Subsystem 1 — WS2812b LED Strip (SPI)

The Pi drives the data line directly at 3.3 V over SPI MOSI at 6.5 MHz.
A 5 V → 3.3 V level shifter is **not** required here (WS2812b data input accepts 3.3 V
logic in practice; optionally add a unidirectional level shifter for long runs).

```
Raspberry Pi 5                         WS2812b Strip
─────────────────────────────────────────────────────────────────────
Pin 19  GPIO 10 (SPI0 MOSI)  ──────── DIN  (data in)
Pin 23  GPIO 11 (SPI0 SCLK)  (unused by strip, needed for SPI bus)
Pin  6  GND                  ──┐
                               ├───── GND  (common ground — REQUIRED)
External 5 V PSU  GND        ──┘
External 5 V PSU  +5 V       ──────── +5 V (power — NOT from Pi 3.3/5 V pin)
```

> **Power note:** 300 LEDs at full white draw up to 18 A at 5 V.
> Use a dedicated 5 V / 20 A power supply.
> Always tie the PSU ground to Pi ground.

---

## Subsystem 2 — Beam-Break Sensors (via Level Shifter)

Sensor outputs are 5 V logic; Pi 5 GPIO is 3.3 V only.
Use **Adafruit BSS138 4-Channel Level Shifter** (product #395) between them.

### Level Shifter Pinout (Adafruit #395)

```
        ┌──────────────────────────┐
  LV ───┤ 3.3 V ref   HV ref ├─── HV  (5 V)
 GND ───┤ GND             GND ├─── GND
 LV1 ───┤ ch1-low   ch1-high ├─── HV1
 LV2 ───┤ ch2-low   ch2-high ├─── HV2
 LV3 ───┤ ch3-low   ch3-high ├─── HV3
 LV4 ───┤ ch4-low   ch4-high ├─── HV4
        └──────────────────────────┘
```

### Connections

```
Raspberry Pi 5            Level Shifter (#395)        Beam-Break Sensor (×4)
─────────────────────────────────────────────────────────────────────────────
Pin 17  3.3 V    ───────── LV  (low-voltage ref)
Pin  1  3.3 V    (backup)
Pin  4  5 V      ───────── HV  (high-voltage ref)     VCC  (all 4 sensors)
Pin  6  GND      ───────── GND ──────────────────────  GND  (all 4 sensors)

Pin 16  GPIO 23  ─────────LV1          HV1 ──────────  OUT  Sensor Ch 0
Pin 18  GPIO 24  ─────────LV2          HV2 ──────────  OUT  Sensor Ch 1
Pin 22  GPIO 25  ─────────LV3          HV3 ──────────  OUT  Sensor Ch 2
Pin 36  GPIO 16  ─────────LV4          HV4 ──────────  OUT  Sensor Ch 3
```

> **Logic convention:** Beam intact = HIGH (5 V at sensor, 3.3 V at Pi).
> Ball breaks beam → falling edge on GPIO → count event.
> Pull-up resistors are typically built into the sensor module;
> if not, enable internal pull-ups via `lgpio`.

---

## Subsystem 3 — PWM Motor Control

Hardware PWM signals from the Pi go to a **motor controller / ESC** (not shown —
depends on motor type). The Pi outputs 3.3 V PWM logic; most ESCs and motor drivers
accept 3.3 V signal levels directly.

```
Raspberry Pi 5                         Motor Controller / ESC
─────────────────────────────────────────────────────────────
Pin 32  GPIO 12  (PWM0)  ──────────── Signal  Motor 0
Pin 33  GPIO 13  (PWM1)  ──────────── Signal  Motor 1
Pin 34  GND              ──────────── GND     (common ground)

Motor Controller           Motors (×2)
─────────────────────────────────────
External 12–24 V PSU ───── VIN
GND ─────────────────────── GND
Motor0 OUT A / OUT B ────── Motor 0 leads
Motor1 OUT A / OUT B ────── Motor 1 leads
```

> **Modbus coil map** (FMS PLC writes, Pi reads):
> - Coil 0 (`MOTOR_COIL_BASE + 0`): enable — `True` = run both motors
> - Coil 1 (`MOTOR_COIL_BASE + 1`): direction — `True` = forward, `False` = reverse

---

## Summary Table

| Signal            | Pi Physical Pin | GPIO    | Connected To                          |
|-------------------|-----------------|---------|---------------------------------------|
| SPI MOSI (LEDs)   | 19              | GPIO 10 | WS2812b DIN                          |
| SPI SCLK          | 23              | GPIO 11 | (SPI bus clock — not used by strip)  |
| Ball Sensor Ch 0  | 16              | GPIO 23 | Level shifter LV1 → Sensor 0 OUT     |
| Ball Sensor Ch 1  | 18              | GPIO 24 | Level shifter LV2 → Sensor 1 OUT     |
| Ball Sensor Ch 2  | 22              | GPIO 25 | Level shifter LV3 → Sensor 2 OUT     |
| Ball Sensor Ch 3  | 36              | GPIO 16 | Level shifter LV4 → Sensor 3 OUT     |
| Motor 0 PWM       | 32              | GPIO 12 | Motor controller signal ch 0          |
| Motor 1 PWM       | 33              | GPIO 13 | Motor controller signal ch 1          |
| 3.3 V ref         | 17              | —       | Level shifter LV                      |
| 5 V ref           | 4               | —       | Level shifter HV, sensor VCC          |
| GND               | 6, 9, 14, …     | —       | All subsystem grounds                 |
