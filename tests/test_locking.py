"""Test operational locking across all Tuiss2HA services."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuiss2ha.binary_sensor import LockStatusSensor
from custom_components.tuiss2ha.cover import HomeAssistantError
from custom_components.tuiss2ha.hub import TuissBlind


@pytest.fixture
def mock_blind(mock_hass):
    """Create a TuissBlind instance with mocked dependencies."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        return_value=fake_device,
    ):
        hub = MagicMock()
        mock_hass.loop = MagicMock()
        hub._hass = mock_hass

        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test Blind", hub)
        tb._current_cover_position = 0.0
        tb._client = MagicMock(is_connected=True)
        tb.ensure_connected = AsyncMock()
        tb.disconnect = AsyncMock()
        return tb


@pytest.mark.asyncio
async def test_get_battery_status_locked_raises_error(mock_blind):
    """Test get_battery_status raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True

    with pytest.raises(HomeAssistantError) as exc:
        await tb.get_battery_status()

    assert exc.value.translation_key == "device_locked"


@pytest.mark.asyncio
async def test_get_battery_status_from_move_bypasses_lock(mock_blind):
    """Test internal battery check from active move reuses the lock without raising."""
    tb = mock_blind
    tb._locked = True
    tb.get_from_blind = AsyncMock()

    await tb.get_battery_status(from_move=True)

    assert tb.get_from_blind.called
    assert tb._locked is True, "Lock should remain held by caller move task"


@pytest.mark.asyncio
async def test_get_battery_status_locks_and_unlocks(mock_blind):
    """Test standalone get_battery_status acquires lock during call and releases after."""
    tb = mock_blind
    tb._locked = False

    locked_during_call = None

    async def fake_get_from_blind(cmd, callback):
        nonlocal locked_during_call
        locked_during_call = tb._locked

    tb.get_from_blind = AsyncMock(side_effect=fake_get_from_blind)

    await tb.get_battery_status()

    assert locked_during_call is True
    assert tb._locked is False
    tb.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_get_blind_position_locked_raises_error(mock_blind):
    """Test get_blind_position raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True

    with pytest.raises(HomeAssistantError) as exc:
        await tb.get_blind_position()

    assert exc.value.translation_key == "device_locked"


@pytest.mark.asyncio
async def test_get_blind_position_locks_and_unlocks(mock_blind):
    """Test get_blind_position acquires lock during call and releases after."""
    tb = mock_blind
    tb._locked = False

    locked_during_call = None

    async def fake_get_from_blind(cmd, callback):
        nonlocal locked_during_call
        locked_during_call = tb._locked

    tb.get_from_blind = AsyncMock(side_effect=fake_get_from_blind)

    await tb.get_blind_position()

    assert locked_during_call is True
    assert tb._locked is False
    tb.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_set_speed_locked_raises_error(mock_blind):
    """Test set_speed raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True
    tb._blind_speed = "Standard"

    with pytest.raises(HomeAssistantError) as exc:
        await tb.set_speed()

    assert exc.value.translation_key == "device_locked"


@pytest.mark.asyncio
async def test_set_speed_locks_and_unlocks(mock_blind):
    """Test set_speed acquires lock during command and releases after."""
    tb = mock_blind
    tb._locked = False
    tb._blind_speed = "Standard"
    tb.send_command = AsyncMock()

    locked_during_call = None

    async def fake_send_command(uuid, cmd):
        nonlocal locked_during_call
        locked_during_call = tb._locked

    tb.send_command = AsyncMock(side_effect=fake_send_command)

    await tb.set_speed()

    assert locked_during_call is True
    assert tb._locked is False
    tb.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_async_add_timer_locked_raises_error(mock_blind):
    """Test async_add_timer raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True

    with pytest.raises(HomeAssistantError) as exc:
        await tb.async_add_timer(["mon"], "08:00", 50.0)

    assert exc.value.translation_key == "device_locked"


@pytest.mark.asyncio
async def test_async_delete_timer_locked_raises_error(mock_blind):
    """Test async_delete_timer raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True

    with pytest.raises(HomeAssistantError) as exc:
        await tb.async_delete_timer("1")

    assert exc.value.translation_key == "device_locked"


@pytest.mark.asyncio
async def test_delete_all_timers_locked_raises_error(mock_blind):
    """Test delete_all_timers raises device_locked when blind is busy."""
    tb = mock_blind
    tb._locked = True

    with pytest.raises(HomeAssistantError) as exc:
        await tb.delete_all_timers()

    assert exc.value.translation_key == "device_locked"


def test_lock_status_sensor_reflects_locked_state(mock_blind):
    """Test LockStatusSensor accurately reflects busy (locked) vs idle (unlocked)."""
    tb = mock_blind
    sensor = LockStatusSensor(tb)

    tb._locked = False
    # HA LOCK convention: is_on=True means Unlocked (available)
    assert sensor.is_on is True

    tb._locked = True
    # is_on=False means Locked (busy)
    assert sensor.is_on is False
