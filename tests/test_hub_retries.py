from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bleak.exc import BleakError
from custom_components.tuiss2ha.hub import TuissBlind
from custom_components.tuiss2ha.const import ConnectionTimeout


@pytest.mark.asyncio
async def test_attempt_connection_retries_and_times_out(mock_hass):
    """If connect never succeeds, attempt_connection should raise ConnectionTimeout."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

        # Patch establish_connection to always raise BleakError (simulate connection failures)
        with patch("custom_components.tuiss2ha.hub.establish_connection", side_effect=BleakError("bleak fail")):
            tb._restart_attempts = 2
            with pytest.raises(ConnectionTimeout):
                await tb.attempt_connection()


@pytest.mark.asyncio
async def test_attempt_connection_eventual_success(mock_hass):
    """If connect fails a few times then succeeds, attempt_connection should return without error."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    fake_client = MagicMock()
    fake_client.is_connected = True
    fake_client.write_gatt_char = AsyncMock()

    # Make a side effect for establish_connection: fail once, then return client
    calls = {"count": 0}

    async def side_effect(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise BleakError("temporary fail")
        return fake_client

    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)
        with patch("custom_components.tuiss2ha.hub.establish_connection", side_effect=side_effect):
            tb._restart_attempts = 3
            await tb.attempt_connection()
            assert tb._client is fake_client
