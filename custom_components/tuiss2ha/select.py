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
        """Match the live position to a preset within 0.5% tolerance, else None."""
        pos = self.blind.current_position
        if pos is None:
            return None
        for name in sorted(self.blind.presets):
            if abs(self.blind.presets[name] - pos) <= 0.5:
                return name
        return None

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen preset."""
        await self.blind.async_apply_preset(option)

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
