# Installation — Raspberry Pi 5

Instructions for deploying bear-hub on a fresh Raspberry Pi 5 running Raspberry Pi OS.

## 1. Set the hostname

```bash
sudo hostnamectl set-hostname redhub   # or bluehub
```

## 2. Enable SPI

```bash
sudo nano /boot/firmware/config.txt
```

Add at the bottom:

```
dtparam=spi=on
```

Reboot for the change to take effect.

## 3. Add your user to the required groups

```bash
sudo usermod -aG gpio,spi $USER
```

Log out and back in for group membership to take effect.

## 4. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

## 5. Copy the code to the Pi

From your dev machine:

```bash
rsync -av /path/to/bear-hub/ pi@redhub.local:~/bear-hub/
```

## 6. Install dependencies

```bash
sudo apt install -y swig liblgpio-dev   # swig: build robotpy-ntcore; liblgpio-dev: link lgpio Python package
cd ~/bear-hub
uv venv --seed                      # --seed ensures pip is available inside the venv
source .venv/bin/activate
uv pip install -e ".[pi]"           # installs lgpio and spidev
python -m pip install pyntcore          # use python -m pip, NOT uv pip — uv cannot resolve robotpy packages
```

## 7. Create the state directory

```bash
sudo mkdir -p /var/lib/bear-hub
sudo chown $USER:$USER /var/lib/bear-hub
```

## 8. Run

```bash
python -m src.main          # auto-detects hub from hostname (redhub → RedHub, bluehub → BlueHub)
python -m src.main --hub red   # or force a specific hub
```

Open the dashboard at `http://redhub.local:8080`.

---

## Run as a systemd service (start on boot)

Copy the included service file:

```bash
sudo cp ~/bear-hub/bear-hub.service /etc/systemd/system/bear-hub.service
```

Enable and start:

```bash
sudo systemctl enable bear-hub
sudo systemctl start bear-hub
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
