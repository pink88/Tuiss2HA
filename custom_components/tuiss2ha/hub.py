"""Tuiss Smartview and Blinds2go BLE Home."""

from __future__ import annotations

import asyncio
import logging
import datetime

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    BLIND_NOTIFY_CHARACTERISTIC,
    TRAVERSAL_UPDATE_THRESHOLD,
    UUID,
    CONNECTION_MESSAGE,
    INITIALIZATION_MESSAGE,
    DEFAULT_RESTART_ATTEMPTS,
    DeviceNotFound,
    ConnectionTimeout,
    NoConnectableBluetoothAdapter,
    TIMEOUT_SECONDS,
    CMD_STOP,
    CMD_BATTERY_STATUS,
    CMD_SPEED_STANDARD,
    CMD_SPEED_COMFORT,
    CMD_SPEED_SLOW,
)
from .limits import TuissLimitsMixin
from .presets import TuissPresetsMixin
from .protocol import (
    build_timestamp_command,
    create_timer_command,
    hex_convert,
    split_data,
)
from .timers import TuissTimersMixin

_LOGGER = logging.getLogger(__name__)


class Hub:
    """Tuiss BLE hub."""

    manufacturer = "Tuiss Smartview"

    def __init__(self, hass: HomeAssistant, host: str, name: str) -> None:
        """Init dummy hub."""
        self._host = host
        self._hass = hass
        self._name = name
        self._id = host
        self.blinds = [TuissBlind(self._host, self._name, self)]

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    @property
    def name(self) -> str:
        """Return the hub name."""
        return self._name


class TuissBlind(TuissLimitsMixin, TuissTimersMixin, TuissPresetsMixin):
    """Tuiss Blind object."""

    def __init__(self, host: str, name: str, hub: Hub) -> None:
        """Init tuiss blind."""
        self._id = host  # also the host address
        self.host = host
        self.name = name
        self.hub = hub
        self._ble_device = bluetooth.async_ble_device_from_address(
            self.hub._hass, self.host, connectable=True
        )
        if self._ble_device is None:
            self._ble_device = bluetooth.async_ble_device_from_address(
                self.hub._hass, self.host, connectable=False
            )
        self.model = self._ble_device.name if self._ble_device else None
        self._rssi: int | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._callbacks = set()
        self._battery_status = False
        self._moving = 0
        self._is_stopping = False
        self._stopped_event = asyncio.Event()
        self._read_response_event = asyncio.Event()
        self._current_cover_position: float | None = None
        self._desired_position: int | None = None
        self._desired_orientation = False
        self._restart_attempts: int | None = None
        self._position_on_restart: bool | None = None
        self._blind_speed: str | None = None
        self._locked = False
        self._attr_traversal_speed: float | None = None
        self._last_connection_error: str | None = None  # For logging when connection fails
        # Battery check configuration
        self._battery_check_days: int = 0
        self._last_battery_check: datetime.datetime | None = None
        # Tracks whether there is an active BLE notify subscription. Reset to False on
        # every new connection and every disconnect.
        self._notify_registered = False
        self._post_move_task: asyncio.Task | None = None
        self.timers = {}
        self._store = Store(self.hub._hass, 1, f"tuiss2ha_{self.host.replace(':', '').lower()}_schedules")
        self._limits_heartbeat_task: asyncio.Task | None = None
        # HA-side named position presets (separate from firmware timers).
        self.presets: dict[str, float] = {}
        self._presets_store = Store(
            self.hub._hass,
            1,
            f"tuiss2ha_{self.host.replace(':', '').lower()}_presets",
        )


    @property
    def blind_id(self) -> str:
        """Return ID for blind."""
        return self._id

    @property
    def rssi(self) -> int | None:
        """Return the rssi for the blind."""
        return self._rssi

    @property
    def current_position(self) -> float | None:
        """Return the last observed cover position (0-100), or None if unknown."""
        return self._current_cover_position

    def set_rssi(self, rssi: int) -> None:
        """Update the RSSI for the blind."""
        if self._rssi == rssi:
            return
        self._rssi = rssi
        self.publish_updates()

    def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            self.hub._hass.loop.call_soon(callback)

    def register_callback(self, callback) -> None:
        """Register callback, called when blind changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)


    ##################################################################################################
    ## CONNECTION METHODS ############################################################################
    ##################################################################################################

    # Attempt Connections
    async def attempt_connection(self):
        """Attempt to connect to the blind."""
        if self._client and self._client.is_connected:
            _LOGGER.debug("%s: Already connected.", self.name)
            return

        #Set restart attempts if not set in options
        rediscover_attempts = 0
        _LOGGER.debug("%s: Number of attempts: %s", self.name, self._restart_attempts)
        _LOGGER.debug("%s: Startup position check: %s",self.name, self._position_on_restart)
        if self._restart_attempts is None:
            self._restart_attempts = DEFAULT_RESTART_ATTEMPTS

        # check if the device not loaded at boot and retry a connection
        while self._ble_device is None and rediscover_attempts < self._restart_attempts:
            _LOGGER.debug("Unable to find device %s, attempting rediscovery", self.name)
            self._ble_device = bluetooth.async_ble_device_from_address(
                self.hub._hass, self.host, connectable=True
            )
            if self._ble_device is None:
                self._ble_device = bluetooth.async_ble_device_from_address(
                    self.hub._hass, self.host, connectable=False
                )
            rediscover_attempts += 1
            if self._ble_device is None and rediscover_attempts < self._restart_attempts:
                await asyncio.sleep(2)
        if self._ble_device is None:
            _LOGGER.error(
                "Cannot find the device %s. Check your bluetooth adapters and proxies",
                self.name,
            )
            raise DeviceNotFound(
                f"{self.name}: Cannot find the device. Check your bluetooth adapters and proxies"
            )

        retry_count = 1
        while retry_count <= self._restart_attempts:
            _LOGGER.debug(
                "%s %s: Attempting Connection to blind. Retry count: %d of %d",
                self.name,
                self._ble_device,
                retry_count,
                self._restart_attempts
            )
            await self.connect()

            # If the client is connected, return early
            if self._client and self._client.is_connected:
                # Read RSSI from the scanner here so the sensor stays current on every blind operation.
                service_info = bluetooth.async_last_service_info(
                    self.hub._hass, self.host, connectable=False
                )
                if service_info is not None:
                    self.set_rssi(service_info.rssi)
                return

            retry_count += 1
            if retry_count <= self._restart_attempts:
                await asyncio.sleep(2)

        last_err = self._last_connection_error or "unknown (no error captured)"
        _LOGGER.error(
            "%s: Connection failed after %d attempts. Last error: %s",
            self.name,
            self._restart_attempts,
            last_err,
        )
        if last_err and (
            "passive-only" in last_err.lower()
            or "no connectable bluetooth" in last_err.lower()
        ):
            raise NoConnectableBluetoothAdapter(
                "No connectable Bluetooth adapter. Shelly and similar devices are passive-only. "
                "You need an ESPHome Bluetooth proxy or a USB Bluetooth adapter to control Tuiss blinds."
            )
        raise ConnectionTimeout(f"{self.name}: Connection failed too many times [{self._restart_attempts}]")

    # Connect
    async def connect(self):
        """Connect to the blind."""
        assert self._ble_device is not None
        device = self._ble_device
        try:
            client: BleakClientWithServiceCache = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.host,
                use_services_cache=True,
                max_attempts=1,
                ble_device_callback=lambda: device,
            )
            self._client = client
            self._notify_registered = False  # fresh connection has no subscriptions
            
            # send the maintain connection message
            await self._client.write_gatt_char(UUID, bytes.fromhex(CONNECTION_MESSAGE))

            # send the connection timestamp message
            await self.send_timestamp()

            _LOGGER.debug(
                "%s: Connected. Current Position: %s. Current Moving: %s",
                self.name,
                self._current_cover_position,
                self._moving,
            )
        except (BleakError, asyncio.TimeoutError) as e:
            self._last_connection_error = f"{dt_util.now().strftime('%Y-%m-%d %H:%M:%S')}: {e}"
            _LOGGER.debug("Failed to connect to blind: %s", e)
        except Exception as e:
            self._last_connection_error = f"{dt_util.now().strftime('%Y-%m-%d %H:%M:%S')}: {type(e).__name__}: {e}"
            _LOGGER.debug("%s: Unexpected error during connect: %s", self.name, e)

    # Disconnect
    async def disconnect(self):
        """Disconnect from the blind."""

        if self._limits_heartbeat_task:
            self._limits_heartbeat_task.cancel()
            self._limits_heartbeat_task = None

        if self._locked:
            _LOGGER.debug("%s: Skipping BLE disconnect — move is in progress", self.name)
            return

        client = self._client
        if not client:
            _LOGGER.debug("%s: Already disconnected", self.name)
            self._stopped_event.set()
            self._read_response_event.set()
            return
        _LOGGER.debug("%s: Disconnecting", self.name)
        try:
            try:
                await client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            except Exception as notify_ex:
                _LOGGER.debug("%s: Could not stop notifications: %s", self.name, notify_ex)
            finally:
                self._notify_registered = False
            await client.disconnect()
        except BLEAK_RETRY_EXCEPTIONS as ex:
            _LOGGER.warning(
                "%s: Error disconnecting: %s",
                self.name,
                ex,
            )
        else:
            _LOGGER.debug("%s: Disconnect completed successfully", self.name)
            _LOGGER.debug(
                "%s: Disconnect. Current Position: %s. Current Moving: %s",
                self.name,
                self._current_cover_position,
                self._moving,
            )
        finally:
            self._stopped_event.set()
            self._read_response_event.set()

    async def wait_for_stop(self):
        """Wait for the blind to stop moving."""
        await self._stopped_event.wait()

    async def ensure_connected(self) -> None:
        """Ensure the blind is connected before sending a command."""
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

    async def _async_start_notify(self, callback) -> None:
        """Safely start notifications on the blind notify characteristic."""
        assert self._client is not None
        try:
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
            self._notify_registered = True
        except BleakError as e:
            _LOGGER.debug("%s: Failed to start notify: %s. Attempting restart.", self.name, e)
            try:
                await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            except Exception:
                pass
            self._notify_registered = False
            try:
                await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
                self._notify_registered = True
            except BleakError as retry_err:
                _LOGGER.warning("%s: Could not establish notifications: %s", self.name, retry_err)
                raise HomeAssistantError(
                    f"{self.name}: Could not establish BLE notifications — characteristic not found"
                ) from retry_err

    ##################################################################################################
    ## SET METHODS ###################################################################################
    ##################################################################################################
    async def set_position(self, userPercent) -> None:
        """Set the position of the blind converting from HA to Tuiss first."""
        await self.ensure_connected()

        assert self._client is not None
        self._desired_position = 100 - userPercent
        _LOGGER.debug(
            "%s: Attempting to set position to: %s", self.name, self._desired_position
        )
        command = bytes.fromhex(self.hex_convert(userPercent))
        await self._async_start_notify(self.set_position_callback)
        await self.send_command(UUID, command)

    async def stop(self) -> None:
        """Stop the blind at current position."""
        _LOGGER.debug("%s: Attempting to stop the blind.", self.name)
        # skip if the blind is not moving
        if self._moving == 0:
            return

        self._is_stopping = True
        try:
            # try to connect to blind if not connected, shouldnt really be necessary if the blind is already moving
            await self.ensure_connected()

            # send the stop command
            if self._client and self._client.is_connected:
                await self.send_command(UUID, bytes.fromhex(CMD_STOP))
        finally:
            self._moving = 0
            self._locked = False
            self._stopped_event.set()
            self._read_response_event.set()
            self.publish_updates()



    async def set_speed(self) -> None:
        """Set the speed for supported blind types"""
        _LOGGER.debug("%s: Attempting to set the blind speed", self.name)
        if self._locked:
            _LOGGER.debug("%s: Device is busy — cannot set blind speed", self.name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )

        match self._blind_speed:
            case "Standard":
                command = bytes.fromhex(CMD_SPEED_STANDARD)
            case "Comfort":
                command = bytes.fromhex(CMD_SPEED_COMFORT)
            case "Slow":
                command = bytes.fromhex(CMD_SPEED_SLOW)
            case _:
                # Defensive: caller should validate, but never let an unset
                # or unrecognised speed value raise UnboundLocalError below.
                _LOGGER.warning(
                    "%s: Cannot set speed — unrecognised value %r",
                    self.name,
                    self._blind_speed,
                )
                return

        self._locked = True
        self.publish_updates()

        try:
            await self.ensure_connected()

            # send the command
            if self._client and self._client.is_connected:
                await self.send_command(UUID, command)
        except (BleakError, RuntimeError) as e:
            _LOGGER.debug("%s: Unable to set the speed: %s", self.name, e)
            raise RuntimeError(
                "Unable to set the speed. Check has enough battery and within bluetooth range or that blind supports speed changes"
            ) from e
        finally:
            self._locked = False
            self.publish_updates()
            await self.disconnect()


    ##################################################################################################
    ## GET METHODS ###################################################################################
    ##################################################################################################

    async def get_from_blind(self, command, callback) -> None:
        """Send a command to the blind and await a notification response."""
        await self.ensure_connected()

        assert self._client is not None
        try:
            self._read_response_event.clear()
            await self._async_start_notify(callback)
            try:
                await self.send_command(UUID, command)
            except Exception as e:
                _LOGGER.error("%s: Error sending command during get_from_blind: %s", self.name, e)
                raise HomeAssistantError(f"{self.name}: BLE send failed — {e}") from e

            # Wait for the response/callback to complete with timeout to prevent hanging
            try:
                await asyncio.wait_for(self._read_response_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                _LOGGER.warning("%s: Timeout waiting for response in get_from_blind", self.name)
        finally:
            await self.disconnect()


    async def get_battery_status(self, from_move: bool = False) -> None:
        """Get the battery state from the blind as good or bad."""
        if not from_move:
            if self._locked:
                _LOGGER.debug("%s: Device is busy — cannot query battery", self.name)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_locked",
                    translation_placeholders={"name": self.name},
                )
            self._locked = True
            self.publish_updates()

        try:
            command = bytes.fromhex(CMD_BATTERY_STATUS)
            await self.get_from_blind(command, self.battery_callback)
        finally:
            if not from_move:
                self._locked = False
                self.publish_updates()
                await self.disconnect()


    async def get_blind_position(self) -> None:
        """Get the current position of the blind."""
        if self._locked:
            _LOGGER.debug("%s: Device is busy — cannot query position", self.name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )
        self._locked = True
        self.publish_updates()

        try:
            command = bytes.fromhex(INITIALIZATION_MESSAGE)
            await self.get_from_blind(command, self.position_callback)
        finally:
            self._locked = False
            self.publish_updates()
            await self.disconnect()

    ##################################################################################################
    ## CALLBACK METHODS ##############################################################################
    ##################################################################################################

    async def battery_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        decimals = self.split_data(data)
        _LOGGER.debug("%s: battery_callback raw decimals (len=%d): %s", self.name, len(decimals), decimals)
        matched = len(decimals) > 4 and decimals[4] == 210

        if matched:
            if len(decimals) < 6:
                _LOGGER.debug("%s: Battery response too short to read level — assuming low", self.name)
                self._battery_status = True
            elif decimals[5] >= 10:
                _LOGGER.debug("%s: Battery low (decimals[5]=%d >= 10)", self.name, decimals[5])
                self._battery_status = True
            else:
                _LOGGER.debug("%s: Battery good (decimals[5]=%d < 10)", self.name, decimals[5])
                self._battery_status = False
            # Record time of this battery check
            try:
                self._last_battery_check = dt_util.now()
            except Exception:
                self._last_battery_check = None
            
            self.publish_updates()
            self._read_response_event.set()
        else:
            _LOGGER.debug(
                "%s: battery_callback — decimals[4]=%s is not 210; skipping parse",
                self.name,
                decimals[4] if len(decimals) > 4 else "N/A",
            )

    async def position_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get position", self.name)

        decimals = self.split_data(data)

        if len(decimals) < 9:
            
            _LOGGER.debug(
                "%s: position_callback — packet too short (len=%d): %s — waiting for position packet",
                self.name, len(decimals), decimals,
            )
            return

        blindPos = (decimals[7] + (256 * decimals[8])) / 10
        _LOGGER.debug("%s: Blind position is %s", self.name, blindPos)
        self._current_cover_position = blindPos
        self.publish_updates()
        self._read_response_event.set()

    async def set_position_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ):
        """Handle response from the blind during movement. Keeps connection alive until target is reached."""
        decimals = self.split_data(data)
        _LOGGER.debug(
            "%s: Received response during movement: %s", self.name, decimals
        )
        if len(decimals) >= 9 and decimals[4] == 210:
            blindPos = decimals[6]
            self._current_cover_position = blindPos
            self.publish_updates()

            if self._desired_position is not None and abs(blindPos - self._desired_position) <= 2:
                _LOGGER.debug("%s: Reached desired position. Stopping wait.", self.name)
                self._stopped_event.set()

    ##################################################################################################
    ## DATA METHODS ############################################################################
    ##################################################################################################

    # Send the data
    async def send_command(self, UUID, command):
        """Send the command to the blind."""
        if self._client and self._client.is_connected:
            _LOGGER.debug(
                "%s (%s) connected state is %s",
                self.name,
                self._ble_device,
                self._client.is_connected,
            )
            try:
                _LOGGER.debug("%s: Sending the command %s", self.name, command.hex())
                await self._client.write_gatt_char(UUID, command)
            except BleakError as e:
                _LOGGER.error("%s: Send Command error: %s", self.name, e)
                raise RuntimeError(e) from e

    async def send_timestamp(self) -> None:
        """Send the current timestamp command to the blind."""
        await self.send_command(UUID, build_timestamp_command(dt_util.now()))

    def hex_convert(self, user_percent: float) -> str:
        """Convert the Home Assistant position percentage (0-100) to the Tuiss hex command."""
        return hex_convert(user_percent)

    def split_data(self, data: bytearray) -> list[int]:
        """Convert the byte response into a list of decimals."""
        return split_data(data)


    async def _cancel_post_move_task(self) -> None:
        """Cancel any pending post-move position queries."""
        if self._post_move_task and not self._post_move_task.done():
            self._post_move_task.cancel()
            try:
                await self._post_move_task
            except asyncio.CancelledError:
                pass
            self._post_move_task = None

    def _schedule_post_move_query(self, delay: float = 5.0) -> None:
        """Schedule a background position query after movement."""
        async def _query():
            try:
                await asyncio.sleep(delay)
                try:
                    await self.get_blind_position()
                except Exception as e:
                    _LOGGER.debug("%s: Post-move position query failed: %s", self.name, e)
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Post-move queries cancelled — new command received", self.name)

        try:
            self._post_move_task = self.hub._hass.async_create_task(_query())
        except Exception as e:
            _LOGGER.debug("%s: Failed to schedule post-move query: %s", self.name, e)

    async def _async_check_battery_if_due(self) -> None:
        """Perform a battery check before moving if configured interval has elapsed."""
        _LOGGER.debug(
            "%s: Battery check age (%s days). Last check: %s.",
            self.name,
            self._battery_check_days,
            self._last_battery_check,
        )
        try:
            if self._battery_check_days and (
                self._last_battery_check is None
                or (
                    (dt_util.now() - self._last_battery_check).total_seconds()
                    / 86400
                )
                > float(self._battery_check_days)
            ):
                _LOGGER.debug(
                    "%s: Battery check age exceeded (%s days). Checking battery.",
                    self.name,
                    self._battery_check_days,
                )
                try:
                    await self.get_battery_status(from_move=True)
                except Exception as e:
                    _LOGGER.debug("%s: Battery check failed: %s", self.name, e)
        except Exception:
            _LOGGER.debug("%s: Error while evaluating battery check timing", self.name)

    async def _async_dead_reckoning_loop(
        self,
        start_position: float,
        target_position: float,
        movement_direction: int,
        start_time: datetime.datetime,
    ) -> None:
        """Task to update the position in real time while the blind is moving."""
        while self._client and self._client.is_connected and not self._is_stopping:
            if self._attr_traversal_speed is not None:
                elapsed = (dt_util.now() - start_time).total_seconds()
                traversal_difference = elapsed * self._attr_traversal_speed * movement_direction
                raw_pos = start_position + traversal_difference
                min_pos = min(start_position, target_position)
                max_pos = max(start_position, target_position)
                self._current_cover_position = round(min(max_pos, max(min_pos, raw_pos)), 2)
                _LOGGER.debug(
                    "%s: StartPos: %s. CurrentPos: %s. TargetPos: %s. Timedelta: %s",
                    self.name,
                    start_position,
                    self._current_cover_position,
                    target_position,
                    elapsed,
                )
                self.publish_updates()
            await asyncio.sleep(1)

    async def async_move_cover(
        self,
        movement_direction,
        target_position,
        skip_battery_check=False
    ):
        """Move the cover."""
        _LOGGER.debug("%s: Entering async_move_cover. Locked: %s", self.name, self._locked)
        if self._locked:
            _LOGGER.debug(
                "%s is locked, please wait for currrent command to complete and then try again.",
                self.name,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={"name": self.name},
            )

        # Acquire lock and set moving state immediately before any awaitable call.
        # This provides instant UI feedback and locks out duplicate or stacked commands.
        self._locked = True
        _LOGGER.debug("%s: Lock acquired.", self.name)
        self._is_stopping = False
        self._moving = movement_direction
        if self._current_cover_position is None:
            self._current_cover_position = 0.0
        start_position = self._current_cover_position
        corrected_target_position = 100 - target_position
        self.publish_updates()

        try:
            # Cancel any background position task from previous move
            await self._cancel_post_move_task()

            await self.attempt_connection()
            if not (self._client and self._client.is_connected):
                self._moving = 0
                self._locked = False
                self.publish_updates()
                return

            if self._is_stopping or not self._locked:
                _LOGGER.debug(
                    "%s: Movement aborted before start (is_stopping=%s, locked=%s)",
                    self.name,
                    self._is_stopping,
                    self._locked,
                )
                self._is_stopping = False
                self._moving = 0
                self._locked = False
                self.publish_updates()
                await self.disconnect()
                return

            if not skip_battery_check:
                await self._async_check_battery_if_due()

            if self._is_stopping or not self._locked:
                _LOGGER.debug(
                    "%s: Movement aborted before start (is_stopping=%s, locked=%s)",
                    self.name,
                    self._is_stopping,
                    self._locked,
                )
                self._is_stopping = False
                self._moving = 0
                self._locked = False
                self.publish_updates()
                await self.disconnect()
                return
        except Exception:
            self._moving = 0
            self._locked = False
            self.publish_updates()
            await self.disconnect()
            raise

        self._stopped_event.clear()
        move_sent = False
        for attempt in range(2):
            try:
                await asyncio.wait_for(self.set_position(target_position), timeout=30.0)
                move_sent = True
                break
            except asyncio.TimeoutError:
                _LOGGER.error("%s: set_position() timed out after 30s. Unsticking blind.", self.name)
                break
            except Exception as e:
                if attempt == 0 and "NotConnected" in str(e):
                    _LOGGER.warning(
                        "%s: Move command got NotConnected — reconnecting and retrying.",
                        self.name,
                    )
                    await self.disconnect()
                    continue
                _LOGGER.error("%s: Failed to send move command: %s. Unsticking blind.", self.name, e)
                break

        if not move_sent:
            self._moving = 0
            self._locked = False
            self.publish_updates()
            await self.disconnect()
            return

        start_time = dt_util.now()
        update_task = self.hub._hass.async_create_task(
            self._async_dead_reckoning_loop(
                start_position, corrected_target_position, movement_direction, start_time
            )
        )

        try:
            if (
                self._attr_traversal_speed is not None
                and 1 <= self._attr_traversal_speed < 6
            ):
                timeout_duration = (
                    (abs(corrected_target_position - start_position) * 1.2)
                    / self._attr_traversal_speed
                ) + 10
            else:
                timeout_duration = TIMEOUT_SECONDS or 120

            _LOGGER.debug(
                "%s: Waiting for stop event with timeout: %s seconds. Traversal speed: %s",
                self.name,
                timeout_duration,
                self._attr_traversal_speed,
            )
            await asyncio.wait_for(self.wait_for_stop(), timeout=timeout_duration)
        except asyncio.TimeoutError:
            _LOGGER.warning("%s: Timeout waiting for blind to stop", self.name)
            self.set_final_state(corrected_target_position)
            self._schedule_post_move_query(delay=3)
            return
        finally:
            update_task.cancel()
            self._locked = False
            await self.disconnect()
            _LOGGER.debug("%s: Lock released in async_move_cover.", self.name)

        _LOGGER.debug(
            "%s: Finished moving. StartPos: %s. CurrentPos: %s. TargetPos: %s. is_stopping: %s",
            self.name,
            start_position,
            self._current_cover_position,
            corrected_target_position,
            self._is_stopping,
        )
        if not self._is_stopping:
            end_time = dt_util.now()
            self.update_traversal_speed(
                corrected_target_position, start_position, start_time, end_time
            )
            self._moving = 0
            self.publish_updates()
        else:
            self._is_stopping = False
            self._schedule_post_move_query(delay=2)

    def update_traversal_speed(self, target_position, start_position, start_time, end_time):
        """Update the traversal speed."""
        time_taken = (end_time - start_time).total_seconds()
        traversal_distance = abs(target_position - start_position)
        # Only update traversal speed if the blind has moved a significant distance to avoid skewing from small movements or noise
        if traversal_distance > TRAVERSAL_UPDATE_THRESHOLD:
            self._attr_traversal_speed = traversal_distance / time_taken
            _LOGGER.debug(
                "%s: Time Taken: %s. Start Pos: %s. End Pos: %s. Distance Travelled: %s. Traversal Speed: %s",
                self.name,
                time_taken,
                start_position,
                target_position,
                traversal_distance,
                self._attr_traversal_speed,
            )

    def set_final_state(self, position):
        """Set the final state of the blind after a move."""
        self._current_cover_position = position
        self._moving = 0
        self.publish_updates()
