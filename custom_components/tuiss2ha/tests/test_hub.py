import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, patch

# Add the project root to the Python path to allow absolute imports
# This ensures that 'custom_components.tuiss2ha.hub' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Correctly import only the 'Hub' class from your 'hub.py' file.
# The UUIDs are attributes of the Hub instance, not module-level constants.
from custom_components.tuiss2ha.hub import Hub

# Mark all tests in this module as asyncio tests
pytestmark = pytest.mark.asyncio

# A fake Bluetooth device address and name for testing purposes
FAKE_DEVICE_ADDRESS = "00:11:22:33:44:55"
FAKE_DEVICE_NAME = "My Test Blind"


@pytest.fixture
def mock_bleak_client():
    """
    This pytest fixture creates a mock BleakClient object.
    It replaces the real BleakClient with a "fake" one for testing.
    This allows us to simulate Bluetooth interactions without a real device.
    """
    # Patch the BleakClient where it's used in the hub module.
    with patch('custom_components.tuiss2ha.hub.BleakClient') as mock_client_class:
        mock_client_instance = mock_client_class.return_value
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock()
        mock_client_instance.connect = AsyncMock()
        mock_client_instance.disconnect = AsyncMock()
        mock_client_instance.read_gatt_char = AsyncMock()
        mock_client_instance.write_gatt_char = AsyncMock()
        yield mock_client_instance


async def test_get_battery_level(hass, mock_bleak_client):
    """
    Tests the get_battery_level method.
    """
    # Arrange
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x5A])
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    battery_level = await hub.get_battery_level()

    # Assert
    assert battery_level == 90
    # Use the instance attribute for the UUID
    mock_bleak_client.read_gatt_char.assert_called_once_with(hub.char_battery)


async def test_get_position(hass, mock_bleak_client):
    """
    Tests the get_position method.
    """
    # Arrange
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x4B])
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    position = await hub.get_position()

    # Assert
    assert position == 75
    # Use the instance attribute for the UUID
    mock_bleak_client.read_gatt_char.assert_called_once_with(hub.char_position)


async def test_set_position(hass, mock_bleak_client):
    """
    Tests the set_position method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)
    target_position = 50

    # Act
    await hub.set_position(target_position)

    # Assert
    expected_payload = b"\x01" + target_position.to_bytes(1, "little")
    # Use the instance attribute for the UUID
    mock_bleak_client.write_gatt_char.assert_called_once_with(hub.char_control, expected_payload)


async def test_open(hass, mock_bleak_client):
    """
    Tests the open method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    await hub.open()

    # Assert
    expected_payload = b'\x01\x00'
    # Use the instance attribute for the UUID
    mock_bleak_client.write_gatt_char.assert_called_once_with(hub.char_control, expected_payload)


async def test_close(hass, mock_bleak_client):
    """
    Tests the close method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    await hub.close()

    # Assert
    expected_payload = b'\x01\x64'
    # Use the instance attribute for the UUID
    mock_bleak_client.write_gatt_char.assert_called_once_with(hub.char_control, expected_payload)


async def test_stop(hass, mock_bleak_client):
    """
    Tests the stop method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    await hub.stop()

    # Assert
    expected_payload = b'\x00'
    # Use the instance attribute for the UUID
    mock_bleak_client.write_gatt_char.assert_called_once_with(hub.char_control, expected_payload)


async def test_connection_management(hass, mock_bleak_client):
    """
    Tests that the hub context manager properly connects and disconnects the client.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)
    assert hub._name == FAKE_DEVICE_NAME

    # Act
    async with hub as h:
        # Assert
        mock_bleak_client.connect.assert_called_once()
        assert h is not None

    # Assert
    mock_bleak_client.disconnect.assert_called_once()
