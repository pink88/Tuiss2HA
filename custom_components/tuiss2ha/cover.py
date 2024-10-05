"""Platform for cover integration."""
from __future__ import annotations

import asyncio
import logging

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
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(Tuiss(blind) for blind in hub.blinds)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "get_blind_position", {}, async_get_blind_position
    )


async def async_get_blind_position(entity, service_call):
    """Get the battery status when called by service."""
    await entity._blind.get_blind_position()
    entity.schedule_update_ha_state()


class Tuiss(CoverEntity, RestoreEntity):
    """Create Cover Class."""

    def __init__(self, blind) -> None:
        """Initialize the cover."""
        self._blind = blind
        self._attr_unique_id = f"{self._blind._id}_cover"
        self._attr_name = self._blind.name
        self._state = None
        

    @property
    def state(self):
        """Set state of object."""
        #corrects the state if there is a disconnect during open or close
        _LOGGER.debug("%s: Setting State from %s. Moving: %s. Client: %s", self._attr_name, self._state, self._blind._moving, self._blind._client)
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
    def current_cover_position(self):
        """Return the current position of the cover."""
        if self._blind._current_cover_position is None:
            return None
        return self._blind._current_cover_position

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        if self._blind._current_cover_position is None:
            return None
        return self._blind._current_cover_position == 0

    @property
    def supported_features(self):
        """Set features of object."""
        return (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.STOP
        )

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._blind._id)},
            # If desired, the name for the device could be different to the entity
            "name": self.name,
            "model": self._blind.model,
            "manufacturer": self._blind.hub.manufacturer,
        }

    async def async_scheduled_update_request(self, *_):
        """Request a state update from the blind at a scheduled point in time."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        last_state = await self.async_get_last_state()
        if not last_state or ATTR_CURRENT_POSITION not in last_state.attributes:
            self._blind._current_cover_position = 0
        else:
            self._blind._current_cover_position = last_state.attributes.get(
                ATTR_CURRENT_POSITION
            )
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._blind.remove_callback(self.async_write_ha_state)


    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.async_move_cover(1,0)


    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.async_move_cover(-1,100)


    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        if (self._blind._current_cover_position <= kwargs[ATTR_POSITION]):
            movVal = 1
        else:  
            movVal = -1
        await self.async_move_cover(movVal,100 - kwargs[ATTR_POSITION])


    async def async_move_cover(self, movVal, targetPos):
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            self._blind._moving = movVal
            await self.async_scheduled_update_request()
            await self._blind.set_position(targetPos)
            while self._blind._client.is_connected:
                await self._blind.check_connection()
                await asyncio.sleep(1)
            self._blind._current_cover_position = 100 - targetPos
            self._blind._moving = 0
            await self.async_scheduled_update_request()



    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._blind.stop()
        if self._blind._client:
            while self._blind._client.is_connected:
                await asyncio.sleep(1)
            self._blind._moving = 0
            await self.async_scheduled_update_request()