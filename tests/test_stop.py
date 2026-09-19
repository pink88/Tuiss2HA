"""Test cover stop command and cleandown behavior."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuiss2ha.const import CMD_STOP, UUID
from custom_components.tuiss2ha.cover import Tuiss
from custom_components.tuiss2ha.hub import TuissBlind


@pytest.fixture
def fake_ble_client():
    """Create a mock BLE client for testing."""
    client = MagicMock()
    client.is_connected = True
    client.write_gatt_char = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def mock_blind(mock_hass, fake_ble_client):
    """Create a TuissBlind instance with mocked BLE dependencies."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        return_value=fake_device,
    ):
        hub = MagicMock()
        mock_hass.async_create_task = asyncio.create_task
        mock_hass.loop = MagicMock()
        hub._hass = mock_hass

        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test Blind", hub)
        tb._client = fake_ble_client
        tb._restart_attempts = 1
        tb._current_cover_position = 0.0
        return tb


@pytest.mark.asyncio
async def test_stop_while_moving_cleans_down_state(mock_blind, fake_ble_client):
    """Test that pressing stop while the blind is moving performs all cleandown tasks."""
    tb = mock_blind

    # Mock attempt_connection so it doesn't try real BLE calls
    tb.attempt_connection = AsyncMock()

    # Start moving the cover in a background task
    move_task = asyncio.create_task(
        tb.async_move_cover(
            movement_direction=1,
            target_position=50,
            skip_battery_check=True,
        )
    )

    # Wait until movement has started and lock is acquired
    for _ in range(50):
        if tb._locked and tb._moving != 0:
            break
        await asyncio.sleep(0.01)

    assert tb._locked is True
    assert tb._moving == 1
    assert tb._is_stopping is False

    # Issue the stop command while the blind is moving
    await tb.stop()

    # Wait for the move task to unblock and finish its cleanup
    await asyncio.wait_for(move_task, timeout=2.0)

    # Verify all cleandown state
    assert tb._locked is False, "Lock should be released after stop"
    assert tb._moving == 0, "Moving direction should be reset to 0"
    assert tb._is_stopping is False, "is_stopping flag should be reset to False"
    assert tb._stopped_event.is_set(), "_stopped_event should be set to unblock waiters"

    # Verify that the STOP command was sent over BLE
    stop_cmd_bytes = bytes.fromhex(CMD_STOP)
    fake_ble_client.write_gatt_char.assert_any_call(UUID, stop_cmd_bytes)

    # Verify that disconnect was called as part of move cleanup
    fake_ble_client.disconnect.assert_called()

    # Verify that a post-move query was scheduled to fetch final resting position
    assert tb._post_move_task is not None

    # Cancel the post-move background task before test teardown
    await tb._cancel_post_move_task()


@pytest.mark.asyncio
async def test_cover_entity_async_stop_cover_cleans_down(mock_blind, fake_ble_client):
    """Test that cover.async_stop_cover cleans down state without raising any exceptions."""
    tb = mock_blind
    tb.attempt_connection = AsyncMock()

    # Create Cover entity wrapping the blind
    config = MagicMock()
    config.options = {}
    cover = Tuiss(tb, config)

    # Start cover moving
    move_task = asyncio.create_task(
        tb.async_move_cover(
            movement_direction=1,
            target_position=100,
            skip_battery_check=True,
        )
    )

    # Wait until movement is active
    for _ in range(50):
        if tb._locked and tb._moving != 0:
            break
        await asyncio.sleep(0.01)

    assert tb._locked is True

    # Call async_stop_cover through the entity
    await cover.async_stop_cover()

    # Wait for move task to finish
    await asyncio.wait_for(move_task, timeout=2.0)

    # Verify clean state
    assert tb._locked is False
    assert tb._moving == 0
    assert tb._is_stopping is False

    # Clean up any scheduled tasks
    await tb._cancel_post_move_task()


@pytest.mark.asyncio
async def test_stop_when_not_moving_is_noop(mock_blind, fake_ble_client):
    """Test that calling stop when the blind is not moving does nothing."""
    tb = mock_blind
    tb._moving = 0
    tb._locked = False

    await tb.stop()

    assert tb._locked is False
    assert tb._moving == 0
    assert tb._is_stopping is False
    # No write command should have been sent
    fake_ble_client.write_gatt_char.assert_not_called()
