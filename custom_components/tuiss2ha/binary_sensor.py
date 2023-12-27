"""Support for Battery sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up Tuiss2ha Battery sensor."""
    hub = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for blind in hub.blinds:
        sensors.append(BatterySensor(blind))
    async_add_entities(sensors, True)



class BatterySensor(BinarySensorEntity):
    """Battery sensor for Tuiss2HA Cover."""

    should_poll = False

    def __init__(self, blind) -> None:
        """Initialize the sensor."""
        self._blind = blind
        self._attr_unique_id = f"{self._blind.blind_id}_battery"
        self._attr_name = f"{self._blind.name} Battery"
        self._status = False
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
    def is_on(self) -> bool:
        """Is the battery on or off."""
        return self._status

    @property
    def device_class(self):
        """Return device class."""
        return self._attr_device_class

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._blind.remove_callback(self.async_write_ha_state)
