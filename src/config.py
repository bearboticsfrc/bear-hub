import socket
from dataclasses import dataclass

# --- Hardware flags (set False to use Null implementations) ---
ENABLE_GPIO: bool = True
ENABLE_LEDS: bool = True

# --- Ball counter ---
BALL_SENSOR_PINS: list[int] = [23, 24, 25, 16]
BALL_DEBOUNCE_MS: int = 10

# --- LED strip ---
LED_COUNT: int = 300
SPI_BUS: int = 0
SPI_DEVICE: int = 0
SPI_SPEED_HZ: int = 6_500_000

# --- Motors (PWM pins TBD) ---
MOTOR_PINS: list[int] = []  # TODO: assign when hardware is known

# --- sACN ---
SACN_UNIVERSE: int = 1

# --- Modbus ---
MODBUS_HOST: str = "0.0.0.0"
MODBUS_PORT: int = 502
MODBUS_UNIT_ID: int = 1

# --- NetworkTables ---
NT_SERVER_ADDRESS: str = "10.40.68.2"  # roboRIO address for team 4068
NT_IDENTITY: str = "bear-hub"

# --- Web ---
WEB_HOST: str = "0.0.0.0"
WEB_PORT: int = 8080

# --- Scoring thresholds ---
THRESHOLD_ENERGIZED: int = 100
THRESHOLD_SUPERCHARGED: int = 360

# --- State persistence ---
STATE_FILE: str = "/var/lib/bear-hub/state.json"


@dataclass(frozen=True)
class HubConfig:
    name: str
    modbus_ball_count_register: int  # 0-based pymodbus address
    led_idle_color: tuple[int, int, int]  # RGB


RED_HUB = HubConfig(name="RedHub", modbus_ball_count_register=0, led_idle_color=(255, 0, 0))
BLUE_HUB = HubConfig(name="BlueHub", modbus_ball_count_register=1, led_idle_color=(0, 0, 255))


def resolve_hub(arg: str | None) -> HubConfig:
    """Select hub config from CLI arg, then hostname, then default to RedHub."""
    if arg == "red":
        return RED_HUB
    if arg == "blue":
        return BLUE_HUB
    hostname = socket.gethostname().lower()
    if "blue" in hostname:
        return BLUE_HUB
    return RED_HUB
