# Installation — Raspberry Pi 5

Instructions for deploying bear-hub on a fresh Raspberry Pi 5 running Raspberry Pi OS.

## 1. Set the hostname

```bash
sudo hostnamectl set-hostname redhub   # or bluehub
```

## 2. Wire the ball sensors

Each of the four sensor channels requires an external **10 kΩ pull-up resistor** — the Pi 5 kernel does not support software pull-up configuration via the GPIO character device.

```
3.3V ──[10kΩ]──┬── GPIO pin
               │
          [sensor / button]
               │
              GND
```

| Channel | BCM GPIO | Header pin | GND pin |
|---------|----------|------------|---------|
| 0 | GPIO 23 | Pin 16 | Pin 14 |
| 1 | GPIO 24 | Pin 18 | Pin 20 |
| 2 | GPIO 25 | Pin 22 | Pin 25 |
| 3 | GPIO 16 | Pin 36 | Pin 34 |

Sensor logic: beam intact = HIGH, beam broken (ball scored) = LOW.
For testing without sensors, wire a momentary pushbutton between the GPIO pin and GND (press = ball scored).

---

## 3. Enable SPI

```bash
sudo nano /boot/firmware/config.txt
```

Add at the bottom:

```
dtparam=spi=on
```

Reboot for the change to take effect.

## 4. Enable hardware PWM

```bash
sudo nano /boot/firmware/config.txt
```

Add inside the `[pi5]` section (create it if it doesn't exist):

```
[pi5]
dtoverlay=pwm-2chan
```

> **Note:** Do not pass `pin=` or `func=` parameters — the overlay defaults are correct for Pi 5.
> The PWM channels appear at `/sys/class/pwm/pwmchip0` after reboot.

Reboot for the change to take effect.

## 5. Add your user to the required groups

```bash
sudo usermod -aG gpio,spi $USER
```

Log out and back in for group membership to take effect.

## 6. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

## 7. Copy the code to the Pi

From your dev machine:

```bash
rsync -av /path/to/bear-hub/ pi@redhub.local:~/bear-hub/
```

## 8. Install dependencies

```bash
sudo apt install -y swig liblgpio-dev   # swig: build robotpy-ntcore; liblgpio-dev: link lgpio Python package
cd ~/bear-hub
uv venv --seed                      # --seed ensures pip is available inside the venv
source .venv/bin/activate
uv pip install -e ".[pi]"           # installs lgpio and spidev
python -m pip install pyntcore          # use python -m pip, NOT uv pip — uv cannot resolve robotpy packages
```

## 9. Create the state directory

```bash
sudo mkdir -p /var/lib/bear-hub
sudo chown $USER:$USER /var/lib/bear-hub
```

## 10. Run

```bash
python -m src.main          # auto-detects hub from hostname (redhub → RedHub, bluehub → BlueHub)
python -m src.main --hub red   # or force a specific hub
```

Open the dashboard at `http://redhub.local:8080`.

---

## Run as a systemd service (start on boot)

Copy both included service files:

```bash
sudo cp ~/bear-hub/pwm-permissions.service /etc/systemd/system/pwm-permissions.service
sudo cp ~/bear-hub/bear-hub.service /etc/systemd/system/bear-hub.service
```

Enable and start:

```bash
sudo systemctl enable pwm-permissions bear-hub
sudo systemctl start pwm-permissions bear-hub
sudo systemctl status bear-hub
```

View logs:

```bash
journalctl -u bear-hub -f
```

---

## Modbus port 502

> **Required** — port 502 is a privileged port (<1024). Without `authbind` the
> Modbus server will fail to start and the app will log a `PermissionError`.

Use `authbind` to allow the service to bind port 502 without running as root:

```bash
sudo apt install authbind
sudo touch /etc/authbind/byport/502
sudo chmod 500 /etc/authbind/byport/502
sudo chown fms /etc/authbind/byport/502
```

Update the `ExecStart` line in the service file to invoke Python through authbind:

```ini
ExecStart=authbind --deep /home/fms/bear-hub/.venv/bin/python -m src.main
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bear-hub
```

To verify authbind is working, check the logs — you should see:

```
INFO  src.modbus: Starting Modbus TCP server on 0.0.0.0:502
INFO  pymodbus.logging: Server listening.
```

If instead you see `PermissionError`, authbind is not configured correctly for the `fms` user.
