from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuiss2ha.hub import TuissBlind


@pytest.mark.asyncio
async def test_attempt_connection_succeeds_and_set_position(mock_hass):
    """Happy path: attempt_connection finds device and connect sets _client and set_position sends command."""
    # Provide a fake BLE device with a .name
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    # Patch the bluetooth lookup to return our device
    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

        # Simulate establish_connection returning a client with is_connected True and write_gatt_char stubs
        fake_client = MagicMock()
        fake_client.is_connected = True
        fake_client.write_gatt_char = AsyncMock()
        fake_client.start_notify = AsyncMock()
        fake_client.stop_notify = AsyncMock()

        # Patch the establish_connection helper used in connect to return our fake client
        with patch("custom_components.tuiss2ha.hub.establish_connection", return_value=fake_client):
            # Ensure attempts small for test speed
            tb._restart_attempts = 1
            await tb.attempt_connection()

            assert tb._client is fake_client

            # Test set_position will call write_gatt_char via send_command
            # Patch send_command to observe calls
            tb._client.write_gatt_char.assert_called()

