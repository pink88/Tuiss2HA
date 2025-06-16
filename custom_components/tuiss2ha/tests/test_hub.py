import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, patch

# Add the project root to the Python path to allow absolute imports
# This ensures that 'custom_components.tuiss2ha.hub' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Correctly import the 'Tuiss' class from your 'hub.py' file
from custom_components.tuiss2ha.hub import *

# Mark all tests in this module as asyncio tests
pytestmark = pytest.mark.asyncio

# A fake Bluetooth device address for testing purposes
FAKE_DEVICE_ADDRESS = "00:11:22:33:44:55"
FAKE_DEVICE_NAME = "Test"

@pytest.fixture
def mock_bleak_client():
    """
    This pytest fixture creates a mock BleakClient object.
    It replaces the real BleakClient with a "fake" one for testing.
    This allows us to simulate Bluetooth interactions without a real device.
    """
    # Patch BleakClient in the correct location where it's used ('hub.py')
    with patch('custom_components.tuiss2ha.hub.bleak.BleakClient') as mock_client_class:
        mock_client_instance = mock_client_class.return_value
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock()
        mock_client_instance.connect = AsyncMock()
        mock_client_instance.disconnect = AsyncMock()
        mock_client_instance.read_gatt_char = AsyncMock()
        mock_client_instance.write_gatt_char = AsyncMock()
        yield mock_client_instance

async def test_get_battery(mock_bleak_client):
    """
    Tests the get_battery method.
    """
    # Arrange: Simulate the device returning a battery level of 90 (0x5A)
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x5A])
    
    # Use the correct class name 'Tuiss'
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act
    battery_level = await device.get_battery()

    # Assert
    assert battery_level == 90
    # Check that read_gatt_char was called with the battery characteristic UUID
    mock_bleak_client.read_gatt_char.assert_called_once_with(device.char_battery)

async def test_get_position(mock_bleak_client):
    """
    Tests the get_position method.
    """
    # Arrange: Simulate device returning a position of 75 (0x4B)
    mock_bleak_client.read_gatt_char.return_value = bytearray([0x4B])
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act
    position = await device.get_position()

    # Assert
    assert position == 75
    mock_bleak_client.read_gatt_char.assert_called_once_with(device.char_position)

async def test_set_position(mock_bleak_client):
    """
    Tests the set_position method.
    """
    # Arrange
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)
    target_position = 50

    # Act
    await device.set_position(target_position)

    # Assert
    # The command to set position is the 'set_position' command from the COMMANDS dict + the position value
    expected_payload = device.COMMANDS["set_position"] + bytearray([target_position])
    mock_bleak_client.write_gatt_char.assert_called_once_with(device.char_control, expected_payload)

async def test_open_blind(mock_bleak_client):
    """
    Tests the open_blind method.
    """
    # Arrange
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act
    await device.open_blind()

    # Assert
    # The 'open' command sends a specific payload
    expected_payload = device.COMMANDS["open"]
    mock_bleak_client.write_gatt_char.assert_called_once_with(device.char_control, expected_payload)

async def test_close_blind(mock_bleak_client):
    """
    Tests the close_blind method.
    """
    # Arrange
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act
    await device.close_blind()

    # Assert
    # The 'close' command sends a specific payload
    expected_payload = device.COMMANDS["close"]
    mock_bleak_client.write_gatt_char.assert_called_once_with(device.char_control, expected_payload)

async def test_stop_blind(mock_bleak_client):
    """
    Tests the stop_blind method.
    """
    # Arrange
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act
    await device.stop_blind()

    # Assert
    # The 'stop' command sends a specific payload
    expected_payload = device.COMMANDS["stop"]
    mock_bleak_client.write_gatt_char.assert_called_once_with(device.char_control, expected_payload)

async def test_connection_management(mock_bleak_client):
    """
    Tests that the device context manager properly connects and disconnects the client.
    """
    # Arrange
    device = Hub(FAKE_DEVICE_ADDRESS,FAKE_DEVICE_NAME)

    # Act: Use the device as an async context manager
    async with device as d:
        # Assert: Check that connect was called upon entering the 'with' block
        mock_bleak_client.connect.assert_called_once()
        assert d is not None

    # Assert: Check that disconnect was called upon exiting the 'with' block
    mock_bleak_client.disconnect.assert_called_once()
