"""Position preset select entity for Tuiss2HA."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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

    Picking an option calls the cover's set_cover_position service with the
    stored value. The list of options is derived from blind.presets so it
    stays in sync after save_preset / delete_preset service calls.
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
        self._attr_current_option = None

    @property
    def options(self) -> list[str]:
        """Return preset names sorted alphabetically for stable display."""
        return sorted(self.blind.presets.keys())

    @property
    def available(self) -> bool:
        """Available only when at least one preset is defined."""
        return bool(self.blind.presets)

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen preset by moving the cover to its position."""
        if option not in self.blind.presets:
            _LOGGER.warning(
                "%s: Preset %r not found; available: %s",
                self.blind.name, option, list(self.blind.presets),
            )
            return
        position = self.blind.presets[option]
        _LOGGER.info(
            "%s: Applying preset %r -> position %s%%",
            self.blind.name, option, position,
        )

        ent_reg = er.async_get(self.hass)
        cover_unique_id = f"{self.blind.blind_id}_cover"
        cover_entity_id = ent_reg.async_get_entity_id(
            Platform.COVER, DOMAIN, cover_unique_id
        )
        if not cover_entity_id:
            _LOGGER.warning(
                "%s: Could not find cover entity for preset %r",
                self.blind.name, option,
            )
            return

        await self.hass.services.async_call(
            "cover",
            "set_cover_position",
            {"entity_id": cover_entity_id, "position": position},
            blocking=False,
        )
        self._attr_current_option = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callbacks so the dropdown refreshes on preset changes."""
        self.blind.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks."""
        self.blind.remove_callback(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        """Refresh entity state when presets change."""
        # Clear current_option if the previously selected preset was removed
        if self._attr_current_option and self._attr_current_option not in self.blind.presets:
            self._attr_current_option = None
        self.async_write_ha_state()
