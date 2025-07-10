from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    OPT_FAVORITE_POSITION,
    DEFAULT_FAVORITE_POSITION,
)
from .hub import Hub, TuissBlind

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuiss button entities."""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [TuissFavoritePositionButton(blind, config_entry) for blind in hub.blinds]
    )


class TuissFavoritePositionButton(ButtonEntity):
    """Tuiss 'Go to Favorite Position' button."""

    _attr_has_entity_name = True

    def __init__(self, blind: TuissBlind, config_entry: ConfigEntry) -> None:
        """Initialize the button."""
        self.blind = blind
        self.config_entry = config_entry
        self._attr_unique_id = f"{self.blind.blind_id}_favorite_position"
        self._attr_name = "Go to Favorite Position"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.blind.blind_id)},
            name=self.blind.name,
            manufacturer=self.blind.hub.manufacturer,
            model=self.blind.model,
        )

    async def async_press(self) -> None:
        """Handle the button press by calling the cover's set_position service."""
        favorite_position = self.config_entry.options.get(
            OPT_FAVORITE_POSITION, DEFAULT_FAVORITE_POSITION
        )
        _LOGGER.info(
            "Moving blind %s to favorite position %s%%",
            self.blind.name,
            favorite_position,
        )

        # Find the cover entity and call its service
        ent_reg = er.async_get(self.hass)
        cover_unique_id = f"{self.blind.blind_id}_cover"
        cover_entity_id = ent_reg.async_get_entity_id(
            Platform.COVER, DOMAIN, cover_unique_id
        )

        if cover_entity_id:
            await self.hass.services.async_call(
                "cover",
                "set_cover_position",
                {
                    "entity_id": cover_entity_id,
                    "position": favorite_position,
                },
                blocking=False,
            )
        else:
            _LOGGER.warning(
                "Could not find cover entity for blind %s to set favorite position",
                self.blind.name,
            ) 