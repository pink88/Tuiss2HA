"""Platform for cover integration."""

from __future__ import annotations

import asyncio
import logging
import voluptuous as vol
import datetime

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
from homeassistant.helpers import entity_platform, config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo


from .const import DOMAIN, OPT_BLIND_ORIENTATION, OPT_RESTART_ATTEMPTS, OPT_RESTART_POSITION
from .hub import TuissBlind

_LOGGER = logging.getLogger(__name__)


ATTR_TRAVERSAL_TIME = "traversal_time"
ATTR_MAC_ADDRESS = "mac_address"

GET_BLIND_POSITION_SCHEMA = cv.make_entity_service_schema({})
SET_BLIND_POSITION_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100))}
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(Tuiss(blind, config_entry) for blind in hub.blinds)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "get_blind_position", GET_BLIND_POSITION_SCHEMA, async_get_blind_position
    )

    platform.async_register_entity_service(
        "set_blind_position",
        SET_BLIND_POSITION_SCHEMA,
        async_set_blind_position,
    )


async def async_get_blind_position(entity, service_call):
    """Get the blind position when called by service."""
    await entity._blind.get_blind_position()
    entity.schedule_update_ha_state()


async def async_set_blind_position(entity, service_call):
    """Set the blind position with decimal precision."""
    position = service_call.data["position"]
    await entity._blind.set_position(100 - position)
    if (
        entity._blind_orientation
    ):  # wokraround for some blinds working opposite for this service only?
        entity._blind._current_cover_position = 100 - position
    else:
        entity._blind._current_cover_position = position
    entity.schedule_update_ha_state()


class Tuiss(CoverEntity, RestoreEntity):
    """Create Cover Class."""

    def __init__(self, blind: TuissBlind, config: ConfigEntry) -> None:
        """Initialize the cover."""
        self._blind = blind
        self._attr_unique_id = f"{self._blind.blind_id}_cover"
        self._attr_name = self._blind.name
        self._state = None
        self._startTime: datetime.datetime | None = None
        self._endTime: datetime.datetime | None = None
        self._attr_traversal_time: float | None = None
        self._attr_mac_address = self._blind.host
        self._locked = False
        self._blind_orientation = config.options.get(OPT_BLIND_ORIENTATION, False)
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
            ATTR_TRAVERSAL_TIME: self._attr_traversal_time,
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
            self._attr_traversal_time = last_state.attributes.get(ATTR_TRAVERSAL_TIME)
        
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._blind.remove_callback(self.async_write_ha_state)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.async_move_cover(1, 0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.async_move_cover(-1, 100)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        if self._blind._current_cover_position is None:
            self._blind._current_cover_position = 0

        if self._blind._current_cover_position <= kwargs[ATTR_POSITION]:
            movVal = 1
        else:
            movVal = -1
        await self.async_move_cover(movVal, 100 - kwargs[ATTR_POSITION])

    async def async_move_cover(self, movVal, targetPos):
        await self._blind.attempt_connection()
        if self._blind._client.is_connected and self._locked == False:
            self._locked = True
            self._blind._is_stopping = False
            startPos = self._blind._current_cover_position
            self._blind._moving = movVal

            # Update the state and trigger the moving
            await self.async_scheduled_update_request()
            await self._blind.set_position(targetPos)
            self._endTime = None
            self._startTime = datetime.datetime.now()

            while self._blind._client.is_connected:
                # Update the position in realtime based on average traversal time
                if self._attr_traversal_time is not None:
                    _LOGGER.debug("StartPos: %s. CurrentPos: %s. Timedelta: %s",
                        startPos,self._blind._current_cover_position,
                        (datetime.datetime.now() - self._startTime).total_seconds(),
                    )
                    traversalDelta = (
                        (datetime.datetime.now() - self._startTime).total_seconds()
                        * self._attr_traversal_time
                        * movVal
                    )
                    self._blind._current_cover_position = round(sorted(
                        [startPos, startPos + traversalDelta, 100 - targetPos]
                    )[1],2)
                    await self.async_scheduled_update_request()
                await asyncio.sleep(1)

            # set the traversal time average and update final states only if the blind has not been stopped, as that updates itself
            _LOGGER.debug("%s: Finished moving. StartPos: %s. CurrentPos: %s. TargetPos: %s. is_stopping: %s", self._attr_name, startPos, self._blind._current_cover_position, targetPos, self._blind._is_stopping)
            if not self._blind._is_stopping:
                self._endTime = datetime.datetime.now()
                await self.update_traversal_time(100 - targetPos, startPos)

                self._blind._current_cover_position = 100 - targetPos
                self._blind._moving = 0
                await self.async_scheduled_update_request()

            # unlock the entity to allow more changes
            self._locked = False

    async def update_traversal_time(self, targetPos, startPos):
        timeTaken = (self._endTime - self._startTime).total_seconds()
        traversalDistance = abs(targetPos - startPos)
        self._attr_traversal_time = traversalDistance / timeTaken
        _LOGGER.debug(
            "%s: Time Taken: %s. Start Pos: %s. End Pos: %s. Distance Travelled: %s. Traversal Time: %s",
            self._attr_name,
            timeTaken,
            startPos,
            targetPos,
            traversalDistance,
            self._attr_traversal_time,
        )
        await self.async_scheduled_update_request()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        self._blind._is_stopping = True
        await self._blind.stop()
        if self._blind._client:
            while self._blind._client.is_connected:
                await asyncio.sleep(1)
            self._blind._moving = 0
            await self.async_scheduled_update_request()
        self._locked = False
