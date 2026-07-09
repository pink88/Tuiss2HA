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
    CMD_HEARTBEAT,
    CMD_STOP,
    CMD_BATTERY_STATUS,
    CMD_SPEED_STANDARD,
    CMD_SPEED_COMFORT,
    CMD_SPEED_SLOW,
    CMD_LIMITS_INIT_2,
    CMD_LIMITS_STEP_UP,
    CMD_LIMITS_STEP_DOWN,
    CMD_LIMITS_MOVE_UP,
    CMD_LIMITS_MOVE_DOWN,
    CMD_LIMITS_SET,
    CMD_TIMER_REQUEST,
    CMD_TIMER_DELETE_BASE,
    CMD_TIMER_RESET,
    CMD_BLIND_REACTIVATE,
    CMD_TIMESTAMP_BASE,
)

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


class TuissBlind:
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
        # Serialises all BLE reads (position + battery). Prevents adapter slot exhaustion
        # when concurrent callers — dashboard polls, background tasks, HA services — all
        # try to connect simultaneously. Callers queue; they never pile onto the adapter.
        self._ble_lock = asyncio.Lock()
        # Tracks whether we have an active BLE notify subscription. Reset to False on
        # every new connection and every disconnect. Used to guard stop_notify calls so
        # we only attempt to stop a session we know is registered.
        self._notify_registered = False
        # Reference to the post-move background task so it can be cancelled when a new
        # movement command arrives before the T+5s / T+15s queries have fired.
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
                self._last_connection_error = None  # clear stale error so sensor state stays short
                # Passive BLE scan callback only fires once per integration reload — read RSSI
                # from the scanner here so the sensor stays current on every blind operation.
                service_info = bluetooth.async_last_service_info(
                    self.hub._hass, self.host, connectable=False
                )
                if service_info is not None:
                    self.set_rssi(service_info.rssi)
                return

            retry_count += 1
            if retry_count <= self._restart_attempts:
                await asyncio.sleep(2)

        # If we reach here, we have exceeded max retries - log the actual error at ERROR so it's visible
        last_err = self._last_connection_error or "unknown (no error captured)"
        _LOGGER.error(
            "%s: Connection failed after %d attempts. Last error: %s",
            self.name,
            self._restart_attempts,
            last_err,
        )
        # Give a clear error when user has only passive Bluetooth (e.g. Shelly)
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
                max_attempts=self._restart_attempts,
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
            self._last_connection_error = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {e}"
            _LOGGER.debug("Failed to connect to blind: %s", e)
        except Exception as e:
            self._last_connection_error = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {type(e).__name__}: {e}"
            _LOGGER.debug("%s: Unexpected error during connect: %s", self.name, e)

    # Disconnect
    async def disconnect(self):
        """Disconnect from the blind."""

        if self._limits_heartbeat_task:
            self._limits_heartbeat_task.cancel()
            self._limits_heartbeat_task = None

        # Don't disconnect while a move is in progress — the move owns the BLE connection.
        # The move releases _locked before calling disconnect itself (see async_move_cover).
        if self._locked:
            _LOGGER.debug("%s: Skipping BLE disconnect — move is in progress", self.name)
            return

        client = self._client
        if not client:
            _LOGGER.debug("%s: Already disconnected", self.name)
            self._stopped_event.set()
            return
        _LOGGER.debug("%s: Disconnecting", self.name)
        try:
            try:
                await client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            except Exception as notify_ex:
                # Characteristic might not exist or notifications not started
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

    async def wait_for_stop(self):
        """Wait for the blind to stop moving."""
        self._stopped_event.clear()
        await self._stopped_event.wait()

    async def ensure_connected(self) -> None:
        """Ensure the blind is connected before sending a command."""
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

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
        try:
            await self._client.start_notify(
                BLIND_NOTIFY_CHARACTERISTIC, self.set_position_callback
            )
            self._notify_registered = True
        except BleakError:
            if self._notify_registered:
                await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
                self._notify_registered = False
            await self._client.start_notify(
                BLIND_NOTIFY_CHARACTERISTIC, self.set_position_callback
            )
            self._notify_registered = True
        await self.send_command(UUID, command)  # send the command

    async def stop(self) -> None:
        """Stop the blind at current position."""
        _LOGGER.debug("%s: Attempting to stop the blind.", self.name)
        command = bytes.fromhex(CMD_STOP)

        # skip if the blind is not moving
        if self._moving == 0:
            return

        # try to connect to blind if not connected, shouldnt really be necessary if the blind is already moving
        await self.ensure_connected()

        # send the stop command
        if self._client and self._client.is_connected:
            await self.send_command(UUID, command)
        if self._client and self._client.is_connected:
            await self.get_blind_position()



    async def set_speed(self) -> None:
        """Set the speed for supported blind types"""
        _LOGGER.debug("%s: Attempting to set the blind speed", self.name)
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


        await self.ensure_connected()

        # send the command
        try:
            if self._client and self._client.is_connected:
                await self.send_command(UUID, command)
        except (BleakError, RuntimeError) as e:
            _LOGGER.debug("%s: Unable to set the speed: %s", self.name, e)
            await self.disconnect()
            raise RuntimeError(
                "Unable to set the speed. Check has enough battery and within bluetooth range or that blind supports speed changes"
            ) from e
        finally:
            # Always disconnect after set_speed operation
            await self.disconnect()


    ##################################################################################################
    ## GET METHODS ###################################################################################
    ##################################################################################################

    async def get_from_blind(self, command, callback) -> None:
        """Get the battery state from the blind as good or bad."""

        async with self._ble_lock:
            await self._get_from_blind_locked(command, callback)

    async def _get_from_blind_locked(self, command, callback) -> None:
        """Inner implementation — must only be called while _ble_lock is held."""
        # connect to the blind first
        await self.ensure_connected()

        # If a move started while we were connecting, bail — the move owns _client and
        # registering notifications here would overwrite set_position_callback.
        if self._locked:
            _LOGGER.debug("%s: Blind locked for movement — aborting concurrent BLE read", self.name)
            return

        assert self._client is not None
        notify_started = False
        try:
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
            notify_started = True
            self._notify_registered = True
        except BleakError as e:
            _LOGGER.debug("%s: Failed to start notify: %s. Attempting to stop and restart.", self.name, e)
            try:
                # when need to overwrite the existing notification
                await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
                self._notify_registered = False
                await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
                notify_started = True
                self._notify_registered = True
            except BleakError as retry_error:
                _LOGGER.warning("%s: Could not establish notifications: %s", self.name, retry_error)
                await self.disconnect()
                raise HomeAssistantError(f"{self.name}: Could not establish BLE notifications — characteristic not found") from retry_error

        # Only send command if we successfully started notifications and are still connected
        if notify_started and self._client and self._client.is_connected:
            try:
                await self.send_command(UUID, command)
            except Exception as e:
                _LOGGER.error("%s: Error sending command during get_from_blind: %s", self.name, e)
                await self.disconnect()
                raise HomeAssistantError(f"{self.name}: BLE send failed — {e}") from e

            # Wait for the response/callback to complete with timeout to prevent hanging
            if self._client:
                try:
                    await asyncio.wait_for(self.wait_for_stop(), timeout=10.0)
                except asyncio.TimeoutError:
                    _LOGGER.warning("%s: Timeout waiting for response in get_from_blind", self.name)
                finally:
                    await self.disconnect()
        else:
            # If we couldn't start notify, ensure we disconnect
            if not notify_started:
                await self.disconnect()


    async def get_battery_status(self) -> None:
        """Get the battery state from the blind as good or bad."""
        command = bytes.fromhex(CMD_BATTERY_STATUS)
        await self.get_from_blind(command, self.battery_callback)

    async def _post_move_battery_check(self) -> None:
        """Battery check run as part of the post-move background task (T+15s after stop)."""
        try:
            await self.get_battery_status()
        except Exception as e:
            _LOGGER.debug("%s: Post-move battery check failed: %s", self.name, e)


    async def get_blind_position(self) -> None:
        """Get the current position of the blind."""
        if self._locked:
            _LOGGER.debug("%s: Skipping position query — movement in progress", self.name)
            return
        command = bytes.fromhex(INITIALIZATION_MESSAGE)
        await self.get_from_blind(command, self.position_callback)

    ##################################################################################################
    ## LIMIT CONFIGURATION METHODS ##################################################################
    ##################################################################################################

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
        # Connect to the blind first
        _LOGGER.debug("Starting Limits Config. Attempting Connection")
        await self.ensure_connected()

        # Set the initialisation commands
        _LOGGER.debug("Sending initialisation commands")
        await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_INIT_2))


    async def limits_step_up(self) -> None:
        """Move the blind up incrementally for manual positioning."""
        self.limits_heartbeat_stop()
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Stepping up")
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_STEP_UP))


    async def limits_step_down(self) -> None:
        """Move the blind down incrementally for manual positioning."""
        self.limits_heartbeat_stop()
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Stepping down")
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_STEP_DOWN))


    async def limits_move_up(self) -> None:
        """Move the blind up continuously for manual positioning (stubbed for now)."""
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Moving up")
        move_command = CMD_LIMITS_MOVE_UP
        await self.send_command(UUID, bytes.fromhex(move_command))
        self.limits_heartbeat_start(move_command)


    async def limits_move_down(self) -> None:
        """Move the blind down continuously for manual positioning (stubbed for now)."""
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Moving down")
        move_command = CMD_LIMITS_MOVE_DOWN
        await self.send_command(UUID, bytes.fromhex(move_command))
        self.limits_heartbeat_start(move_command)


    async def limits_stop(self) -> None:
        """Stop the blind movement."""
        self.limits_heartbeat_stop()
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Stopping movement")
        await self.send_command(UUID, bytes.fromhex(CMD_STOP))


    async def limits_set(self) -> None:
        """Sets the limit."""
        self.limits_heartbeat_stop()
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")

        _LOGGER.debug("Setting the limit")
        await self.send_command(UUID, bytes.fromhex(CMD_STOP))
        await self.send_command(UUID, bytes.fromhex(CMD_LIMITS_SET))

    ##################################################################################################
    ## TIMER METHODS #################################################################################
    ##################################################################################################

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


    async def async_load_presets(self) -> None:
        """Load stored position presets; fall back to empty on corruption."""
        try:
            stored = await self._presets_store.async_load()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "%s: Failed to load presets from storage (%s); starting empty",
                self.name, exc,
            )
            self.presets = {}
            return
        if stored and isinstance(stored, dict):
            clean: dict[str, float] = {}
            for name, position in stored.items():
                if not isinstance(name, str) or not name.strip():
                    _LOGGER.warning(
                        "%s: Dropping preset with invalid name %r",
                        self.name, name,
                    )
                    continue
                try:
                    pos_f = float(position)
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "%s: Dropping preset %r with invalid position %r",
                        self.name, name, position,
                    )
                    continue
                if not 0 <= pos_f <= 100:
                    _LOGGER.warning(
                        "%s: Dropping preset %r with out-of-range position %s",
                        self.name, name, pos_f,
                    )
                    continue
                clean[name] = pos_f
            self.presets = clean
            # Re-persist if we dropped anything so the next restart is clean.
            if len(clean) != len(stored):
                await self._presets_store.async_save(clean)
        else:
            self.presets = {}

    async def async_save_presets(self) -> None:
        """Persist position presets to storage."""
        await self._presets_store.async_save(self.presets)

    async def async_apply_preset(self, name: str) -> None:
        """Move the blind to the position stored under ``name``.

        Dispatches directly to ``async_move_cover`` to bypass HA's
        ``cover.set_cover_position`` int-coercion and preserve 0.1%
        precision end-to-end. Refuses when the live position is unknown
        rather than guessing a direction.
        """
        if name not in self.presets:
            raise HomeAssistantError(
                f"{self.name}: preset {name!r} not found"
            )
        position = float(self.presets[name])
        current = self._current_cover_position
        if current is None:
            raise HomeAssistantError(
                f"{self.name}: preset {name!r} cannot apply — current "
                "position is unknown. Move the blind once so its "
                "position is read, then try again."
            )
        movement_direction = 1 if current <= position else -1
        try:
            await self.async_move_cover(
                movement_direction=movement_direction,
                target_position=100 - position,
            )
        except (ConnectionTimeout, DeviceNotFound, HomeAssistantError) as e:
            raise HomeAssistantError(
                f"{self.name}: preset {name!r} failed to apply: {e}"
            ) from e
        _LOGGER.info(
            "%s: Applied preset %r -> %s%%", self.name, name, position
        )

    async def async_save_current_as_preset(self, name: str) -> float | None:
        """Save the live cover position under ``name``.

        Returns the stored float, or None if position has never been read.
        Raises ValueError on empty/non-string names.
        """
        if not isinstance(name, str):
            raise ValueError("preset name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("preset name cannot be empty or whitespace only")
        current = self._current_cover_position
        if current is None:
            _LOGGER.warning(
                "%s: Cannot save preset %r — current position is unknown",
                self.name, name,
            )
            return None
        # Clamp against transient out-of-range frames.
        position = max(0.0, min(100.0, float(current)))
        self.presets[name] = position
        await self.async_save_presets()
        self.publish_updates()
        _LOGGER.info(
            "%s: Saved preset %r at current position %s%%",
            self.name, name, position,
        )
        return position


    async def async_add_timer(self, days: list[str], time_str: str, position: float) -> str:
        """Add a new schedule."""
        await self.ensure_connected()

        new_timer_id = None
        timer_id_event = asyncio.Event()

        async def timer_id_callback(sender, data):
            nonlocal new_timer_id
            decimals = self.split_data(data)
            # Filter for the correct response: 7 bytes long, where the 5th byte is 0xd6 (214)
            if len(decimals) >= 7 and decimals[4] == 214:
                new_timer_id = str(decimals[6])
                timer_id_event.set()

        try:
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, timer_id_callback)
        except BleakError:
            await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, timer_id_callback)

        await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
        await self.send_timestamp()
        await self.send_command(UUID, bytes.fromhex(CMD_TIMER_REQUEST))

        try:
            await asyncio.wait_for(timer_id_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            await self.disconnect()
            raise HomeAssistantError("Timeout waiting for timer ID from blind.")

        await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)

        _LOGGER.debug("Received timer ID from blind: %s", new_timer_id)

        if not new_timer_id:
            await self.disconnect()
            _LOGGER.debug("Failed to obtain timer ID from the blind.")
            raise HomeAssistantError("Failed to obtain timer ID from the blind.")

        if int(new_timer_id) >= 17:
            await self.disconnect()
            _LOGGER.debug("Maximum number of timers reached.")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="max_timers_reached",
                translation_placeholders={"max_timers": "16"}
            )

        timer_id = new_timer_id
        timer_command = self.create_timer_command(timer_id, days, time_str, position)

        await self.send_command(UUID, bytes.fromhex(timer_command))
        await self.send_command(UUID, bytes.fromhex(CMD_BATTERY_STATUS))
        await self.disconnect()

        existing_ha_indices = {t.get("ha_index") for t in self.timers.values() if "ha_index" in t}
        available_indices = set(range(1, 17)) - existing_ha_indices
        ha_index = min(available_indices) if available_indices else len(self.timers) + 1

        self.timers[timer_id] = {
            "timer_id": timer_id,
            "ha_index": ha_index,
            "days": days,
            "time": time_str,
            "position": position
        }

        await self.async_save_timer()
        self.publish_updates()
        async_dispatcher_send(self.hub._hass, f"{DOMAIN}_add_timer_{self.blind_id}", timer_id)
        return timer_id


    async def async_delete_timer(self, timer_id: str) -> None:
        """Remove an existing schedule."""
        await self.ensure_connected()

        await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
        await self.send_timestamp()
        await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
        delete_hex = f"{CMD_TIMER_DELETE_BASE}{int(timer_id):02x}" #schedule index in hex, convert from string to int to hex
        await self.send_command(UUID, bytes.fromhex(delete_hex))
        await self.send_command(UUID, bytes.fromhex(CMD_BATTERY_STATUS))
        await self.disconnect()

        if timer_id in self.timers:
            del self.timers[timer_id]
            await self.async_save_timer()
            async_dispatcher_send(self.hub._hass, f"{DOMAIN}_delete_timer_{self.blind_id}_{timer_id}")
            self.publish_updates()



    async def delete_all_timers(self) -> None:
        """Delete all timers from the blind."""
        _LOGGER.debug("%s: Attempting to delete all timers.", self.name)
        # Connect to the blind first
        await self.ensure_connected()

        await self.send_command(UUID, bytes.fromhex(CONNECTION_MESSAGE))
        await self.send_timestamp()
        await self.send_command(UUID, bytes.fromhex(INITIALIZATION_MESSAGE))
        await self.send_command(UUID, bytes.fromhex(CMD_TIMER_RESET)) # reset command

        await self.disconnect()

        # Reconnect to the blind to ensure it's back online after reset
        await self.attempt_connection()
        await self.send_command(UUID, bytes.fromhex(CMD_BLIND_REACTIVATE)) # reactivate blind
        await self.disconnect()

        #remove any timer entities
        if self.timers:
            timer_ids = list(self.timers.keys())
            for timer_id in timer_ids:
                async_dispatcher_send(self.hub._hass, f"{DOMAIN}_delete_timer_{self.blind_id}_{timer_id}")

            self.timers.clear()
            await self.async_save_timer()
            self.publish_updates()




    def create_timer_command(self, index: str, days: list[str], time: str, position: float) -> str:
        # Convert days to bitmask
        day_map = {"sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64}
        day_bits = sum(day_map[day] for day in days if day in day_map)

        # Convert time to minutes since midnight
        time_parts = time.split(":")
        hours = int(time_parts[0])
        minutes = int(time_parts[1])

        # Convert position to fixed-point (e.g., multiply by 10)
        target_position_value = int(float(position) * 10)
        position_byte_1 = target_position_value % 256
        position_byte_2 = target_position_value // 256


        # Construct the command (example format)
        cmd_hex = "ff78ea410300"
        cmd_hex += f"{int(index):02x}"   # Timer index converted to hex
        cmd_hex += "b2"   # not sure
        cmd_hex += "3f"   # not sure
        cmd_hex += f"{day_bits:02x}" # Days bitmask
        cmd_hex += f"{hours:02x}" # Time hours
        cmd_hex += f"{minutes:02x}" # Time minutes
        cmd_hex += "00"  # Padding
        cmd_hex += f"{position_byte_1:02x}" # Position byte
        cmd_hex += f"{position_byte_2:02x}" # Position byte

        return cmd_hex




    ##################################################################################################
    ## CALLBACK METHODS ##############################################################################
    ##################################################################################################

    async def battery_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status.

        NOTE: Same duplicate-packet behaviour as position_callback — two identical
        packets arrive within ~60ms. Second fire is benign for the same reasons.
        """
        decimals = self.split_data(data)
        _LOGGER.debug("%s: battery_callback raw decimals (len=%d): %s", self.name, len(decimals), decimals)

        matched = len(decimals) > 4 and decimals[4] in (2, 210)

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
            self._stopped_event.set()
        else:
            _LOGGER.debug(
                "%s: battery_callback — decimals[4]=%s not in known discriminators (2, 210); skipping parse",
                self.name,
                decimals[4] if len(decimals) > 4 else "N/A",
            )

    async def position_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status.

        NOTE: Tuiss firmware sends duplicate BLE notify packets for the same read —
        two identical packets arrive within ~60ms of each other. This is normal firmware
        behaviour and results in this callback firing twice per position query. The second
        fire is benign: _current_cover_position is overwritten with the same value,
        _stopped_event.set() is a no-op (already set), and publish_updates() fires once
        more. Not worth deduplicating given the negligible cost.
        """
        _LOGGER.debug("%s: Attempting to get position", self.name)

        decimals = self.split_data(data)

        if len(decimals) < 9:
            # Short packets (e.g. battery notifications) can arrive on the shared
            # characteristic while this callback is registered. Don't crash — just
            # wait; the 10s timeout in get_from_blind is the safety net.
            _LOGGER.debug(
                "%s: position_callback — packet too short (len=%d): %s — waiting for position packet",
                self.name, len(decimals), decimals,
            )
            return

        blindPos = (decimals[7] + (256 * decimals[8])) / 10
        _LOGGER.debug("%s: Blind position is %s", self.name, blindPos)
        self._current_cover_position = blindPos
        if self._moving != 0:
            # A concurrent position read arrived while the blind is moving (e.g. a
            # dashboard poll queued behind the movement). Update position but don't
            # signal stop — movement continues until set_position_callback fires near
            # the target. Without this guard the stop event fires prematurely and
            # wait_for_stop() returns while the blind is still physically moving.
            _LOGGER.debug(
                "%s: position_callback during movement — position updated, stop not signalled",
                self.name,
            )
            return
        self._moving = 0
        self._stopped_event.set()

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
        now = datetime.datetime.now()
        timestamp_command = f"{CMD_TIMESTAMP_BASE}{now.year - 2000:02x}{now.month:02x}{now.day:02x}{now.hour:02x}{now.minute:02x}{now.second:02x}"
        await self.send_command(UUID, bytes.fromhex(timestamp_command))

    # Creates the % open/closed hex command
    def hex_convert(self, user_percent: float) -> str:
        """Convert the Home Assistant position percentage (0-100) to the Tuiss hex command."""
        # Tuiss uses an inverted percentage (0=open, 100=closed)
        tuiss_percent = 100 - user_percent

        # Calculate the absolute position value (0-1000)
        total_val = int(round(tuiss_percent * 10))

        # Extract lower byte (position) and upper byte (group)
        position_value = total_val % 256
        group_value = total_val // 256

        # Format the position value as a two-character hex (e.g., 0A, FF)
        hex_val = f"{position_value:02x}"
        group_str = f"{group_value:02x}"

        # Build the final command
        command_prefix = "ff78ea41bf03"
        return f"{command_prefix}{hex_val}{group_str}"

    def split_data(self, data: bytearray) -> list[int]:
        """Convert the byte response into a list of decimals."""
        decimals = list(data)
        _LOGGER.debug("%s: Received data decimals: %s", self.name, decimals)
        return decimals


    async def async_move_cover(
        self,
        movement_direction,
        target_position,
        skip_battery_check=False
    ):
        """Move the cover."""
        _LOGGER.debug("%s: Entering async_move_cover. Locked: %s", self.name, self._locked)
        if not self._locked:
            # Cancel any background position/battery task from the previous move so it
            # doesn't race the BLE operations we're about to start.
            if self._post_move_task and not self._post_move_task.done():
                self._post_move_task.cancel()
                try:
                    await self._post_move_task
                except asyncio.CancelledError:
                    pass
                self._post_move_task = None
            # Wait for any concurrent get_from_blind (dashboard poll, background read) to
            # finish before connecting. Without this, attempt_connection() races the
            # get_from_blind caller's establish_connection(), causing BlueZ "InProgress".
            if self._ble_lock.locked():
                _LOGGER.debug("%s: Waiting for concurrent BLE read to finish before movement", self.name)
                async with self._ble_lock:
                    pass  # acquire + release just to serialise; don't hold during movement
            await self.attempt_connection()
            if self._client and self._client.is_connected:
                self._locked = True
                _LOGGER.debug("%s: Lock acquired.", self.name)
                self._is_stopping = False
                start_position = self._current_cover_position
                corrected_target_position = 100 - target_position
                self._moving = movement_direction

                # Update the state and trigger the moving
                self.publish_updates()

                _LOGGER.debug(
                            "%s: Battery check age (%s days). Last check: %s.",
                            self.name,
                            self._battery_check_days,
                            self._last_battery_check,
                        )

                # Perform a battery check before moving if configured
                try:
                    if not skip_battery_check and self._battery_check_days and (
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
                        # It's OK if this fails — we still proceed with the movement
                        try:
                            await self.get_battery_status()
                        except Exception as e:
                            _LOGGER.debug("%s: Battery check failed: %s", self.name, e)
                except Exception:
                    # Defensive: don't let battery-check logic break movement
                    _LOGGER.debug("%s: Error while evaluating battery check timing", self.name)

                move_sent = False
                for _attempt in range(2):
                    try:
                        # Timeout on set_position to prevent hanging indefinitely
                        await asyncio.wait_for(self.set_position(target_position), timeout=30.0)
                        move_sent = True
                        break
                    except asyncio.TimeoutError:
                        _LOGGER.error("%s: set_position() timed out after 30s. Unsticking blind.", self.name)
                        self._moving = 0
                        self._locked = False
                        self.publish_updates()
                        await self.disconnect()
                        return
                    except Exception as e:
                        if _attempt == 0 and 'NotConnected' in str(e):
                            # BLE link dropped silently — disconnect to clear stale client
                            # and let ensure_connected() re-establish on the next attempt.
                            _LOGGER.warning(
                                "%s: Move command got NotConnected — reconnecting and retrying.",
                                self.name,
                            )
                            await self.disconnect()
                            continue
                        _LOGGER.error("%s: Failed to send move command: %s. Unsticking blind.", self.name, e)
                        self._moving = 0
                        self._locked = False
                        self.publish_updates()
                        await self.disconnect()
                        return
                if not move_sent:
                    return

                end_time = None
                start_time = datetime.datetime.now()

                async def aync_update_position_in_realtime():
                    """Task to update the position while the blind is moving."""
                    while self._client and self._client.is_connected and not self._is_stopping:
                        if self._attr_traversal_speed is not None:
                            _LOGGER.debug(
                                "%s: StartPos: %s. CurrentPos: %s. TargetPos: %s. Timedelta: %s",
                                self.name,
                                start_position,
                                self._current_cover_position,
                                corrected_target_position,
                                (datetime.datetime.now() - start_time).total_seconds(),
                            )
                            traversal_difference = (
                                (datetime.datetime.now() - start_time).total_seconds()
                                * self._attr_traversal_speed
                                * movement_direction
                            )
                            self._current_cover_position = round(
                                sorted([
                                    min(start_position, corrected_target_position),
                                    start_position + traversal_difference,
                                    max(start_position, corrected_target_position),
                                ])[1], 2
                            )
                            self.publish_updates()

                        await asyncio.sleep(1)

                update_task = self.hub._hass.async_create_task(aync_update_position_in_realtime())

                try:
                    # Calculate timeout based on traversal speed or use default
                    if (self._attr_traversal_speed is not None and
                        self._attr_traversal_speed >= 1 and
                        self._attr_traversal_speed < 6):
                        timeout_duration = ((abs(corrected_target_position - start_position) * 1.2) / self._attr_traversal_speed) + 10
                    else:
                        timeout_duration = TIMEOUT_SECONDS or 120

                    _LOGGER.debug(
                        "%s: Waiting for stop event with timeout: %s seconds. Traversal speed: %s",
                        self.name,
                        timeout_duration,
                        self._attr_traversal_speed,
                    )
                    await asyncio.wait_for(self.wait_for_stop(), timeout=timeout_duration)
                    # Movement complete — confirm final position while BLE is warm.
                    # Battery check is scheduled with a 12s delay so the sync_blind_position
                    # automation (fires at T+2s) has finished before we reuse the characteristic.
                    if not self._is_stopping:
                        # Cancel dead-reckoning now that movement is confirmed complete.
                        update_task.cancel()
                        # Schedule position confirmation and battery check as a background
                        # task. T+5s gives the BLE characteristic time to clear after any
                        # sync_blind_position automation (fires T+2s, takes 1-3s to complete).
                        try:
                            async def _post_move_queries():
                                try:
                                    await asyncio.sleep(5)
                                    try:
                                        await self.get_blind_position()
                                    except Exception as e:
                                        _LOGGER.debug("%s: Post-move position query failed: %s", self.name, e)
                                    await asyncio.sleep(10)
                                    await self._post_move_battery_check()
                                except asyncio.CancelledError:
                                    _LOGGER.debug("%s: Post-move queries cancelled — new command received", self.name)
                            self._post_move_task = self.hub._hass.async_create_task(_post_move_queries())
                        except Exception as e:
                            _LOGGER.debug("%s: Failed to schedule post-move queries: %s", self.name, e)
                except asyncio.TimeoutError:
                    _LOGGER.warning("%s: Timeout waiting for blind to stop", self.name)
                    update_task.cancel()
                    self._locked = False  # Release before disconnect so disconnect() isn't skipped
                    await self.disconnect()
                    # Don't assume the blind reached the target — it may not have moved at
                    # all (BLE failure, firmware no-op). Setting state to the target would
                    # corrupt _current_cover_position and cause the next command to compute
                    # zero travel distance and a 10-second timeout. Query actual position
                    # instead so state reflects reality.
                    self._moving = 0
                    self.publish_updates()
                    async def _query_after_timeout():
                        await asyncio.sleep(3)
                        try:
                            await self.get_blind_position()
                        except Exception as e:
                            _LOGGER.debug("%s: Post-timeout position query failed: %s", self.name, e)
                    self._post_move_task = self.hub._hass.async_create_task(_query_after_timeout())
                    _LOGGER.debug("%s: Lock released following timeout", self.name)
                    return  # stops blind updating traversal speed if it timesout
                finally:
                    update_task.cancel()
                    self._locked = False  # Release before disconnect so disconnect() isn't skipped
                    # Ensure disconnect is called in all cases (no-op if post-move sync already disconnected)
                    await self.disconnect()
                    _LOGGER.debug("%s: Lock released in async_move_cover.", self.name)

                # set the traversal speed average and update final states only if the blind has not been stopped, as that updates itself
                _LOGGER.debug(
                    "%s: Finished moving. StartPos: %s. CurrentPos: %s. TargetPos: %s. is_stopping: %s",
                    self.name,
                    start_position,
                    self._current_cover_position,
                    corrected_target_position,
                    self._is_stopping,
                )
                if not self._is_stopping:
                    end_time = datetime.datetime.now()
                    self.update_traversal_speed(
                        corrected_target_position, start_position, start_time, end_time
                    )
                    # Use BLE-confirmed position (_current_cover_position was updated by
                    # get_blind_position above). Only fall back to desired target if BLE
                    # query failed and left _current_cover_position unchanged from movement.
                    self._moving = 0
                    self.publish_updates()

        elif self._locked:
            _LOGGER.debug(
                "%s is locked, please wait for currrent command to complete and then try again.",
                self.name,
            )
            # Use translation placeholder so the frontend can localise the message
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_locked",
                translation_placeholders={
                    "name": self.name,
                })

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
