import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tuiss2ha.hub import TuissBlind
import importlib
from custom_components.tuiss2ha.cover import Tuiss, HomeAssistantError
from custom_components.tuiss2ha.const import DeviceNotFound, ConnectionTimeout


@pytest.mark.asyncio
async def test_attempt_connection_raises_device_not_found(mock_hass):
    """If no BLE device can be discovered the attempt_connection should raise DeviceNotFound."""
    # Patch the bluetooth lookup to return None (device not found)
    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=None):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)
        # Ensure restart attempts is small so the loop exits quickly
        tb._restart_attempts = 1

        with pytest.raises(DeviceNotFound):
            await tb.attempt_connection()


@pytest.mark.asyncio
async def test_attempt_connection_raises_connection_timeout(mock_hass):
    """If connection attempts fail repeatedly, ConnectionTimeout should be raised."""
    # Patch the bluetooth lookup to return a dummy device with a .name attribute
    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=MagicMock(name="DummyDevice")):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)
        # Force a single retry and patch connect to do nothing (so _client remains None)
        tb._restart_attempts = 1

        async def fake_connect():
            # simulate a failed connect that doesn't set _client
            return

        tb.connect = AsyncMock(side_effect=fake_connect)

        with pytest.raises(ConnectionTimeout):
            await tb.attempt_connection()


@pytest.mark.asyncio
async def test_cover_methods_raise_homeassistanterror_on_device_errors(mock_hass, mock_hub):
    """Test that cover entity methods raise HomeAssistantError when the underlying blind raises device/connection errors."""
    # Get a TuissBlind from the provided fixture (mock_hub)
    tuiss_blind = mock_hub.blinds[0]

    # Create a fake config entry with minimal options
    fake_config = MagicMock()
    fake_config.options = {}

    cover_entity = Tuiss(tuiss_blind, fake_config)
    # Ensure .name is available for logging inside the integration
    cover_entity.name = cover_entity._attr_name

    # Patch async_move_cover to raise DeviceNotFound for open/close/set
    tuiss_blind.async_move_cover = AsyncMock(side_effect=DeviceNotFound("not found"))

    with pytest.raises(HomeAssistantError):
        await cover_entity.async_open_cover()

    with pytest.raises(HomeAssistantError):
        await cover_entity.async_close_cover()

    # The integration expects kwargs keyed by ATTR_POSITION (imported from HA). In the
    # test environment that constant may be a MagicMock object which can't be used
    # as a keyword name. Override it to a plain string for the test.
    cover_mod = importlib.import_module("custom_components.tuiss2ha.cover")
    setattr(cover_mod, "ATTR_POSITION", "position")

    with pytest.raises(HomeAssistantError):
        await cover_entity.async_set_cover_position(**{"position": 50})

    # For stop, patch stop to raise RuntimeError while _moving != 0
    tuiss_blind.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    tuiss_blind._moving = 1

    with pytest.raises(HomeAssistantError):
        await cover_entity.async_stop_cover()
