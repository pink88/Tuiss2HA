from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
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
    """Set up the Tuiss sensor entities."""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([TuissSignalSensor(blind) for blind in hub.blinds])


class TuissSignalSensor(SensorEntity):
    """Tuiss Signal Strength Sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, blind: TuissBlind) -> None:
        """Initialize the sensor."""
        self.blind = blind
        self._attr_unique_id = f"{self.blind.blind_id}_signal_strength"
        self._attr_name = "Signal Strength"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.blind.blind_id)},
            name=self.blind.name,
            manufacturer=self.blind.hub.manufacturer,
            model=self.blind.model,
        )
        self._attr_native_value = self.blind.rssi

    @property
    def available(self) -> bool:
        """Return True if the blind is available."""
        return True

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        return self.blind.rssi

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.blind.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks."""
        self.blind.remove_callback(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the hub."""
        self._attr_native_value = self.blind.rssi
        self.async_write_ha_state() 