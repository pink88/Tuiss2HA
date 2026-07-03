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
    """Malformed entries are dropped and the cleaned dict is re-persisted."""
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
    tb._presets_store.async_save = AsyncMock()

    await tb.async_load_presets()

    assert tb.presets == {"Good": 50.0}
    # Cleaned dict re-persisted so the next restart doesn't re-walk garbage.
    tb._presets_store.async_save.assert_awaited_once_with({"Good": 50.0})


@pytest.mark.asyncio
async def test_async_load_presets_does_not_resave_when_clean(mock_hass):
    """If every stored entry is valid, no re-save happens at load time."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value={"Morning": 80})
    tb._presets_store.async_save = AsyncMock()

    await tb.async_load_presets()

    assert tb.presets == {"Morning": 80.0}
    tb._presets_store.async_save.assert_not_awaited()


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
    """Storage layer may give back strings; loader should coerce to float."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value={"Morning": "75.5"})

    await tb.async_load_presets()

    assert tb.presets == {"Morning": 75.5}
    assert isinstance(tb.presets["Morning"], float)


@pytest.mark.asyncio
async def test_async_load_presets_handles_non_dict_payload(mock_hass):
    """A corrupt non-dict payload should reset to empty rather than crash."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(return_value=["unexpected", "list"])

    await tb.async_load_presets()

    assert tb.presets == {}


@pytest.mark.asyncio
async def test_save_current_preserves_float_precision(mock_hass):
    """async_save_current_as_preset stores the live position as a float.

    The blind hardware reports position at 0.1% resolution. Preserve it
    end-to-end so save → apply round-trips don't drop fractional bits.
    """
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb._current_cover_position = 42.7

    result = await tb.async_save_current_as_preset("Reading")

    assert result == 42.7
    assert tb.presets == {"Reading": 42.7}
    tb._presets_store.async_save.assert_awaited_once_with({"Reading": 42.7})
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

    assert result == 75.0
    assert tb.presets == {"Reading": 75.0}
    tb._presets_store.async_save.assert_awaited_once_with({"Reading": 75.0})


@pytest.mark.asyncio
async def test_save_current_handles_integer_position(mock_hass):
    """An integer-typed position is coerced to float for consistency."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()
    tb._current_cover_position = 50

    result = await tb.async_save_current_as_preset("Half")

    assert result == 50.0
    assert tb.presets == {"Half": 50.0}


def _make_select(mock_hass):
    """Build a TuissPresetSelect bound to a fresh blind."""
    from custom_components.tuiss2ha.select import TuissPresetSelect
    tb = _make_blind(mock_hass)
    return TuissPresetSelect(tb), tb


def test_select_current_option_none_when_position_unknown(mock_hass):
    """Position never read -> dropdown shows nothing selected."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Movie": 30, "Morning": 100}
    tb._current_cover_position = None

    assert sel.current_option is None


def test_select_current_option_matches_exact_position(mock_hass):
    """Live position equal to a preset value -> that preset is selected."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Movie": 30, "Morning": 100, "Sleep": 0}
    tb._current_cover_position = 30

    assert sel.current_option == "Movie"


def test_select_current_option_none_when_no_match(mock_hass):
    """Position between presets -> nothing selected."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Movie": 30, "Morning": 100}
    tb._current_cover_position = 55

    assert sel.current_option is None


def test_select_current_option_matches_with_tolerance(mock_hass):
    """0.5% tolerance accepts intermediate BLE readings near a preset."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Morning": 100.0}
    # 99.7 vs 100.0 — within tolerance.
    tb._current_cover_position = 99.7

    assert sel.current_option == "Morning"


def test_select_current_option_preserves_float_preset(mock_hass):
    """Float-stored preset matches exact float live position."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Reading": 42.7}
    tb._current_cover_position = 42.7

    assert sel.current_option == "Reading"


def test_select_current_option_alphabetical_tiebreak(mock_hass):
    """When two presets share a value, the alphabetically-first wins."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Zeta": 50, "Alpha": 50, "Mid": 50}
    tb._current_cover_position = 50

    # sorted({"Zeta","Alpha","Mid"}) -> "Alpha","Mid","Zeta" -> first match Alpha
    assert sel.current_option == "Alpha"


def test_select_current_option_clears_after_manual_move(mock_hass):
    """A manual move away from the preset clears the selection."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Movie": 30}
    tb._current_cover_position = 30
    assert sel.current_option == "Movie"

    # User manually drags blind to 70 — no service call, just position update
    tb._current_cover_position = 70
    assert sel.current_option is None


def test_select_current_option_re_selects_on_return(mock_hass):
    """Returning to a preset position re-selects it automatically."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Reading": 42}
    tb._current_cover_position = 100  # somewhere else
    assert sel.current_option is None

    # Move back to the preset value
    tb._current_cover_position = 42
    assert sel.current_option == "Reading"


def test_select_options_sorted(mock_hass):
    """Options list is alphabetically sorted for stable UI display."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {"Zeta": 1, "Alpha": 2, "Mid": 3}

    assert sel.options == ["Alpha", "Mid", "Zeta"]


def test_select_unavailable_when_no_presets(mock_hass):
    """The entity reports itself unavailable when no presets are defined."""
    sel, tb = _make_select(mock_hass)
    tb.presets = {}

    assert sel.available is False


# ---------------------------------------------------------------------------
# Schema + resolver guards
# ---------------------------------------------------------------------------


def test_preset_name_schema_strips_whitespace():
    """The shared name schema must trim leading/trailing whitespace."""
    from custom_components.tuiss2ha import _PRESET_NAME_SCHEMA

    assert _PRESET_NAME_SCHEMA("  Morning  ") == "Morning"


def test_preset_name_schema_rejects_blank():
    """Whitespace-only or empty names must be refused before reaching storage."""
    import voluptuous as vol
    from custom_components.tuiss2ha import _PRESET_NAME_SCHEMA

    with pytest.raises(vol.Invalid):
        _PRESET_NAME_SCHEMA("")
    with pytest.raises(vol.Invalid):
        _PRESET_NAME_SCHEMA("   ")
    with pytest.raises(vol.Invalid):
        _PRESET_NAME_SCHEMA("\t\n")


def test_resolve_rejects_non_preset_entity(mock_hass):
    """Resolver must refuse tuiss2ha entities that aren't cover/preset select.

    Battery, signal-strength, model etc. share the integration platform but
    are not valid preset-service targets. The resolver should return None
    rather than falling back to a fragile rsplit that accidentally yields
    the correct blind only because MAC addresses lack underscores.
    """
    from custom_components.tuiss2ha import _resolve_blind_from_entity_id, DOMAIN
    from custom_components.tuiss2ha.hub import Hub

    blind = MagicMock()
    blind.blind_id = "AA:BB:CC:DD:EE:FF"
    hub = MagicMock(spec=Hub)
    hub.blinds = [blind]
    mock_hass.data = {DOMAIN: {"entry": hub}}

    # Fake the entity registry — return an entry for a battery sensor.
    fake_entry = MagicMock()
    fake_entry.platform = DOMAIN
    fake_entry.unique_id = "AA:BB:CC:DD:EE:FF_battery"

    with patch(
        "custom_components.tuiss2ha.er.async_get",
        return_value=MagicMock(async_get=MagicMock(return_value=fake_entry)),
    ):
        result = _resolve_blind_from_entity_id(
            mock_hass, "binary_sensor.blind_test_battery"
        )

    assert result is None


def test_resolve_accepts_cover_and_preset_select(mock_hass):
    """Resolver must accept both the cover entity and the preset select entity."""
    from custom_components.tuiss2ha import _resolve_blind_from_entity_id, DOMAIN
    from custom_components.tuiss2ha.hub import Hub

    blind = MagicMock()
    blind.blind_id = "AA:BB:CC:DD:EE:FF"
    hub = MagicMock(spec=Hub)
    hub.blinds = [blind]
    mock_hass.data = {DOMAIN: {"entry": hub}}

    for suffix in ("_cover", "_preset_select"):
        fake_entry = MagicMock()
        fake_entry.platform = DOMAIN
        fake_entry.unique_id = f"AA:BB:CC:DD:EE:FF{suffix}"
        with patch(
            "custom_components.tuiss2ha.er.async_get",
            return_value=MagicMock(async_get=MagicMock(return_value=fake_entry)),
        ):
            result = _resolve_blind_from_entity_id(mock_hass, "ignored.id")
        assert result is blind, f"resolver must accept {suffix}"


@pytest.mark.asyncio
async def test_select_raises_on_unknown_option(mock_hass):
    """Selecting a preset that no longer exists must surface as an error."""
    from homeassistant.exceptions import HomeAssistantError

    sel, tb = _make_select(mock_hass)
    tb.presets = {"Morning": 80}
    # SelectEntity reads self.hass; the mocked base doesn't supply it.
    sel.hass = mock_hass

    with pytest.raises(HomeAssistantError, match="not found"):
        await sel.async_select_option("Nope")


# ---------------------------------------------------------------------------
# Behaviour added for review feedback
# ---------------------------------------------------------------------------


def test_position_schema_preserves_floats():
    """Schema keeps float precision so storage round-trips at 0.1%."""
    from custom_components.tuiss2ha import _PRESET_POSITION_SCHEMA

    assert _PRESET_POSITION_SCHEMA(99.9) == 99.9
    assert _PRESET_POSITION_SCHEMA(49.5) == 49.5
    assert _PRESET_POSITION_SCHEMA(0) == 0.0
    assert _PRESET_POSITION_SCHEMA(100) == 100.0
    assert isinstance(_PRESET_POSITION_SCHEMA(42), float)


def test_position_schema_rejects_out_of_range():
    """Bound check is still applied after rounding."""
    import voluptuous as vol
    from custom_components.tuiss2ha import _PRESET_POSITION_SCHEMA

    with pytest.raises(vol.Invalid):
        _PRESET_POSITION_SCHEMA(-1)
    with pytest.raises(vol.Invalid):
        _PRESET_POSITION_SCHEMA(101)
    with pytest.raises(vol.Invalid):
        _PRESET_POSITION_SCHEMA("not-a-number")


def test_current_position_property_exposes_internal_state(mock_hass):
    """Platforms must read position via the public property, not _current_cover_position."""
    tb = _make_blind(mock_hass)
    assert tb.current_position is None
    tb._current_cover_position = 42.7
    assert tb.current_position == 42.7


@pytest.mark.asyncio
async def test_async_save_current_rejects_blank_name(mock_hass):
    """Hub-level guard so direct Python callers can't bypass the service schema."""
    tb = _make_blind(mock_hass)
    tb._current_cover_position = 50

    with pytest.raises(ValueError):
        await tb.async_save_current_as_preset("")
    with pytest.raises(ValueError):
        await tb.async_save_current_as_preset("   ")


@pytest.mark.asyncio
async def test_async_load_presets_swallows_storage_errors(mock_hass):
    """Corrupt storage must not crash entity setup."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_load = AsyncMock(side_effect=ValueError("corrupt JSON"))

    await tb.async_load_presets()

    assert tb.presets == {}


@pytest.mark.asyncio
async def test_async_apply_preset_raises_for_unknown(mock_hass):
    """Hub helper raises HomeAssistantError so both UI and services share behaviour."""
    from homeassistant.exceptions import HomeAssistantError

    tb = _make_blind(mock_hass)
    tb.presets = {"Morning": 80}
    tb._current_cover_position = 50  # known; otherwise the apply guard short-circuits

    with pytest.raises(HomeAssistantError, match="not found"):
        await tb.async_apply_preset("Nope")


@pytest.mark.asyncio
async def test_async_apply_preset_refuses_when_position_unknown(mock_hass):
    """Apply must refuse rather than guess direction from an unknown position."""
    from homeassistant.exceptions import HomeAssistantError

    tb = _make_blind(mock_hass)
    tb.presets = {"Morning": 80}
    tb._current_cover_position = None

    with pytest.raises(HomeAssistantError, match="unknown"):
        await tb.async_apply_preset("Morning")


@pytest.mark.asyncio
async def test_async_apply_preset_dispatches_with_correct_direction(mock_hass):
    """Success path: helper resolves direction and calls async_move_cover."""
    tb = _make_blind(mock_hass)
    tb.presets = {"Up": 80.0, "Down": 20.0}
    tb._current_cover_position = 50.0
    tb.async_move_cover = AsyncMock()

    await tb.async_apply_preset("Up")
    tb.async_move_cover.assert_awaited_with(
        movement_direction=1, target_position=20.0
    )

    tb.async_move_cover.reset_mock()
    await tb.async_apply_preset("Down")
    tb.async_move_cover.assert_awaited_with(
        movement_direction=-1, target_position=80.0
    )


@pytest.mark.asyncio
async def test_async_save_current_clamps_out_of_range(mock_hass):
    """A bad BLE frame can't poison storage with a >100 or <0 value."""
    tb = _make_blind(mock_hass)
    tb._presets_store = MagicMock()
    tb._presets_store.async_save = AsyncMock()
    tb.publish_updates = MagicMock()

    tb._current_cover_position = 105.4
    result = await tb.async_save_current_as_preset("HighGlitch")
    assert result == 100.0

    tb._current_cover_position = -5.0
    result = await tb.async_save_current_as_preset("LowGlitch")
    assert result == 0.0
