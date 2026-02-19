"""Shared pytest fixtures — mock hardware at the library level."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config import BLUE_HUB, RED_HUB, HubConfig


@pytest.fixture
def red_hub_config() -> HubConfig:
    return RED_HUB


@pytest.fixture
def blue_hub_config() -> HubConfig:
    return BLUE_HUB


@pytest.fixture
def mock_lgpio():
    """Patch lgpio at import level so hardware modules never touch real GPIO."""
    lgpio_mock = MagicMock()
    lgpio_mock.FALLING_EDGE = 0
    lgpio_mock.gpiochip_open.return_value = 99
    lgpio_mock.callback.return_value = MagicMock()
    with patch.dict("sys.modules", {"lgpio": lgpio_mock}):
        yield lgpio_mock


@pytest.fixture
def mock_spidev():
    """Patch spidev so LedStrip can be instantiated without hardware."""
    spi_instance = MagicMock()
    spidev_mock = MagicMock()
    spidev_mock.SpiDev.return_value = spi_instance
    with patch.dict("sys.modules", {"spidev": spidev_mock}):
        yield spi_instance


@pytest.fixture
def mock_sacn():
    """Patch sacn so SACNReceiver can be used without a real network."""
    receiver_mock = MagicMock()
    sacn_mock = MagicMock()
    sacn_mock.sACNreceiver.return_value = receiver_mock
    with patch.dict("sys.modules", {"sacn": sacn_mock}):
        yield receiver_mock


@pytest.fixture
def mock_ntcore():
    """Patch ntcore so NTClient can be used without a real NetworkTables server."""
    inst_mock = MagicMock()
    nt_mock = MagicMock()
    nt_mock.NetworkTableInstance.getDefault.return_value = inst_mock
    inst_mock.getConnections.return_value = []
    with patch.dict("sys.modules", {"ntcore": nt_mock}):
        yield inst_mock
