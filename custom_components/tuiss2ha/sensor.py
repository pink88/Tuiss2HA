"""Platform for sensor integration."""

from __future__ import annotations

import logging
from typing import Any
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, ServiceCall
import voluptuous as vol
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.helpers import entity_platform, config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .hub import TuissBlind, Hub

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up sensor platform for config entry: %s", config_entry.entry_id)
    
    # Clean up orphaned timer entities from the registry
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    for entry in entries:
        if entry.domain == "sensor" and "_timer_" in entry.unique_id:
            timer_id = entry.unique_id.split("_timer_")[-1]
            timer_exists = False
            for blind in hub.blinds:
                if blind.blind_id in entry.unique_id and timer_id in blind.timers:
                    timer_exists = True
                    break
            if not timer_exists:
                _LOGGER.debug("Removing orphaned timer entity: %s", entry.entity_id)
                registry.async_remove(entry.entity_id)
    
    # 1. Add sensors for timers that already exist in storage
    for blind in hub.blinds:
        existing_sensors = []
        for timer_id in blind.timers:
            existing_sensors.append(TuissTimerSensor(blind, timer_id))
            _LOGGER.debug("Adding existing timer sensor %s for blind %s", timer_id, blind.blind_id)
        if existing_sensors:
            async_add_entities(existing_sensors)
        async_add_entities([TuissSignalSensor(blind)])
            
        # 2. Listen for newly created timers dynamically
        def _create_add_timer_listener(current_blind):
            @callback
            def async_add_timer_sensor(timer_id: str) -> None:
                """Add a new timer sensor dynamically."""
                _LOGGER.debug("Dynamically adding new timer sensor %s for blind %s", timer_id, current_blind.blind_id)
                async_add_entities([TuissTimerSensor(current_blind, timer_id)])
            return async_add_timer_sensor

        config_entry.async_on_unload(
            async_dispatcher_connect(
                hass, 
                f"{DOMAIN}_add_timer_{blind.blind_id}", 
                _create_add_timer_listener(blind)
            )
        )
        
    # Register the delete action as a standard global service
    async def async_action_delete_blind_timer(call: ServiceCall) -> None:
        """Handle the delete action from the service."""
        entity_id = call.data.get("entity_id")
        if not entity_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_entity_id"
            )
            
        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
        
        if not entry:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="entity_not_found",
                translation_placeholders={"entity_id": entity_id}
            )
            
        if "_timer_" not in entry.unique_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_a_timer"
            )
            
        timer_id = entry.unique_id.split("_timer_")[-1]
        blind_id = entry.unique_id.split("_timer_")[0]
        
        for hub_instance in hass.data[DOMAIN].values():
            if hasattr(hub_instance, "blinds"):
                for blind in hub_instance.blinds:
                    if blind.blind_id == blind_id:
                        await blind.async_delete_timer(timer_id)
                        return
                        
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="blind_not_found"
        )

    if not hass.services.has_service(DOMAIN, "delete_blind_timer"):
        hass.services.async_register(
            DOMAIN,
            "delete_blind_timer",
            async_action_delete_blind_timer,
            schema=vol.Schema({vol.Required("entity_id"): cv.entity_id}),
        )

class TuissTimerSensor(SensorEntity):
    """Representation of a Tuiss Timer."""
    
    _attr_icon = "mdi:timer-outline"
    _attr_has_entity_name = True
    _attr_should_poll = False
    
    def __init__(self, blind: TuissBlind, timer_id: str) -> None:
        """Initialize the sensor."""
        self._blind = blind
        self._timer_id = timer_id
        self._attr_unique_id = f"{blind.blind_id}_timer_{timer_id}"
        
        timer = self._blind.timers.get(self._timer_id)
        try:
            if timer and "ha_index" in timer:
                timer_index = timer["ha_index"]
            else:
                timer_index = int(timer_id) - 9
        except ValueError:
            timer_index = timer_id
            
        prefix = f"Timer {timer_index} - "
        
        if timer:
            day_map = {"mon": "Mo", "tue": "Tu", "wed": "We", "thu": "Th", "fri": "Fr", "sat": "Sa", "sun": "Su"}
            timer_days = timer.get("days", [])
            days_str = "".join(day_map.get(d, "") for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] if d in timer_days)
            
            raw_time = str(timer.get("time", "Unknown"))
            display_time = ":".join(raw_time.split(":")[:2]) if ":" in raw_time else raw_time
            
            pos = float(timer.get("position", 0))
            display_pos = f"{int(pos)}" if pos.is_integer() else f"{pos}"
            
            self._attr_name = f"{prefix}{display_time} - {display_pos}% - {days_str}"
            self._attr_native_value = display_time
            self._attr_extra_state_attributes = {
                "days": timer_days,
                "position": timer.get("position"),
                "timer_id": self._timer_id
            }
        else:
            self._attr_name = f"{prefix}Unknown"
            self._attr_native_value = "Unknown"
            self._attr_extra_state_attributes = {}
            
        _LOGGER.debug("Initialized TuissTimerSensor %s with name: %s", self._attr_unique_id, self._attr_name)

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._blind.blind_id)},
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        _LOGGER.debug("TuissTimerSensor added to HA: %s (Entity ID: %s)", self._attr_name, self.entity_id)
        
        @callback
        def handle_delete() -> None:
            """Remove the entity from HA."""
            _LOGGER.debug("Delete event received for timer sensor: %s", self.entity_id)
            self.hass.async_create_task(self._async_remove_self())
            
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_delete_timer_{self._blind.blind_id}_{self._timer_id}",
                handle_delete
            )
        )

    async def _async_remove_self(self) -> None:
        """Remove this entity from the entity registry and state machine."""
        _LOGGER.debug("Starting removal of timer sensor: %s", self.entity_id)
        if self.registry_entry:
            registry = er.async_get(self.hass)
            registry.async_remove(self.entity_id)
        else:
            await self.async_remove(force_remove=True)



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