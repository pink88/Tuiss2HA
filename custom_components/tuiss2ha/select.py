"""Position preset select entity for Tuiss2HA."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import Hub, TuissBlind

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuiss select entities (one preset selector per blind)."""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [TuissPresetSelect(blind) for blind in hub.blinds]
    )


class TuissPresetSelect(SelectEntity):
    """Dropdown of saved position presets for a Tuiss blind.

    The selected option is *derived* from the live cover position rather
    than stored: any preset whose value matches the current position is
    shown as selected, and the dropdown clears as soon as the blind is
    moved away. This keeps the entity from claiming the blind is at
    "Movie" when the user has manually slid it elsewhere.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bookmark-multiple"
    should_poll = False

    def __init__(self, blind: TuissBlind) -> None:
        """Initialize the select entity."""
        self.blind = blind
        self._attr_unique_id = f"{self.blind.blind_id}_preset_select"
        self._attr_name = "Preset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.blind.blind_id)},
            name=self.blind.name,
            manufacturer=self.blind.hub.manufacturer,
            model=self.blind.model,
        )

    @property
    def options(self) -> list[str]:
        """Return preset names sorted alphabetically for stable display."""
        return sorted(self.blind.presets.keys())

    @property
    def available(self) -> bool:
        """Available only when at least one preset is defined."""
        return bool(self.blind.presets)

    @property
    def current_option(self) -> str | None:
        """Match the live cover position to a preset, else ``None``.

        Recomputed every read so the dropdown reflects reality:
        - Manual cover moves clear the selection.
        - Re-arriving at a preset position re-selects it automatically.
        - When two presets share a value, the alphabetically-first
          name wins so the result is stable.
        - Compares with a 0.5%% tolerance so intermediate readings from
          the BLE position stream don't flicker the dropdown off the
          matching preset name (firmware reports at 0.1%% resolution).
        """
        pos = self.blind.current_position
        if pos is None:
            return None
        for name in sorted(self.blind.presets):
            if abs(self.blind.presets[name] - pos) < 0.5:
                return name
        return None

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen preset by delegating to the blind helper."""
        await self.blind.async_apply_preset(option)
        # No need to set _attr_current_option — current_option is
        # derived from the live position, which the cover will publish
        # via publish_updates() once the move starts.

    async def async_added_to_hass(self) -> None:
        """Register callbacks so the dropdown refreshes on state changes."""
        self.blind.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks."""
        self.blind.remove_callback(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        """Refresh entity state when presets or position change."""
        self.async_write_ha_state()
