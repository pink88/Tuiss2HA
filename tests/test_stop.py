"""Test cover stop command and cleandown behavior."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuiss2ha.const import CMD_STOP, UUID, ConnectionTimeout
from custom_components.tuiss2ha.cover import (
    Tuiss,
    HomeAssistantError,
    STATE_OPENING,
    STATE_CLOSING,
)
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


@pytest.mark.asyncio
async def test_rapid_move_commands_rejected_with_locked_error(mock_blind, fake_ble_client):
    """Test that rapid button clicks while connection or movement is starting are locked out."""
    tb = mock_blind

    connection_started = asyncio.Event()
    allow_connection = asyncio.Event()

    async def slow_attempt_connection():
        connection_started.set()
        await allow_connection.wait()

    tb.attempt_connection = AsyncMock(side_effect=slow_attempt_connection)

    # Launch first command (e.g. Open)
    first_task = asyncio.create_task(
        tb.async_move_cover(movement_direction=1, target_position=0, skip_battery_check=True)
    )

    await connection_started.wait()

    # The blind should already be locked and moving up, even before connection completes
    assert tb._locked is True
    assert tb._moving == 1

    # Attempt a second command (e.g. Close) while first is still connecting
    with pytest.raises(HomeAssistantError) as exc_info:
        await tb.async_move_cover(movement_direction=-1, target_position=100, skip_battery_check=True)

    assert exc_info.value.translation_key == "device_locked"
    # Moving state and direction must NOT have been overwritten by second command
    assert tb._moving == 1
    assert tb._locked is True

    # Allow first task to proceed and then stop it
    allow_connection.set()
    await tb.stop()
    await asyncio.wait_for(first_task, timeout=2.0)
    await tb._cancel_post_move_task()


@pytest.mark.asyncio
async def test_move_updates_state_and_locks_immediately_before_connection(mock_blind, fake_ble_client):
    """Test that UI state reflects opening/closing immediately before BLE connection."""
    tb = mock_blind
    config = MagicMock()
    config.options = {}
    cover = Tuiss(tb, config)

    allow_connection = asyncio.Event()

    async def slow_attempt_connection():
        await allow_connection.wait()

    tb.attempt_connection = AsyncMock(side_effect=slow_attempt_connection)

    # Launch move task
    move_task = asyncio.create_task(
        tb.async_move_cover(movement_direction=1, target_position=0, skip_battery_check=True)
    )

    # Immediately (without waiting for connection to finish), verify entity state
    await asyncio.sleep(0)

    assert tb._locked is True
    assert tb._moving == 1
    assert cover.state == STATE_OPENING
    assert cover.is_opening is True
    assert cover.is_closing is False

    allow_connection.set()
    await tb.stop()
    await asyncio.wait_for(move_task, timeout=2.0)
    await tb._cancel_post_move_task()


@pytest.mark.asyncio
async def test_stop_during_connection_aborts_move_without_sending_position(mock_blind, fake_ble_client):
    """Test that pressing stop while connection is in progress aborts cleanly without sending move."""
    tb = mock_blind
    tb.set_position = AsyncMock()

    allow_connection = asyncio.Event()

    async def slow_attempt_connection():
        await allow_connection.wait()

    tb.attempt_connection = AsyncMock(side_effect=slow_attempt_connection)

    move_task = asyncio.create_task(
        tb.async_move_cover(movement_direction=1, target_position=0, skip_battery_check=True)
    )

    await asyncio.sleep(0)
    assert tb._moving == 1

    # User clicks stop before connection completes
    await tb.stop()
    allow_connection.set()

    await asyncio.wait_for(move_task, timeout=2.0)

    # set_position should NOT have been called
    tb.set_position.assert_not_called()
    assert tb._locked is False
    assert tb._moving == 0


@pytest.mark.asyncio
async def test_connection_failure_restores_unlocked_and_idle_state(mock_blind, fake_ble_client):
    """Test that if connection fails or raises, locked and moving states are restored to idle."""
    tb = mock_blind
    tb.attempt_connection = AsyncMock(side_effect=ConnectionTimeout("device unreachable"))

    with pytest.raises(ConnectionTimeout):
        await tb.async_move_cover(movement_direction=1, target_position=0, skip_battery_check=True)

    assert tb._locked is False
    assert tb._moving == 0
