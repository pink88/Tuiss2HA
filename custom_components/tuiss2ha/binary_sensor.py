"""Support for Battery sensors."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Tuiss2ha Battery sensor."""
    hub = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for blind in hub.blinds:
        sensors.append(BatterySensor(blind))
    async_add_entities(sensors, True)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "get_battery_status", {}, async_get_battery_status
    )


async def async_get_battery_status(entity, service_call):
    """Get the battery status when called by service."""
    await entity._blind.get_battery_status()
    entity._attr_is_on = entity._blind._battery_status
    entity.schedule_update_ha_state()


class BatterySensor(BinarySensorEntity, RestoreEntity):
    """Battery sensor for Tuiss2HA Cover."""

    should_poll = False

    def __init__(self, blind) -> None:
        """Initialize the sensor."""
        self._blind = blind
        self._attr_unique_id = f"{self._blind.blind_id}_battery"
        self._attr_name = f"{self._blind.name} Battery"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY

    # To link this entity to the cover device, this property must return an
    # identifiers value matching that used in the cover, but no other information such
    # as name. If name is returned, this entity will then also become a device in the
    # HA UI.
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._blind.blind_id)}}

    @property
    def device_class(self):
        """Return device class."""
        return self._attr_device_class

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        last_state = await self.async_get_last_state()
        # last_state.state = "off" #For debug
        _LOGGER.debug(last_state)
        if last_state.state == "on":
            self._attr_is_on = True
        else:
            self._attr_is_on = False

        # Sensors should also register callbacks to HA when their state changes
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._blind.remove_callback(self.async_write_ha_state)
