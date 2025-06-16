import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, patch

# Add the project root to the Python path to allow absolute imports
# This ensures that 'custom_components.tuiss2ha.hub' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Correctly import the 'Hub' class and UUID constants from your 'hub.py' file
from custom_components.tuiss2ha.hub import Hub, BATTERY_LEVEL_UUID, CURRENT_POSITION_UUID, MOTOR_CONTROL_UUID

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
    # Arrange: Simulate the device returning a battery level of 90 (0x5A)
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x5A])
    
    # Instantiate the Hub with the device name passed directly.
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act: Call the correct method
    battery_level = await hub.get_battery_level()

    # Assert
    assert battery_level == 90
    # Check that read_gatt_char was called with the correct battery UUID
    mock_bleak_client.read_gatt_char.assert_called_once_with(BATTERY_LEVEL_UUID)


async def test_get_position(hass, mock_bleak_client):
    """
    Tests the get_position method.
    """
    # Arrange: Simulate device returning a position of 75 (0x4B)
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x4B])
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    position = await hub.get_position()

    # Assert
    assert position == 75
    mock_bleak_client.read_gatt_char.assert_called_once_with(CURRENT_POSITION_UUID)


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
    # The command to set position sends a payload: b'\x01' + position byte
    expected_payload = b"\x01" + target_position.to_bytes(1, "little")
    mock_bleak_client.write_gatt_char.assert_called_once_with(MOTOR_CONTROL_UUID, expected_payload)


async def test_open(hass, mock_bleak_client):
    """
    Tests the open method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    await hub.open()

    # Assert
    # The 'open' command should result in a call to set_position(0).
    # The payload for position 0 is b'\x01\x00'
    expected_payload = b'\x01\x00'
    mock_bleak_client.write_gatt_char.assert_called_once_with(MOTOR_CONTROL_UUID, expected_payload)


async def test_close(hass, mock_bleak_client):
    """
    Tests the close method.
    """
    # Arrange
    hub = Hub(hass, FAKE_DEVICE_ADDRESS, FAKE_DEVICE_NAME)

    # Act
    await hub.close()

    # Assert
    # The 'close' command should result in a call to set_position(100).
    # The payload for position 100 is b'\