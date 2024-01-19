"""Platform for cover integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN


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
        self._current_cover_position: None
        self._moving = 0

    @property
    def state(self):
        """Set state of object."""
        if self._current_cover_position >= 25:
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
        last_state = await self.async_get_last_state()
        if not last_state or ATTR_CURRENT_POSITION not in last_state.attributes:
            self._current_cover_position = 0
        else:
            self._current_cover_position = last_state.attributes.get(
                ATTR_CURRENT_POSITION
            )
        self._blind.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        self._blind.remove_callback(self.async_write_ha_state)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            await self._blind.set_position(0)
            self._current_cover_position = 100
            self.schedule_update_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            await self._blind.set_position(100)
            self._current_cover_position = 0
            self.schedule_update_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._blind.attempt_connection()
        if self._blind._client.is_connected:
            await self._blind.set_position(100 - kwargs[ATTR_POSITION])
            self._current_cover_position = kwargs[ATTR_POSITION]
            self.schedule_update_ha_state()
