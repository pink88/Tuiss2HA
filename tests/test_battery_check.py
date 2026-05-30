from unittest.mock import AsyncMock, MagicMock, patch

import datetime
import pytest

from homeassistant.util import dt as dt_util

from custom_components.tuiss2ha.hub import TuissBlind


@pytest.mark.asyncio
async def test_battery_check_runs_if_never_checked(mock_hass):
    """If no last battery check exists and option > 0, get_battery_status is called."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

        # Configure to require checks every 1 day and never checked before
        tb._battery_check_days = 1
        tb._last_battery_check = None

        # Patch connection/movement helpers so movement completes quickly
        async def fake_attempt_connection():
            tb._client = MagicMock()
            tb._client.is_connected = True

        tb.attempt_connection = AsyncMock(side_effect=fake_attempt_connection)
        tb.set_position = AsyncMock()
        tb.wait_for_stop = AsyncMock()
        tb.disconnect = AsyncMock()

        tb.get_battery_status = AsyncMock()

        # Prevent traversal speed division by zero during test by stubbing
        tb.update_traversal_speed = MagicMock()

        # Ensure current position is set so movement logic runs
        tb._current_cover_position = 10

        await tb.async_move_cover(movement_direction=1, target_position=50)

        assert tb.get_battery_status.called


@pytest.mark.asyncio
async def test_battery_check_skipped_if_recent(mock_hass):
    """If last battery check is recent (less than configured days), get_battery_status is not called."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

        # Configure to require checks every 7 days and last checked 1 day ago
        tb._battery_check_days = 7
        tb._last_battery_check = dt_util.now() - datetime.timedelta(days=1)

        # Patch connection/movement helpers so movement completes quickly
        async def fake_attempt_connection():
            tb._client = MagicMock()
            tb._client.is_connected = True

        tb.attempt_connection = AsyncMock(side_effect=fake_attempt_connection)
        tb.set_position = AsyncMock()
        tb.wait_for_stop = AsyncMock()
        tb.disconnect = AsyncMock()

        tb.get_battery_status = AsyncMock()

        # Prevent traversal speed division by zero during test by stubbing
        tb.update_traversal_speed = MagicMock()

        tb._current_cover_position = 10

        await tb.async_move_cover(movement_direction=1, target_position=50)

        assert not tb.get_battery_status.called


@pytest.mark.asyncio
async def test_battery_check_runs_if_older_than_config(mock_hass):
    """If last battery check is older than configured days, get_battery_status is called."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"

    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", return_value=fake_device):
        hub = MagicMock()
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)

        # Configure to require checks every 1 day and last checked 3 days ago
        tb._battery_check_days = 1
        tb._last_battery_check = dt_util.now() - datetime.timedelta(days=3)

        # Patch connection/movement helpers so movement completes quickly
        async def fake_attempt_connection():
            tb._client = MagicMock()
            tb._client.is_connected = True

        tb.attempt_connection = AsyncMock(side_effect=fake_attempt_connection)
        tb.set_position = AsyncMock()
        tb.wait_for_stop = AsyncMock()
        tb.disconnect = AsyncMock()

        tb.get_battery_status = AsyncMock()

        # Prevent traversal speed division by zero during test by stubbing
        tb.update_traversal_speed = MagicMock()

        tb._current_cover_position = 10

        await tb.async_move_cover(movement_direction=1, target_position=50)

        assert tb.get_battery_status.called
