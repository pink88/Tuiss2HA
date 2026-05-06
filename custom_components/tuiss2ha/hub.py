"""Tuiss Smartview and Blinds2go BLE Home."""

from __future__ import annotations

import asyncio
import logging
import datetime
import uuid

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

from .const import (
    DOMAIN,
    BLIND_NOTIFY_CHARACTERISTIC,
    UUID,
    CONNECTION_MESSAGE,
    DEFAULT_RESTART_ATTEMPTS,
    DeviceNotFound,
    ConnectionTimeout,
    NoConnectableBluetoothAdapter,
    TIMEOUT_SECONDS,
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
        self._heartbeat_task: asyncio.Task | None = None
        self._last_connection_error: str | None = None  # For logging when connection fails
        # Battery check configuration
        self._battery_check_days: int = 0
        self._last_battery_check: datetime.datetime | None = None
        self.timers = {}
        self._store = Store(self.hub._hass, 1, f"tuiss2ha_{self.host.replace(':', '').lower()}_schedules")


    @property
    def blind_id(self) -> str:
        """Return ID for blind."""
        return self._id

    @property
    def rssi(self) -> int | None:
        """Return the rssi for the blind."""
        return self._rssi

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

    async def _heartbeat(self):
        """Send heartbeat command periodically."""
        _LOGGER.debug("%s: Starting heartbeat task", self.name)
        heartbeat_cmd = bytes.fromhex("ff010101010101")
        try:
            while True:
                await asyncio.sleep(2.0)
                if self._client and self._client.is_connected:
                    try:
                        await self._client.write_gatt_char(UUID, heartbeat_cmd)
                        _LOGGER.debug("%s: Heartbeat sent", self.name)
                    except Exception as e:
                        _LOGGER.debug("%s: Heartbeat failed: %s", self.name, e)
                else:
                    _LOGGER.debug("%s: Client not connected, stopping heartbeat", self.name)
                    break
        except asyncio.CancelledError:
            _LOGGER.debug("%s: Heartbeat task cancelled", self.name)
        except Exception as e:
            _LOGGER.error("%s: Heartbeat task error: %s", self.name, e)

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
            # send the maintain connection message
            await self._client.write_gatt_char(UUID, bytes.fromhex(CONNECTION_MESSAGE))

            # send the connection timestamp message
            now = datetime.datetime.now()
            year = now.year - 2000 
            month = now.month
            day = now.day
            hour = now.hour
            minute = now.minute
            second = now.second

            await self._client.write_gatt_char(UUID, bytes.fromhex("ff78ea410200" + f"{year:02x}{month:02x}{day:02x}{hour:02x}{minute:02x}{second:02x}"))
    
            # # Start heartbeat
            # if self._heartbeat_task:
            #     self._heartbeat_task.cancel()
            # self._heartbeat_task = self.hub._hass.loop.create_task(self._heartbeat())

            _LOGGER.debug(
                "%s: Connected. Current Position: %s. Current Moving: %s",
                self.name,
                self._current_cover_position,
                self._moving,
            )
        except (BleakError, asyncio.TimeoutError) as e:
            self._last_connection_error = str(e)
            _LOGGER.debug("Failed to connect to blind: %s", e)
        except Exception as e:
            self._last_connection_error = f"{type(e).__name__}: {e}"
            _LOGGER.debug("%s: Unexpected error during connect: %s", self.name, e)

    # Disconnect
    async def disconnect(self):
        """Disconnect from the blind."""
        # if self._heartbeat_task:
        #     self._heartbeat_task.cancel()
        #     self._heartbeat_task = None

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
                "Disconnect. Current Position: %s. Current Moving: %s",
                self._current_cover_position,
                self._moving,
            )
        finally:
            self._stopped_event.set()

    async def wait_for_stop(self):
        """Wait for the blind to stop moving."""
        self._stopped_event.clear()
        await self._stopped_event.wait()
        
    async def _ensure_connected(self) -> None:
        """Ensure the blind is connected before sending a command."""
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

    ##################################################################################################
    ## SET METHODS ###################################################################################
    ##################################################################################################
    async def set_position(self, userPercent) -> None:
        """Set the position of the blind converting from HA to Tuiss first."""

        await self._ensure_connected()

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
        except BleakError:
            await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            await self._client.start_notify(
                BLIND_NOTIFY_CHARACTERISTIC, self.set_position_callback
            )
        await self.send_command(UUID, command)  # send the command

    async def stop(self) -> None:
        """Stop the blind at current position."""
        _LOGGER.debug("%s: Attempting to stop the blind.", self.name)
        command = bytes.fromhex("ff78ea415f0301")

        # skip if the blind is not moving
        if self._moving == 0:
            return

        # try to connect to blind if not connected, shouldnt really be necessary if the blind is already moving
        await self._ensure_connected()

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
                command = bytes.fromhex("ff78ea41f202")
            case "Comfort":
                command = bytes.fromhex("ff78ea41f201")
            case "Slow":
                command = bytes.fromhex("ff78ea41f200")


        await self._ensure_connected()
        
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

        # connect to the blind first
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

        assert self._client is not None
        notify_started = False
        try:
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
            notify_started = True
        except BleakError as e:
            _LOGGER.debug("%s: Failed to start notify: %s. Attempting to stop and restart.", self.name, e)
            try:
                # when need to overwrite the existing notification
                await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
                await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
                notify_started = True
            except BleakError as retry_error:
                _LOGGER.warning("%s: Could not establish notifications: %s", self.name, retry_error)
                # Characteristic may not exist or device disconnected; ensure cleanup
                await self.disconnect()
                return

        # Only send command if we successfully started notifications and are still connected
        if notify_started and self._client and self._client.is_connected:
            try:
                await self.send_command(UUID, command)
            except Exception as e:
                _LOGGER.error("%s: Error sending command during get_from_blind: %s", self.name, e)
                await self.disconnect()
                return

            # Wait for the response/callback to complete with timeout to prevent hanging
            if self._client:
                try:
                    await asyncio.wait_for(self.wait_for_stop(), timeout=10.0)
                except asyncio.TimeoutError:
                    _LOGGER.warning("%s: Timeout waiting for response in get_from_blind", self.name)
                    await self.disconnect()
        else:
            # If we couldn't start notify, ensure we disconnect
            if not notify_started:
                await self.disconnect()
                    

    async def get_battery_status(self) -> None:
        """Get the battery state from the blind as good or bad."""
        command = bytes.fromhex("ff78ea41f00301")
        await self.get_from_blind(command, self.battery_callback)

    async def get_blind_position(self) -> None:
        """Get the current position of the blind."""
        command = bytes.fromhex("ff78ea41d10301")
        await self.get_from_blind(command, self.position_callback)

    ##################################################################################################
    ## LIMIT CONFIGURATION METHODS ##################################################################
    ##################################################################################################

    async def limits_initialise(self) -> None:
        """Initialise the limit configuration by connecting to the blind."""
        # Connect to the blind first
        _LOGGER.debug("Starting Limits Config. Attempting Connection")
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()
            
        # Set the initialisation commands
        _LOGGER.debug("Sending initialisation commands")
        await self.send_command(UUID, bytes.fromhex("ff78ea41d10301"))
        await self.send_command(UUID, bytes.fromhex("ff78ea41210301"))
    
    async def _send_limit_command(self, action_name: str, hex_command: str) -> None:    
        """Helper method to execute a limit configuration step."""
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")
        _LOGGER.debug(action_name)
        await self.send_command(UUID, bytes.fromhex(hex_command))


    async def limits_step_up(self) -> None:
        """Move the blind up incrementally for manual positioning."""
        await self._send_limit_command("Stepping up", "ff78ea41220301")



    async def limits_step_down(self) -> None:
        """Move the blind down incrementally for manual positioning."""
        await self._send_limit_command("Stepping up", "ff78ea41220301")



    async def limits_move_up(self) -> None:
        """Move the blind up continuously for manual positioning (stubbed for now)."""
        await self._send_limit_command("Moving up", "ff78ea41cf0301")



    async def limits_move_down(self) -> None:
        """Move the blind down continuously for manual positioning (stubbed for now)."""
        await self._send_limit_command("Moving down", "ff78ea411f0301")

        
        
    async def limits_stop(self) -> None:
        """Stop the blind movement."""
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")  
        
        _LOGGER.debug("Stopping movement")
        await self.send_command(UUID, bytes.fromhex("ff78ea415f0301"))
        
        
    async def set_limit(self) -> None:
        """Sets the limit."""
        # Connect to the blind first
        if not self._client or not self._client.is_connected:
            _LOGGER.debug("Connection lost, limits set up failed")
        
        _LOGGER.debug("Setting the limit")
        await self.send_command(UUID, bytes.fromhex("ff78ea415f0301"))
        await self.send_command(UUID, bytes.fromhex("ff78ea41410301"))


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


    async def async_add_timer(self, days: list[str], time_str: str, position: float) -> str:
        """Add a new schedule."""
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()      

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

        current_time = datetime.datetime.now()
        timestamp_command = f"ff78ea410200{current_time.year - 2000:02x}{current_time.month:02x}{current_time.day:02x}{current_time.hour:02x}{current_time.minute:02x}{current_time.second:02x}"        
        
        await self.send_command(UUID, bytes.fromhex("ff03030303787878787878"))   
        await self.send_command(UUID, bytes.fromhex(timestamp_command))   
        await self.send_command(UUID, bytes.fromhex("ff78ea4104"))   
        
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
        await self.send_command(UUID, bytes.fromhex("ff78ea41f00301"))
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
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()     
        
        current_time = datetime.datetime.now()
        timestamp_command = f"ff78ea410200{current_time.year - 2000:02x}{current_time.month:02x}{current_time.day:02x}{current_time.hour:02x}{current_time.minute:02x}{current_time.second:02x}"    
        
        await self.send_command(UUID, bytes.fromhex("ff03030303787878787878"))
        await self.send_command(UUID, bytes.fromhex(timestamp_command))      
        await self.send_command(UUID, bytes.fromhex("ff78ea41d10301"))
        delete_hex = f"ff78ea410301{int(timer_id):02x}" #schedule index in hex, convert from string to int to hex
        await self.send_command(UUID, bytes.fromhex(delete_hex))
        await self.send_command(UUID, bytes.fromhex("ff78ea41f00301"))
        await self.disconnect()
        
        if timer_id in self.timers:
            del self.timers[timer_id]
            await self.async_save_timer()
            async_dispatcher_send(self.hub._hass, f"{DOMAIN}_delete_timer_{self.blind_id}_{timer_id}")
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
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get battery status", self.name)

        decimals = self.split_data(data)

        if decimals[4] == 210:
            if len(decimals) == 7 or decimals[5] >= 10:
                _LOGGER.debug(
                    "%s: Please charge device", self.name
                )  # think its based on the length of the response? ff010203d2 (bad) vs ff010203d202e803 (good)
                self._battery_status = True
            elif decimals[5] < 10:
                _LOGGER.debug("%s: Battery is good", self.name)
                self._battery_status = False
            else:
                _LOGGER.debug("%s: Battery logic is wrong", self.name)
                self._battery_status = None
            # Record time of this battery check
            try:
                self._last_battery_check = datetime.datetime.now()
            except Exception:
                self._last_battery_check = None
            await self.disconnect()

    async def position_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get position", self.name)

        decimals = self.split_data(data)

        blindPos = (decimals[7] + (256 * decimals[8])) / 10
        _LOGGER.debug("%s: Blind position is %s", self.name, blindPos)
        self._current_cover_position = blindPos
        self._moving = 0
        await self.disconnect()

    async def set_position_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ):
        """Wait for response from the blind and disconnects. Used to keep alive."""
        _LOGGER.debug(
            "%s: Disconnecting based on response %s", self.name, self.split_data(data)
        )
        await self.disconnect()

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
                            (datetime.datetime.now() - self._last_battery_check).total_seconds()
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
                
                try:
                    # Timeout on set_position to prevent hanging indefinitely
                    await asyncio.wait_for(self.set_position(target_position), timeout=30.0)
                except asyncio.TimeoutError:
                    _LOGGER.error("%s: set_position() timed out after 30s. Unsticking blind.", self.name)
                    self._moving = 0
                    self._locked = False
                    self.publish_updates()
                    await self.disconnect()
                    return
                except Exception as e:
                    _LOGGER.error("%s: Failed to send move command: %s. Unsticking blind.", self.name, e)
                    # Command failed; unstick the blind immediately
                    self._moving = 0
                    self._locked = False
                    self.publish_updates()
                    await self.disconnect()
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
                                sorted([0, start_position + traversal_difference, 100])[1], 2
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
                except asyncio.TimeoutError:
                    _LOGGER.warning("%s: Timeout waiting for blind to stop", self.name)
                    update_task.cancel()
                    # await self.get_blind_position()
                    await self.disconnect()
                    self.set_final_state(corrected_target_position)
                    _LOGGER.debug("%s: Lock released following timeout", self.name)
                    self._locked = False
                    return  # stops blind updating traversal speed if it timesout
                finally:
                    update_task.cancel()
                    # Ensure disconnect is called in all cases
                    await self.disconnect()
                    # unlock the entity to allow more changes
                    self._locked = False
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

                    self.set_final_state(corrected_target_position)

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
