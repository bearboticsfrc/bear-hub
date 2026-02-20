"""Network interface utilities — read and set the eth0 IPv4 address via nmcli."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

INTERFACE = "eth0"


def get_eth0_address() -> str | None:
    """Return the current IPv4 address of eth0 in CIDR form (e.g. '192.168.1.100/24'),
    or None if the interface is not found or has no address."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", INTERFACE],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1]  # "x.x.x.x/prefix"
        return None
    except Exception:
        log.warning("Could not read %s address", INTERFACE)
        return None


def set_eth0_address(cidr: str) -> None:
    """Set a static IPv4 address on eth0 using nmcli.

    Args:
        cidr: Address in CIDR notation, e.g. '192.168.1.100/24'.

    Raises:
        RuntimeError: If nmcli commands fail.
    """
    # Resolve the NetworkManager connection name bound to eth0
    try:
        result = subprocess.run(
            ["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", INTERFACE],
            capture_output=True, text=True, timeout=3, check=True,
        )
        connection = result.stdout.strip()
        if not connection:
            raise RuntimeError(f"No NetworkManager connection found for {INTERFACE}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"nmcli device show failed: {exc.stderr}") from exc

    try:
        subprocess.run(
            ["nmcli", "connection", "modify", connection,
             "ipv4.method", "manual",
             "ipv4.addresses", cidr],
            capture_output=True, text=True, timeout=5, check=True,
        )
        subprocess.run(
            ["nmcli", "connection", "up", connection],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"nmcli failed: {exc.stderr}") from exc

    log.info("Set %s address to %s", INTERFACE, cidr)
