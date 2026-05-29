"""Tests for the raw battery level capture in battery_callback."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuiss2ha.hub import TuissBlind


def _make_blind(mock_hass) -> TuissBlind:
    """Build a TuissBlind with bluetooth discovery patched."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"
    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        return_value=fake_device,
    ):
        hub = MagicMock()
        hub._hass = mock_hass
        return TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)


@pytest.mark.asyncio
async def test_battery_level_raw_parsed_from_long_frame(mock_hass):
    """Long-form response should populate _battery_level_raw with LE u16 from bytes [6..8]."""
    tb = _make_blind(mock_hass)
    # Avoid touching BLE / ha state during the callback.
    tb.disconnect = AsyncMock()
    tb.publish_updates = MagicMock()

    # ff 01 02 03 d2 02 e8 03  -> raw value = 0x03e8 = 1000
    data = bytearray.fromhex("ff010203d202e803")
    sender = MagicMock()

    await tb.battery_callback(sender, data)

    assert tb._battery_level_raw == 1000
    assert tb._battery_status is False  # decimals[5]=2 < 10 -> good
    tb.publish_updates.assert_called_once()


@pytest.mark.asyncio
async def test_battery_level_raw_none_for_short_frame(mock_hass):
    """Low-battery (length 7) response should not populate _battery_level_raw."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()
    tb.publish_updates = MagicMock()

    # ff 01 02 03 d2 00 00  -> 7 bytes, len==7 branch -> low battery, no raw level
    data = bytearray.fromhex("ff010203d20000")
    sender = MagicMock()

    await tb.battery_callback(sender, data)

    assert tb._battery_level_raw is None
    assert tb._battery_status is True  # len == 7 -> low
    tb.publish_updates.assert_called_once()


@pytest.mark.asyncio
async def test_battery_level_raw_overwritten_on_subsequent_read(mock_hass):
    """A later good frame should overwrite a previous reading."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()
    tb.publish_updates = MagicMock()

    # First reading: 1000
    await tb.battery_callback(MagicMock(), bytearray.fromhex("ff010203d202e803"))
    assert tb._battery_level_raw == 1000

    # Second reading: 0x01f4 = 500
    await tb.battery_callback(MagicMock(), bytearray.fromhex("ff010203d202f401"))
    assert tb._battery_level_raw == 500


@pytest.mark.asyncio
async def test_battery_level_raw_unset_when_invalid_header(mock_hass):
    """If decimals[4] != 0xd2 the callback exits without touching state."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()
    tb.publish_updates = MagicMock()

    # Pre-seed a reading; an invalid frame must not clobber it.
    tb._battery_level_raw = 999

    # Invalid header byte at position 4
    data = bytearray.fromhex("ff01020399ffffff")
    await tb.battery_callback(MagicMock(), data)

    assert tb._battery_level_raw == 999
    tb.publish_updates.assert_not_called()
