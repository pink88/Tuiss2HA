"""Tests for the position presets feature: storage + select entity + services."""
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
async def test_async_load_presets_empty_when_store_empty(mock_hass):
    """No stored data should leave presets as an empty dict."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value=None)

    await tb.async_load_presets()

    assert tb.presets == {}


@pytest.mark.asyncio
async def test_async_load_presets_round_trips(mock_hass):
    """Stored dict is loaded verbatim into blind.presets."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(
        return_value={"Morning": 100, "Movie": 30, "Sleep": 0}
    )

    await tb.async_load_presets()

    assert tb.presets == {"Morning": 100, "Movie": 30, "Sleep": 0}


@pytest.mark.asyncio
async def test_async_load_presets_drops_invalid_entries(mock_hass):
    """Malformed entries are dropped without raising."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(
        return_value={
            "Good": 50,
            "OutOfRange": 150,            # > 100 -> dropped
            "Negative": -1,                # < 0 -> dropped
            "BadType": "not-a-number",     # not coercible -> dropped
            "": 25,                         # empty name -> dropped
        }
    )

    await tb.async_load_presets()

    assert tb.presets == {"Good": 50}


@pytest.mark.asyncio
async def test_async_save_presets_persists(mock_hass):
    """Saving forwards the current presets dict to the store."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.presets = {"X": 10, "Y": 90}

    await tb.async_save_presets()

    tb._presets_store.async_save.assert_awaited_once_with({"X": 10, "Y": 90})


@pytest.mark.asyncio
async def test_async_load_presets_coerces_string_positions(mock_hass):
    """Storage layer may give back strings; loader should coerce to int."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value={"Morning": "75"})

    await tb.async_load_presets()

    assert tb.presets == {"Morning": 75}
    assert isinstance(tb.presets["Morning"], int)


@pytest.mark.asyncio
async def test_async_load_presets_handles_non_dict_payload(mock_hass):
    """A corrupt non-dict payload should reset to empty rather than crash."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value=["unexpected", "list"])

    await tb.async_load_presets()

    assert tb.presets == {}


@pytest.mark.asyncio
async def test_save_current_stores_rounded_position(mock_hass):
    """async_save_current_as_preset rounds the live position to int."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb._current_cover_position = 42.7

    result = await tb.async_save_current_as_preset("Reading")

    assert result == 43
    assert tb.presets == {"Reading": 43}
    tb._presets_store.async_save.assert_awaited_once_with({"Reading": 43})
    tb.publish_updates.assert_called_once()


@pytest.mark.asyncio
async def test_save_current_returns_none_when_position_unknown(mock_hass):
    """If the cover position has never been read, refuse and don't persist."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb._current_cover_position = None

    result = await tb.async_save_current_as_preset("Reading")

    assert result is None
    assert tb.presets == {}
    tb._presets_store.async_save.assert_not_called()
    tb.publish_updates.assert_not_called()


@pytest.mark.asyncio
async def test_save_current_overwrites_existing_name(mock_hass):
    """Re-using a preset name overwrites the old position."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb.presets = {"Reading": 10}
    tb._current_cover_position = 75

    result = await tb.async_save_current_as_preset("Reading")

    assert result == 75
    assert tb.presets == {"Reading": 75}
    tb._presets_store.async_save.assert_awaited_once_with({"Reading": 75})


@pytest.mark.asyncio
async def test_save_current_handles_integer_position(mock_hass):
    """An integer position is stored as-is (round is a no-op)."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb._current_cover_position = 50

    result = await tb.async_save_current_as_preset("Half")

    assert result == 50
    assert tb.presets == {"Half": 50}
