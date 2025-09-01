"""Platform for cover integration."""

from __future__ import annotations

import asyncio
import logging
import voluptuous as vol
import datetime
from contextlib import asynccontextmanager

from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPEN, STATE_OPENING, STATE_CLOSING
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_platform, config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.exceptions import HomeAssistantError


from .const import DOMAIN, OPT_RESTART_ATTEMPTS, OPT_RESTART_POSITION, BLIND_SPEED_LIST, OPT_BLIND_SPEED, SPEED_CONTROL_SUPPORTED_MODELS, ConnectionTimeout, DeviceNotFound
from .hub import TuissBlind

_LOGGER = logging.getLogger(__name__)


ATTR_TRAVERSAL_TIME = "traversal_time"
ATTR_MAC_ADDRESS = "mac_address"

GET_BLIND_POSITION_SCHEMA = cv.make_entity_service_schema({})
SET_BLIND_POSITION_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100))}
)
SET_BLIND_SPEED_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("speed"): vol.In(BLIND_SPEED_LIST)}
)
SIMULTANEOUS_BLIND_POSITIONING_SCHEMA = vol.Schema(
    {
        vol.Required("entity_ids"): cv.entity_ids,
        vol.Required("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    blinds = [Tuiss(blind, config_entry) for blind in hub.blinds]
    async_add_entities(blinds)

    # Store entities in hass.data[DOMAIN] for easy retrieval by entity_id
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if "entities" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"] = {}
    for blind_entity in blinds:
        hass.data[DOMAIN]["entities"][blind_entity.entity_id] = blind_entity

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "get_blind_position", GET_BLIND_POSITION_SCHEMA, async_action_get_blind_position
    )

    platform.async_register_entity_service(
        "set_blind_position",
        SET_BLIND_POSITION_SCHEMA,
        async_action_set_blind_position,
    )
    
    # Register the set_speed service only for supported models
    for blind_entity in blinds:
        if blind_entity._blind.model in SPEED_CONTROL_SUPPORTED_MODELS:
            _LOGGER.debug("Adding blind speed service for %s, model %s",blind_entity._blind.name, blind_entity._blind.model)
            platform.async_register_entity_service(
                "set_blind_speed", SET_BLIND_SPEED_SCHEMA, async_action_set_blind_speed
            )

    # Register the new parallel blind position service as a domain service
    async def async_action_simultaneous_blind_positioning(service_call: ServiceCall) -> None:
        """Set the position of multiple blinds simultaneously."""
        hass = service_call.hass
        entity_ids = service_call.data["entity_ids"]
        position = service_call.data["position"]

        entities = []
        for entity_id in entity_ids:
            entity = hass.data[DOMAIN]["entities"].get(entity_id)
            if entity:
                entities.append(entity)
            else:
                _LOGGER.warning(
                    "Entity %s not found for parallel blind position setting.", entity_id
                )

        if not entities:
            _LOGGER.error("No valid entities found for parallel blind position setting.")
            return

        # Connect to all blinds in parallel
        connect_tasks = [entity._blind.attempt_connection() for entity in entities]
        await asyncio.gather(*connect_tasks)

        # Set position for all blinds in parallel
        set_position_tasks = [
            entity.async_set_cover_position(position=position) for entity in entities
        ]
        await asyncio.gather(*set_position_tasks)

    hass.services.async_register(
        DOMAIN,
        "simultaneous_blind_positioning",
        async_action_simultaneous_blind_positioning,
        schema=SIMULTANEOUS_BLIND_POSITIONING_SCHEMA,
    )


async def async_action_get_blind_position(entity, service_call):
    """Get the blind position when called by service."""
    await entity._blind.get_blind_position()
    entity.schedule_update_ha_state()


async def async_action_set_blind_position(entity, service_call):
    """Set the blind position with decimal precision."""
    position = service_call.data["position"]
    await entity.async_set_cover_position(**{ATTR_POSITION: position})


async def async_action_set_blind_speed(entity, service_call):
    """Set the blind speed."""
    speed = service_call.data["speed"]
    entity._blind._blind_speed = speed
    await entity._blind.set_speed()

    # Update the config entry with the new speed
    new_data = entity.config_entry.data.copy()
    new_options = entity.config_entry.options.copy()
    new_options[OPT_BLIND_SPEED] = speed
    entity.hass.config_entries.async_update_entry(
        entity.config_entry, data=new_data, options=new_options
    )


class Tuiss(CoverEntity, RestoreEntity):
    """Create Cover Class."""

    def __init__(self, blind: TuissBlind, config: ConfigEntry) -> None:
        """Initialize the cover."""
        self._blind = blind
        self.config_entry = config
        self._attr_unique_id = f"{self._blind.blind_id}_cover"
        self._attr_name = self._blind.name
        self._state = None
        self._start_time: datetime.datetime | None = None
        self._end_time: datetime.datetime | None = None
        self._attr_traversal_time: float | None = None
        self._attr_mac_address = self._blind.host
        self._blind._restart_attempts = config.options.get(OPT_RESTART_ATTEMPTS)
        self._blind._position_on_restart = config.options.get(OPT_RESTART_POSITION)

    @property
    def state(self):
        """Set state of object."""
        # corrects the state if there is a disconnect during open or close
        _LOGGER.debug(
            "%s: Setting State from %s. Moving: %s. Client: %s",
            self._attr_name,
            self._state,
            self._blind._moving,
            self._blind._client,
        )
        if self._blind._moving > 0:
            self._state = STATE_OPENING
        elif self._blind._moving < 0:
            self._state = STATE_CLOSING
        elif self._blind._moving == 0 and self._blind._current_cover_position >= 25:
            self._state = STATE_OPEN
        else:
            self._state = STATE_CLOSED
        return self._state
        
    @property
    def should_poll(self):
        """Set poll of object."""
        return False

    @property
    def device_class(self):
        """Set class of object."""
        return CoverDeviceClass.SHADE

    @property
    def available(self) -> bool:
        """Return True if blind and hub is available."""
        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._blind.blind_id)},
            name=self.name,
            model=self._blind.model,
            manufacturer=self._blind.hub.manufacturer,
            connections={(CONNECTION_NETWORK_MAC, self._blind.host)},
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributes for the traversal time of the blinds."""
        return {
            ATTR_TRAVERSAL_TIME: self._blind._attr_traversal_time,
            ATTR_MAC_ADDRESS: self._attr_mac_address,
        }

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        if self._blind._current_cover_position is None:
            return None
        return int(self._blind._current_cover_position)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        if self._blind._current_cover_position is None:
            return None
        return self._blind._current_cover_position == 0

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Set features of object."""
        return (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.STOP
        )


    async def async_scheduled_update_request(self, *_):
        """Request a state update from the blind at a scheduled point in time."""
        self.async_write_ha_state()

    async def async_update_state(self):
        """Update the state of the blind."""
        self.async_write_ha_state()


    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Restore the last known state
        last_state = await self.async_get_last_state()
        if not last_state or last_state.attributes.get(ATTR_CURRENT_POSITION) is None:
            self._blind._current_cover_position = 0
        else:
            self._blind._current_cover_position = float(
                last_state.attributes.get(ATTR_CURRENT_POSITION)
            )
        if last_state and last_state.attributes.get(ATTR_TRAVERSAL_TIME) is not None:
            self._blind._attr_traversal_time = last_state.attributes.get(ATTR_TRAVERSAL_TIME)
        
        self._blind.register_callback(self.async_update_state)


    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._blind.remove_callback(self.async_update_state)


    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        try:
            await self._blind.async_move_cover(movement_direction=1, target_position=0)
        except (ConnectionTimeout, DeviceNotFound) as e:
            _LOGGER.debug("%s failed to open with error %s.", self._attr_name, e)
            raise HomeAssistantError(f"{self._attr_name} failed to open with error {e}.")


    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        try:
            await self._blind.async_move_cover(movement_direction=-1, target_position=100)
        except (ConnectionTimeout, DeviceNotFound) as e:
            _LOGGER.debug("%s failed to close with error %s.", self._attr_name, e)
            raise HomeAssistantError(f"{self._attr_name} failed to close with error {e}.")


    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        if self._blind._current_cover_position is None:
            self._blind._current_cover_position = 0

        if self._blind._current_cover_position <= kwargs[ATTR_POSITION]:
            movement_direction = 1
        else:
            movement_direction = -1
        try:
            await self._blind.async_move_cover(
                movement_direction=movement_direction,
                target_position= 100 - kwargs[ATTR_POSITION],
            )
        except (ConnectionTimeout, DeviceNotFound) as e:
            _LOGGER.debug("%s failed to set position with error %s.", self._attr_name, e)
            raise HomeAssistantError(f"{self._attr_name} failed to set position with error {e}.")



    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("%s: Entering async_stop_cover. is_stopping: %s", self.name, self._blind._is_stopping)
        self._blind._is_stopping = True
        try:
            await self._blind.stop()
        except (ConnectionTimeout, DeviceNotFound, RuntimeError) as e:
            _LOGGER.debug("Failed to stop %s. Error %s", self._attr_name, e)
            raise HomeAssistantError("Failed to stop %s. Error %s", self._attr_name, e)
        if self._blind._client:
            while self._blind._client.is_connected:
                await asyncio.sleep(1)
            self._blind._moving = 0
            await self.async_scheduled_update_request()
        _LOGGER.debug("%s: Lock released in async_stop_cover.", self._attr_name)
        self._locked = False
