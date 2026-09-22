"""Hardware timers mixin for Tuiss Smartview BLE blinds."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.exceptions import HomeAssistantError

from . import hub

from .const import (
    DOMAIN,
    UUID,
    BLIND_NOTIFY_CHARACTERISTIC,
    CONNECTION_MESSAGE,
    INITIALIZATION_MESSAGE,
    CMD_BATTERY_STATUS,
    CMD_TIMER_REQUEST,
    CMD_TIMER_DELETE_BASE,
    CMD_TIMER_RESET,
    CMD_BLIND_REACTIVATE,
)
from .protocol import create_timer_command, split_data

_LOGGER = logging.getLogger(__name__)


class TuissTimersMixin:
    """Mixin providing on-blind firmware timer scheduling and management."""

    def create_timer_command(
        self, index: str, days: list[str], time: str, position: float
    ) -> str:
        """Create the hex command to program a timer slot (delegated to protocol)."""
        return create_timer_command(index, days, time, position)

    async def async_load_timers(self) -> None:
        """Load stored schedules."""
        stored = await self._store.async_load()
        if stored:
            self.timers = stored
        else:
            self.timers = {}

    async def async_save_timer(self) -> None:
        """Save schedules to storage."""
        await self._store.async_save(self.timers)

    async def async_add_timer(
        self, days: list[str], time_str: str, position: float
    ) -> str:
        """Add a new schedule to the blind firmware."""
        if self._locked:
            _LOGGER.debug("%s: Device is busy — cannot add timer", self.name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )
        self._locked = True
        self.publish_updates()

        try:
            await self.ensure_connected()

            new_timer_id = None
            timer_id_event = asyncio.Event()

            async def timer_id_callback(sender, data):
                nonlocal new_timer_id
                decimals = split_data(data)
                # Filter for the correct response: 7 bytes long, where the 5th byte is 0xd6 (214)
                if len(decimals) >= 7 and decimals[4] == 214:
                    new_timer_id = str(decimals[6])
                    timer_id_event.set()

            await self._async_start_notify(timer_id_callback)

            await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
            await self.send_timestamp()
            await self.send_command(UUID, bytes.fromhex(CMD_TIMER_REQUEST))

            try:
                await asyncio.wait_for(timer_id_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
                raise HomeAssistantError("Timeout waiting for timer ID from blind.")

            await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)

            _LOGGER.debug("Received timer ID from blind: %s", new_timer_id)

            if not new_timer_id:
                _LOGGER.debug("Failed to obtain timer ID from the blind.")
                raise HomeAssistantError("Failed to obtain timer ID from the blind.")

            if int(new_timer_id) >= 17:
                _LOGGER.debug("Maximum number of timers reached.")
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="max_timers_reached",
                    translation_placeholders={"max_timers": "16"},
                )

            timer_id = new_timer_id
            timer_command = create_timer_command(timer_id, days, time_str, position)

            await self.send_command(UUID, bytes.fromhex(timer_command))
            await self.send_command(UUID, bytes.fromhex(CMD_BATTERY_STATUS))

            existing_ha_indices = {
                t.get("ha_index") for t in self.timers.values() if "ha_index" in t
            }
            available_indices = set(range(1, 17)) - existing_ha_indices
            ha_index = (
                min(available_indices) if available_indices else len(self.timers) + 1
            )

            self.timers[timer_id] = {
                "timer_id": timer_id,
                "ha_index": ha_index,
                "days": days,
                "time": time_str,
                "position": position,
            }

            await self.async_save_timer()
            hub.async_dispatcher_send(
                self.hub._hass, f"{DOMAIN}_add_timer_{self.blind_id}", timer_id
            )
            return timer_id
        finally:
            self._locked = False
            self.publish_updates()
            await self.disconnect()

    async def async_delete_timer(self, timer_id: str) -> None:
        """Remove an existing schedule from the blind firmware."""
        if self._locked:
            _LOGGER.debug("%s: Device is busy — cannot delete timer", self.name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )
        self._locked = True
        self.publish_updates()

        try:
            await self.ensure_connected()

            await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
            await self.send_timestamp()
            await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
            delete_hex = f"{CMD_TIMER_DELETE_BASE}{int(timer_id):02x}"
            await self.send_command(UUID, bytes.fromhex(delete_hex))
            await self.send_command(UUID, bytes.fromhex(CMD_BATTERY_STATUS))

            if timer_id in self.timers:
                del self.timers[timer_id]
                await self.async_save_timer()
                hub.async_dispatcher_send(
                    self.hub._hass,
                    f"{DOMAIN}_delete_timer_{self.blind_id}_{timer_id}",
                )
        finally:
            self._locked = False
            self.publish_updates()
            await self.disconnect()

    async def delete_all_timers(self) -> None:
        """Delete all schedules from the blind firmware."""
        _LOGGER.debug("%s: Attempting to delete all timers.", self.name)
        if self._locked:
            _LOGGER.debug("%s: Device is busy — cannot delete all timers", self.name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )
        self._locked = True
        self.publish_updates()

        try:
            await self.ensure_connected()

            await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
            await self.send_timestamp()
            await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
            await self.send_command(UUID, bytes.fromhex(CMD_TIMER_RESET))

            if self._client:
                await self._client.disconnect()
                self._client = None

            await self.attempt_connection()
            await self.send_command(UUID, bytes.fromhex(CMD_BLIND_REACTIVATE))

            if self.timers:
                timer_ids = list(self.timers.keys())
                for timer_id in timer_ids:
                    hub.async_dispatcher_send(
                        self.hub._hass,
                        f"{DOMAIN}_delete_timer_{self.blind_id}_{timer_id}",
                    )

                self.timers.clear()
                await self.async_save_timer()
        finally:
            self._locked = False
            self.publish_updates()
            await self.disconnect()
