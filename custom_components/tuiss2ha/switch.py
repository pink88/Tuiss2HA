"""Platform for switch integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add switch orientation."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    sensors = []
    for blind in hub.blinds:
        sensors.append(SwitchOrientation(blind))
    async_add_entities(sensors, True)


class SwitchOrientation(SwitchEntity, RestoreEntity):
    """Switch Orientation for Tuiss2HA Cover."""

    def __init__(self, blind) -> None:
        """Initialize the sensor."""
        self._blind = blind
        self._state = False
        self._attr_unique_id = f"{self._blind.blind_id}_orientation"
        self._attr_name = f"{self._blind.name} Orientation"
        self._attr_device_class = SwitchDeviceClass.SWITCH

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set orientation to normal."""
        self._state = False
        self._blind._desired_orientation = False
        self.schedule_update_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set orientation to opposite."""
        self._state = True
        self._blind._desired_orientation = True
        self.schedule_update_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return True if orientation is opposite or False if Normal"""
        return self._state
