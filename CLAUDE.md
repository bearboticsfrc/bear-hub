# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**bear-hub** is a FRC hub management program for team 4068. It runs on a Raspberry Pi 5 and supports two installations: **RedHub** and **BlueHub** (one per alliance). Each hub:
- Counts scored balls via four GPIO input channels (beam-break or IR sensors)
- Controls WS2812b LED strips via SPI
- Controls motors via PWM GPIO
- Communicates with the FMS PLC over Modbus TCP
- Publishes/subscribes to a robot via NT4 (NetworkTables 4)
- Serves a live web dashboard over WebSockets

## Tech Stack

| Role | Library |
|---|---|
| GPIO / PWM | `lgpio` (Pi 5 compatible; uses kernel GPIO char device, not `/dev/mem`) |
| WS2812b LEDs | `spidev` + `numpy` (custom bit-encoding over SPI — see Hardware Notes) |
| sACN (E1.31) | `sacn` (FMS LED control in `fms` mode) |
| Modbus TCP | `pymodbus` (async server — Pi is the Modbus slave, FMS PLC polls it) |
| NetworkTables 4 | `robotpy-ntcore` |
| Web server | `fastapi` + `uvicorn` + WebSockets |
| Async framework | `asyncio` (central event loop shared by all subsystems) |
| Package manager | `uv` |
| Linter/formatter | `ruff` |
| Tests | `pytest` + `pytest-asyncio` |

## Architecture

All subsystems are async and share a single `asyncio` event loop. Inter-subsystem communication uses `asyncio.Queue` objects to avoid tight coupling. A top-level `App` class owns all subsystems and wires the queues together.

### Hardware Abstraction

Hardware modules (`leds.py`, `ball_counter.py`, `motors.py`) each define a **Protocol** interface and two implementations: a real one and a `Null` stub that no-ops silently. This allows the app to run fully on a non-Pi dev machine.

```python
# Example pattern used in every hardware module:
class LedStripProtocol(Protocol):
    def show(self, pixels: list[Color]) -> None: ...

class LedStrip:          # real — uses spidev
    ...

class NullLedStrip:      # stub — does nothing
    def show(self, pixels: list[Color]) -> None:
        pass
```

`main.py` selects the implementation based on `config.py` flags:

```python
ENABLE_LEDS = True   # set False to use NullLedStrip
ENABLE_GPIO = True   # set False to use NullBallCounter and NullMotors
```

Alternatively, set `--no-hardware` on the CLI to disable all hardware modules at once regardless of config flags. `App` receives the resolved instances via constructor injection, keeping it hardware-agnostic and fully testable.

**Null impls vs mocks:**
- `NullLedStrip` / `NullBallCounter` / `NullMotors` — silent no-ops used when running the full app without hardware (dev machine, CI). No assertions possible.
- Tests use `unittest.mock.MagicMock` (or `AsyncMock`) patching `lgpio`, `spidev`, `sacn`, and `ntcore` at the library level, so behavior can be asserted (e.g. verify the correct bytes were written to SPI, or the correct register value was set).

```
src/
  main.py            # Entry point — resolves HubConfig, selects hw/null impls, creates App
  app.py             # App class — wires subsystems together, owns queues
  config.py          # HubConfig dataclass, RED_HUB/BLUE_HUB instances, ENABLE_* flags
  ball_counter.py    # BallCounter (lgpio) + NullBallCounter + BallCounterProtocol
  leds.py            # LedStrip (spidev) + NullLedStrip + LedStripProtocol
  motors.py          # Motors (lgpio PWM) + NullMotors + MotorsProtocol
  modbus.py          # pymodbus async server — exposes holding registers and coils to FMS PLC
  sacn_receiver.py   # sacn E1.31 receiver — active only in fms mode, feeds led queue
  nt_client.py       # robotpy-ntcore client — publishes scores, subscribes to commands
  web/
    server.py        # FastAPI app with WebSocket endpoint
    static/          # JS, CSS, 4068Gear.jpeg
    templates/       # Jinja2 HTML templates
tests/
  conftest.py        # Fixtures — mocks lgpio, spidev, sacn, NT at the library level
  test_ball_counter.py
  test_leds.py
  ...
pyproject.toml
```

### Operating Modes

The app runs in one of four modes, selected via the admin web page and persisted to disk:

| Mode | Ball Count | LEDs | Motors | Modbus | NT |
|---|---|---|---|---|---|
| `fms` | written to Modbus holding register (FMS PLC reads it) | driven by FMS via sACN | read from Modbus coils (FMS PLC writes them) | active | inactive |
| `adhoc` | web dashboard only | local scoring animation | idle | inactive | inactive |
| `robot_teleop` | web dashboard + NT | local scoring animation | NT-controlled | inactive | active |
| `robot_practice` | web dashboard + NT | NT-driven color scheme | NT-controlled | inactive | active |

**LED source by mode:** `leds.py` accepts commands from different sources depending on mode. In `fms` mode the source is `sacn_receiver.py`; in `adhoc`/`robot_teleop` it is the local scoring logic in `app.py`; in `robot_practice` it is NT values published by the robot. The LED subsystem itself is source-agnostic — it only consumes a command queue.

Mode changes are applied immediately without restart. The current mode is stored in `app.py` state and broadcast to all WebSocket clients on change. It is persisted to a local JSON file so it survives restarts.

### Data Flow

```
GPIO sensors → ball_counter → ball_count_queue → app.py (score logic)
                                                       │
                                NT topics ─────────────┤
                                  FMS/mode              │ categorize → active / auto / inactive count
                                  HubTracker/isActive ──┘
                                                       │
                                             nt_client (publish total, if NT mode)
                                             modbus    (write holding register, if FMS mode)
                                             leds      (update strip color)
                                             web       (broadcast via WS)

Modbus coils (FMS PLC writes) → modbus.py data store → app.py polls → motors
Admin web page                → mode_change          → app.py (activates/deactivates subsystems)
```

#### Ball Categorization Logic

Each ball event from `ball_count_queue` is categorized by `app.py` using the current NT state:

```
if FMS/mode == "auto":
    → autonomous_count += 1
    → active_count += 1
elif HubTracker/isActive == False:
    → inactive_count += 1
else:
    → active_count += 1
```

`active_count` is the primary score — it accumulates balls from both the autonomous period and active teleop cycles. `autonomous_count` and `inactive_count` are supplementary breakdowns displayed smaller on the dashboard.

In `adhoc` mode (no NT connection) there is no period or active/inactive signal, so all balls increment `active_count` only.

#### NetworkTables Topics

| Topic | Type | Direction | Description |
|---|---|---|---|
| `FMS/mode` | string | subscribe | `"auto"` during autonomous, `"teleop"` during teleoperated |
| `HubTracker/isActive` | boolean | subscribe | `true` when this hub's scoring cycle is active |

### Web Pages

The web server serves two distinct pages:
- **`/`** — Live dashboard (see UI spec below)
- **`/admin`** — Admin page: mode toggle, manual LED/motor overrides, connection status

#### Dashboard UI Spec

**Layout** (inspired by `../6328/RobotCode2026Public/hubcounter/hub_counter/web/`):

```
┌─────────────────────────────────────────┐
│  [logo] BearHub  [RedHub]  ● FMS  ● NT  │  ← header: branding, mode badge, status dots
├─────────────────────────────────────────┤
│                                         │
│           ACTIVE BALL COUNT             │  ← label
│                  42                     │  ← large centered count (~6rem), pulses on change
│                                         │
├───────────────────┬─────────────────────┤
│   AUTO COUNT      │   INACTIVE COUNT    │  ← smaller cards, ~2.5rem font
│       15          │         8           │
├───────────────────┴─────────────────────┤
│          [ Reset Count ]                │  ← only visible in adhoc mode
└─────────────────────────────────────────┘
```

**Color scheme — dark navy/white:**
- Background: `#0D1B2A` (dark navy)
- Card background: `#162032`
- Primary text: `#FFFFFF`
- Secondary text: `#8899BB`
- Accent / interactive: `#4488FF`
- Connected status dot: `#44FF44`
- Disconnected status dot: `#CC3333`
- Reset button: `#CC3333` (danger red)
- Mode badge: filled pill, color varies by mode (blue=fms, gray=adhoc, green=robot_teleop, yellow=robot_practice)

**Status indicators** (header, right side):
- `● FMS` — green if Modbus connected, red if not
- `● NT` — green if NetworkTables connected, red if not
- Only the relevant indicator for the current mode is highlighted; the other is dimmed

**Count update animation:** Active count pulses (scale 1 → 1.1 → 1) on each increment, matching the 6328 reference pattern.

**Scoring thresholds** (configurable in `config.py` as `THRESHOLD_ENERGIZED = 100` and `THRESHOLD_SUPERCHARGED = 360`):

| Threshold | Active count color | Milestone animation |
|---|---|---|
| Default (< 100) | white | — |
| Energized (≥ 100) | `#FFB300` (amber) | screen flash amber + confetti burst + screen shake |
| SuperCharged (≥ 360) | `#00CFFF` (electric blue) | screen flash electric blue + heavy confetti + intense double shake |

Animations trigger **once when the threshold is first crossed**, not on every subsequent ball. The active count number stays in the threshold color for the remainder of the match. Threshold colors and animations are inspired by the 6328 reference (`../6328/RobotCode2026Public/hubcounter/hub_counter/web/static/`).

**Reset button:** Rendered in the DOM always but shown only when mode is `adhoc`. Resets all three counts to zero via `POST /api/counts/reset`.

**Real-time updates:** WebSocket at `/api/ws` pushes JSON on every count change and mode/connection change. 30-second client-side keepalive ping. Auto-reconnects on disconnect.

**Logo:** Team logo is `src/web/static/4068Gear.jpeg` (white-on-black JPEG). Render in the header at ~48px height with `mix-blend-mode: screen` so the black background disappears against the dark navy page, leaving only the white gear/paw mark visible.

**Technology:** Single HTML file + single CSS file + single JS file (no build step, no framework). Vanilla JS class pattern matching the 6328 reference.

## Commands

### Setup (first time)
```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Run
```bash
# Add your user to the gpio and spi groups (one-time Pi setup):
# sudo usermod -aG gpio,spi $USER
python -m src.main              # auto-detects hub from hostname
python -m src.main --hub red    # override: force RedHub config
python -m src.main --hub blue   # override: force BlueHub config
```

### Lint / Format
```bash
ruff check src tests
ruff format src tests
```

### Tests
```bash
pytest                          # all tests
pytest tests/test_ball_counter.py          # single file
pytest -k "test_count_increments"          # single test by name
pytest --asyncio-mode=auto      # default mode set in pyproject.toml
```

## Configuration

Both hubs run identical code. Hub-specific settings live in `config.py` as a `HubConfig` dataclass with two instances: `RED_HUB` and `BLUE_HUB`.

**Fields that differ between hubs:**
| Field | RedHub | BlueHub |
|---|---|---|
| `name` | `"RedHub"` | `"BlueHub"` |
| `modbus_ball_count_register` | `0` (conventional 40001) | `1` (conventional 40002) |
| `led_idle_color` | red | blue |

**Fields shared in both instances** (GPIO pins, SPI device, LED count, NT server address, NT topic prefix, Modbus port, Modbus unit ID) are defined once as module-level constants.

#### Modbus Register Map

The Pi runs a Modbus TCP **server** on port 502, unit ID 1. The FMS PLC is the client that polls/writes.

| Conventional addr | pymodbus addr (0-based) | Type | Direction | Description |
|---|---|---|---|---|
| 40001 | 0 | Holding Register | Pi writes, PLC reads | RedHub total ball count (uint16) |
| 40002 | 1 | Holding Register | Pi writes, PLC reads | BlueHub total ball count (uint16) |
| 0xxxx | TBD | Coil | PLC writes, Pi reads | Motor commands (address TBD) |

`modbus.py` owns a `ModbusSequentialDataBlock` data store. `app.py` writes the ball count into the store whenever the count changes. `app.py` periodically reads the coil block to receive motor commands from the PLC.

**Hub selection** (in `main.py`): the active config is resolved at startup by checking `--hub red|blue` CLI argument first, then falling back to hostname detection (`redhub` → `RED_HUB`, `bluehub` → `BLUE_HUB`). Set each Pi's hostname accordingly (`sudo hostnamectl set-hostname redhub`).

## Hardware Notes

### WS2812b over SPI (`spidev` + `numpy`)
`rpi_ws281x` does not support the Pi 5 (BCM2712). Instead, the SPI MOSI line is used as a serialized data stream. A reference implementation exists at `../simple-bear-hub/led/ledstrip.py`.

**Encoding:** Each WS2812b bit is encoded as **8 SPI bits at 6.5 MHz** (`T_SPI_bit ≈ 154 ns`):
- `1` → `0b1111_1100` (6 high, 2 low → T1H ≈ 924 ns)
- `0` → `0b1100_0000` (2 high, 6 low → T0H ≈ 308 ns)

Each 24-bit GRB pixel becomes **24 bytes** of SPI data. `numpy.unpackbits` is used to expand pixel bytes into individual bits, which are then mapped to the byte patterns above.

**Buffer layout:** 42 zero-byte preamble (≈ 52 µs reset) followed by `led_count × 24` bytes of pixel data. Total: `42 + N × 24` bytes per frame.

**Pixel order:** WS2812b expects **GRB** — reorder before writing: `[g, r, b]` per pixel.

**SPI bus:** MOSI = GPIO 10, SCLK = GPIO 11. Only MOSI carries data; CE is unused.
**Voltage:** Pi 5 GPIO is 3.3 V; WS2812b data input typically accepts this, but a level shifter to 5 V improves reliability over long runs.
**SPI device:** `/dev/spidev0.0` — enable with `dtparam=spi=on` in `/boot/firmware/config.txt`.

### sACN / E1.31 (`sacn`)
Used in `fms` mode only. The FMS lighting system sends DMX512 data encapsulated in sACN packets over the network.

- The `sacn.sACNreceiver()` runs in its **own thread**; its callbacks must use `loop.call_soon_threadsafe()` to push LED commands into the asyncio LED queue.
- The sACN universe number is set in `config.py` (`SACN_UNIVERSE`).
- DMX channels 1–3 (R, G, B) set all LEDs to the same color.
- `sacn_receiver.py` is started and stopped by `App` when entering/leaving `fms` mode.

### lgpio (GPIO and PWM)
- Pi 5 is **not compatible** with `pigpio` (which uses `/dev/mem`) or legacy `RPi.GPIO`.
- `lgpio` uses the kernel GPIO character device (`/dev/gpiochip*`) and works without root when the user is in the `gpio` group.
- `lgpio` callbacks are threaded; use `loop.call_soon_threadsafe()` to post events into the asyncio loop.
- Hardware PWM on Pi 5: available on GPIO 12, 13, 18, 19 via `lgpio.tx_pwm()`.
- For unit tests, mock `lgpio.sbc()` — tests must not require real hardware.

### Ball Counter Channels
- Four physical ball chutes, one beam-break sensor each.
- Default GPIO pins in `config.py`: `BALL_SENSOR_PINS = [23, 24, 25, 16]` (channels 0–3).
- Beam-break logic: beam intact = HIGH, beam broken (ball present) = LOW → count on **falling edge**.
- Each falling edge = one ball scored in that channel; `ball_counter.py` posts the channel index to the queue.
- Debounce interval configured in `config.py` as `BALL_DEBOUNCE_MS` (milliseconds).

## Key Design Decisions

- **Single event loop** — `lgpio` callbacks use `loop.call_soon_threadsafe()` to post events into the asyncio loop; they never mutate shared state directly.
- **config.py is the single source of truth** for all hardware pin numbers, network addresses, NT topic names, Modbus register map, and LED strip parameters.
- **No WPILib robot code** — this device is a field peripheral, not a robot. It connects to the robot's NT server as a client.
- **Graceful shutdown** — `App.shutdown()` must stop `lgpio` callbacks, send a "disabled" LED state, and close Modbus/NT connections before the process exits (handle `SIGINT`/`SIGTERM`).
