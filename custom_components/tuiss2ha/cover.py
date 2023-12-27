"""Platform for cover integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_CURRENT_POSITION,
    CoverEntityFeature,
    CoverDeviceClass,
    CoverEntity,
)

from homeassistant.const import (
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_OPENING,
    STATE_CLOSING
)


from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(Tuiss(blind) for blind in hub.blinds)


class Tuiss(CoverEntity):
    """Create Cover Class."""

    def __init__(self, blind) -> None:
        """Initialize the cover."""
        self._blind = blind
        self._attr_unique_id = f"{self._blind._id}_cover"
        self._attr_name = self._blind.name
        self._state = None
        self._current_cover_position = 0
        self._moving = 0


    @property
    def state(self):
        """Set state of object."""
        if self._moving > 0:
            self._state = STATE_OPENING
        elif self._moving < 0:
            self._state = STATE_CLOSING
        elif self._current_cover_position == 100:
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
        if self._current_cover_position is None:
            return None
        return self._current_cover_position


    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        if self._current_cover_position is None:
            return None
        return self._current_cover_position == 0


    @property
    def supported_features(self):
        """Set features of object."""
        return (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
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
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._blind.remove_callback(self.async_write_ha_state)


    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            # if 0  < self._current_cover_position:
            #     self._moving = -50
            # else:
            #     self._moving = 0
            #self.schedule_update_ha_state()
            await self._blind.set_position(0)
            self._current_cover_position = 100
            self.schedule_update_ha_state()


    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            # if 100  > self._current_cover_position:
            #     self._moving = 50
            # else:
            #     self._moving = 0
            #self.schedule_update_ha_state()
            await self._blind.set_position(100)
            self._current_cover_position = 0
            #self._moving = 0
            self.schedule_update_ha_state()



    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            # if  kwargs[ATTR_POSITION] < self._current_cover_position:
            #     self._moving = -50
            # elif kwargs[ATTR_POSITION] > self._current_cover_position:
            #     self._moving = 50
            # else:
            #     self._moving = 0
            # self.schedule_update_ha_state()
            await self._blind.set_position(100 - kwargs[ATTR_POSITION])
            #self._moving = 0
            self._current_cover_position = kwargs[ATTR_POSITION]
            self.schedule_update_ha_state()
