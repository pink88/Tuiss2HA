"""Limits configuration mixin for Tuiss Smartview BLE blinds."""
from __future__ import annotations

import asyncio
import logging

from .const import (
    UUID,
    INITIALIZATION_MESSAGE,
    CMD_HEARTBEAT,
    CMD_STOP,
    CMD_LIMITS_INIT_2,
    CMD_LIMITS_STEP_UP,
    CMD_LIMITS_STEP_DOWN,
    CMD_LIMITS_MOVE_UP,
    CMD_LIMITS_MOVE_DOWN,
    CMD_LIMITS_SET,
)

_LOGGER = logging.getLogger(__name__)


class TuissLimitsMixin:
    """Mixin providing hardware limit calibration and motion heartbeat."""

    def limits_heartbeat_start(self, move_command: str) -> None:
        """Start the heartbeat task for limits."""
        self.limits_heartbeat_stop()
        self._limits_heartbeat_task = self.hub._hass.async_create_task(
            self.limits_heartbeat_loop(move_command)
        )

    def limits_heartbeat_stop(self) -> None:
        """Stop the heartbeat task for limits."""
        if self._limits_heartbeat_task:
            self._limits_heartbeat_task.cancel()
            self._limits_heartbeat_task = None

    async def limits_heartbeat_loop(self, move_command_str: str) -> None:
        """Send heartbeat every 4 seconds while moving."""
        heartbeat_command = bytes.fromhex(CMD_HEARTBEAT)
        move_command = bytes.fromhex(move_command_str)
        while True:
            try:
                await asyncio.sleep(2)
                if self._client and self._client.is_connected:
                    await self.send_command(UUID, heartbeat_command)
                    await self.send_command(UUID, move_command)
                else:
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.debug("%s: Moving heartbeat failed: %s", self.name, e)
                break

    async def limits_initialise(self) -> None:
        """Initialise the limit configuration by connecting to the blind."""
        self.limits_heartbeat_stop()
        _LOGGER.debug("Starting Limits Config. Attempting Connection")
        await self.ensure_connected()

        _LOGGER.debug("Sending initialisation commands")
        await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_INIT_2))

    async def _async_send_limit_command(
        self, command_hex: str, start_heartbeat: bool = False
    ) -> None:
        """Send a limit setup command and manage the motion heartbeat."""
        if not start_heartbeat:
            self.limits_heartbeat_stop()
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits command failed")
            return
        await self.send_command(UUID, bytes.fromhex(command_hex))
        if start_heartbeat:
            self.limits_heartbeat_start(command_hex)

    async def limits_step_up(self) -> None:
        """Move the blind up incrementally for manual positioning."""
        _LOGGER.debug("Stepping up")
        await self._async_send_limit_command(CMD_LIMITS_STEP_UP)

    async def limits_step_down(self) -> None:
        """Move the blind down incrementally for manual positioning."""
        _LOGGER.debug("Stepping down")
        await self._async_send_limit_command(CMD_LIMITS_STEP_DOWN)

    async def limits_move_up(self) -> None:
        """Move the blind up continuously for manual positioning."""
        _LOGGER.debug("Moving up")
        await self._async_send_limit_command(CMD_LIMITS_MOVE_UP, start_heartbeat=True)

    async def limits_move_down(self) -> None:
        """Move the blind down continuously for manual positioning."""
        _LOGGER.debug("Moving down")
        await self._async_send_limit_command(CMD_LIMITS_MOVE_DOWN, start_heartbeat=True)

    async def limits_stop(self) -> None:
        """Stop the blind movement."""
        _LOGGER.debug("Stopping movement")
        await self._async_send_limit_command(CMD_STOP)

    async def limits_set(self) -> None:
        """Sets the limit."""
        self.limits_heartbeat_stop()
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")
            return
        _LOGGER.debug("Setting the limit")
        await self.send_command(UUID, bytes.fromhex(CMD_STOP))
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_SET))
