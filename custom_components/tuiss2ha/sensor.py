"""Support for Battery sensors."""
from __future__ import annotations

from homeassistant.components.bluetooth import async_last_service_info
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

PARALLEL_UPDATES = 0
SENSOR_TYPES= {
"battery_description": [
        "Battery Status Description",
        None,
        "mdi:battery",
        None,
        None,]
}


async def async_setup_entry(hass: HomeAssistantType, entry: ConfigEntry, async_add_entities) -> None:
    """Set up Tuiss2ha Battery sensor"""
    sensors = []
    for sensor in SENSOR_TYPES:
        sensors.append()
    async_add_entities(sensors, True)

    
