"""Test simultaneous blind positioning service."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import ServiceCall
from custom_components.tuiss2ha.const import DOMAIN, OPT_FAVORITE_POSITION
from custom_components.tuiss2ha.cover import Tuiss, async_setup_entry


@pytest.fixture
def mock_cover_pair(mock_hass):
    """Create two mock cover entities for simultaneous testing."""
    covers = []
    for i, mac in enumerate(["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"], start=1):
        fake_client = MagicMock()
        fake_client.is_connected = False
        fake_client.write_gatt_char = AsyncMock()
        fake_client.start_notify = AsyncMock()
        fake_client.stop_notify = AsyncMock()
        fake_client.disconnect = AsyncMock()

        blind = MagicMock()
        blind.blind_id = mac
        blind.name = f"Blind {i}"
        blind._attr_name = f"Blind {i}"
        blind.host = mac
        blind.hub = MagicMock(manufacturer="Tuiss", _hass=mock_hass)
        blind._client = fake_client
        blind._locked = False
        blind._moving = 0
        blind._current_cover_position = 0.0

        async def fake_connect(b=blind, c=fake_client):
            c.is_connected = True
            b._client = c

        blind.attempt_connection = AsyncMock(side_effect=fake_connect)

        config = MagicMock()
        config.options = {OPT_FAVORITE_POSITION: 42.0 * i}

        cover = Tuiss(blind, config)
        cover.entity_id = f"cover.blind_{i}"
        covers.append(cover)

    mock_hass.data = {
        DOMAIN: {
            "test_entry": MagicMock(blinds=[]),
            "entities": {c.entity_id: c for c in covers},
        }
    }
    return covers


@pytest.mark.asyncio
async def test_attempt_connection_already_connected_is_noop(mock_hass):
    """Test that attempt_connection returns immediately without reconnecting if already connected."""
    from custom_components.tuiss2ha.hub import TuissBlind

    hub = MagicMock()
    hub._hass = mock_hass
    tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

    client = MagicMock()
    client.is_connected = True
    tb._client = client
    tb.connect = AsyncMock()

    await tb.attempt_connection()

    tb.connect.assert_not_called()


@pytest.mark.asyncio
async def test_simultaneous_positioning_connects_all_then_moves(mock_hass, mock_cover_pair):
    """Test that all blinds connect in parallel first, and then move simultaneously."""
    cover1, cover2 = mock_cover_pair

    # Track calls to async_set_cover_position
    cover1.async_set_cover_position = AsyncMock()
    cover2.async_set_cover_position = AsyncMock()

    # Capture the registered service handler
    service_handlers = {}

    def mock_async_register(domain, service, handler, schema=None):
        service_handlers[service] = handler

    mock_hass.services.async_register = MagicMock(side_effect=mock_async_register)

    # Trigger entry setup to register the service
    mock_config = MagicMock()
    mock_config.entry_id = "test_entry"
    mock_config.options = {}
    mock_async_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_config, mock_async_add_entities)

    simultaneous_handler = service_handlers["simultaneous_blind_positioning"]

    service_call = MagicMock()
    service_call.hass = mock_hass
    service_call.data = {
        "entity_ids": [cover1.entity_id, cover2.entity_id],
        "position": 75.0,
        "favourite": False,
    }

    await simultaneous_handler(service_call)

    # Both blinds must have been connected first
    cover1._blind.attempt_connection.assert_awaited_once()
    cover2._blind.attempt_connection.assert_awaited_once()

    # Both blinds must have had position dispatched with skip_battery_check=True
    cover1.async_set_cover_position.assert_awaited_once_with(position=75.0, skip_battery_check=True)
    cover2.async_set_cover_position.assert_awaited_once_with(position=75.0, skip_battery_check=True)


@pytest.mark.asyncio
async def test_simultaneous_favourite_positioning(mock_hass, mock_cover_pair):
    """Test simultaneous positioning with favourite=True moves each blind to its configured favourite."""
    cover1, cover2 = mock_cover_pair

    cover1.async_set_cover_position = AsyncMock()
    cover2.async_set_cover_position = AsyncMock()

    service_handlers = {}
    mock_hass.services.async_register = MagicMock(
        side_effect=lambda d, s, h, schema=None: service_handlers.update({s: h})
    )

    mock_config = MagicMock(entry_id="test_entry", options={})
    await async_setup_entry(mock_hass, mock_config, MagicMock())

    simultaneous_handler = service_handlers["simultaneous_blind_positioning"]

    service_call = MagicMock()
    service_call.hass = mock_hass
    service_call.data = {
        "entity_ids": [cover1.entity_id, cover2.entity_id],
        "favourite": True,
    }

    await simultaneous_handler(service_call)

    cover1.async_set_cover_position.assert_awaited_once_with(position=42.0, skip_battery_check=True)
    cover2.async_set_cover_position.assert_awaited_once_with(position=84.0, skip_battery_check=True)


@pytest.mark.asyncio
async def test_simultaneous_positioning_aborts_when_blind_locked(mock_hass, mock_cover_pair):
    """Test that simultaneous positioning raises device_locked if any target blind is currently busy."""
    cover1, cover2 = mock_cover_pair
    cover1._blind._locked = True  # Simulate cover1 is actively moving

    service_handlers = {}
    mock_hass.services.async_register = MagicMock(
        side_effect=lambda d, s, h, schema=None: service_handlers.update({s: h})
    )

    mock_config = MagicMock(entry_id="test_entry", options={})
    await async_setup_entry(mock_hass, mock_config, MagicMock())

    simultaneous_handler = service_handlers["simultaneous_blind_positioning"]

    service_call = MagicMock()
    service_call.hass = mock_hass
    service_call.data = {
        "entity_ids": [cover1.entity_id, cover2.entity_id],
        "position": 50.0,
        "favourite": False,
    }

    with pytest.raises(HomeAssistantError) as exc_info:
        await simultaneous_handler(service_call)

    assert exc_info.value.translation_key == "device_locked"
    # Neither blind should have attempted connection
    cover1._blind.attempt_connection.assert_not_called()
    cover2._blind.attempt_connection.assert_not_called()
