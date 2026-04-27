"""Test timer actions and command generation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError
from custom_components.tuiss2ha.hub import Hub, TuissBlind
from custom_components.tuiss2ha.cover import async_action_add_timer


@pytest.fixture
def real_hub(mock_hass):
    """A mock Hub object initialized with a TuissBlind."""
    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=MagicMock(name="TB-01")), \
         patch("custom_components.tuiss2ha.hub.Store"):
        hub = Hub(mock_hass, "AA:BB:CC:DD:EE:FF", "Test Blind")
    return hub


@pytest.fixture
def tuiss_blind(real_hub):
    """A real TuissBlind object for testing."""
    return real_hub.blinds[0]


@pytest.mark.parametrize(
    "index, days, time, position, expected_hex",
    [
        # index 10 = 0a | days [mon(2), wed(8)] = 10 = 0a | time 08:30 = 08 1e | pos 50.0 = 500 = f4 01
        ("10", ["mon", "wed"], "08:30", 50.0, "ff78ea4103000ab23f0a081e00f401"),
        # index 15 = 0f | days [sun(1), sat(64)] = 65 = 41 | time 15:45 = 0f 2d | pos 100.0 = 1000 = e8 03
        ("15", ["sun", "sat"], "15:45", 100.0, "ff78ea4103000fb23f410f2d00e803"),
        # index 11 = 0b | days [fri(32)] = 32 = 20 | time 00:00 = 00 00 | pos 0.0 = 0 = 00 00
        ("11", ["fri"], "00:00", 0.0, "ff78ea4103000bb23f200000000000"),
    ]
)
def test_create_timer_command(tuiss_blind, index, days, time, position, expected_hex):
    """Test the command string generation for timers."""
    assert tuiss_blind.create_timer_command(index, days, time, position) == expected_hex


@pytest.mark.asyncio
async def test_async_add_timer_success(mock_hass, tuiss_blind):
    """Test successfully adding a timer to the blind."""
    tuiss_blind.attempt_connection = AsyncMock()
    tuiss_blind.send_command = AsyncMock()
    tuiss_blind.async_save_timer = AsyncMock()
    tuiss_blind.publish_updates = MagicMock()
    
    # Simulate an already connected client
    tuiss_blind._client = MagicMock()
    tuiss_blind._client.is_connected = True
    
    with patch("custom_components.tuiss2ha.hub.async_dispatcher_send") as mock_dispatch:
        timer_id = await tuiss_blind.async_add_timer(["mon"], "08:00", 50.0)
        
        assert timer_id == "10"
        assert "10" in tuiss_blind.timers
        assert tuiss_blind.timers["10"]["days"] == ["mon"]
        assert tuiss_blind.timers["10"]["time"] == "08:00"
        assert tuiss_blind.timers["10"]["position"] == 50.0
        
        # Verify it sent all 5 setup commands to the blind
        assert tuiss_blind.send_command.call_count == 5
        tuiss_blind.async_save_timer.assert_awaited_once()
        tuiss_blind.publish_updates.assert_called_once()
        
        # Verify it dispatched the new timer event to HA dynamically
        mock_dispatch.assert_called_once_with(mock_hass, f"tuiss2ha_add_timer_{tuiss_blind.blind_id}", "10")


@pytest.mark.asyncio
async def test_async_add_timer_max_reached(mock_hass, tuiss_blind):
    """Test adding a timer when the hardware maximum has been reached."""
    # Simulate having all 6 timers (10 through 15) allocated
    tuiss_blind.timers = {str(i): {} for i in range(10, 16)}
    
    with pytest.raises(HomeAssistantError) as exc:
        await tuiss_blind.async_add_timer(["mon"], "08:00", 50.0)
        
    assert "max_timers_reached" in str(exc.value)


@pytest.mark.asyncio
async def test_async_delete_timer_success(mock_hass, tuiss_blind):
    """Test successfully deleting an existing timer."""
    tuiss_blind.attempt_connection = AsyncMock()
    tuiss_blind.send_command = AsyncMock()
    tuiss_blind.async_save_timer = AsyncMock()
    tuiss_blind.publish_updates = MagicMock()
    
    tuiss_blind._client = MagicMock()
    tuiss_blind._client.is_connected = True
    
    # Pre-populate a timer
    tuiss_blind.timers = {"11": {"days": ["mon"], "time": "08:00", "position": 50.0}}
    
    with patch("custom_components.tuiss2ha.hub.async_dispatcher_send") as mock_dispatch:
        await tuiss_blind.async_delete_timer("11")
        
        assert "11" not in tuiss_blind.timers
        assert tuiss_blind.send_command.call_count == 3
        tuiss_blind.async_save_timer.assert_awaited_once()
        tuiss_blind.publish_updates.assert_called_once()
        
        mock_dispatch.assert_called_once_with(mock_hass, f"tuiss2ha_delete_timer_{tuiss_blind.blind_id}_11")


@pytest.mark.asyncio
async def test_cover_action_add_timer():
    """Test the cover platform service wrapper correctly parses inputs."""
    mock_entity = MagicMock()
    mock_entity._blind.async_add_timer = AsyncMock()
    
    mock_service_call = MagicMock()
    mock_service_call.data = {
        "position": 75.0,
        "days": ["mon", "tue"],
        "time": "12:34:00"
    }
    
    await async_action_add_timer(mock_entity, mock_service_call)
    
    mock_entity._blind.async_add_timer.assert_awaited_once_with(
        ["mon", "tue"], "12:34:00", 75.0
    )