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

from .const import (
    DOMAIN,
    BLIND_NOTIFY_CHARACTERISTIC,
    UUID,
    CONNECTION_MESSAGE,
    DEFAULT_RESTART_ATTEMPTS,
    DeviceNotFound,
    ConnectionTimeout,
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
        self.model = self._ble_device.name if self._ble_device else None
        self._rssi: int | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._callbacks = set()
        self._battery_status = False
        self._moving = 0
        self._is_stopping = False
        self._current_cover_position: float | None = None
        self._desired_position: int | None = None
        self._desired_orientation = False
        self._restart_attempts: int | None = None
        self._position_on_restart: bool | None = None
        self._blind_speed: str | None = None
        


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
        self._rssi = rssi
        for callback in self._callbacks:
            callback()

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
            rediscover_attempts += 1
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
            await self.blind_connect()

            # If the client is connected, return early
            if self._client and self._client.is_connected:
                return

            retry_count += 1

        # If we reach here, we have exceeded max retries
        _LOGGER.error("%s: Connection failed too many times [%d]", self.name, self._restart_attempts)
        raise ConnectionTimeout(f"{self.name}: Connection failed too many times [{self._restart_attempts}]")

    # Connect
    async def blind_connect(self):
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
            _LOGGER.debug(
                "%s: Connected. Current Position: %s. Current Moving: %s",
                self.name,
                self._current_cover_position,
                self._moving,
            )
        except (BleakError, asyncio.TimeoutError) as e:
            _LOGGER.debug("Failed to connect to blind: %s", e)

    # Disconnect
    async def blind_disconnect(self):
        """Disconnect from the blind."""
        client = self._client
        if not client:
            _LOGGER.debug("%s: Already disconnected", self.name)
            return
        _LOGGER.debug("%s: Disconnecting", self.name)
        try:
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

    ##################################################################################################
    ## SET METHODS ############################################################################
    ##################################################################################################
    async def set_position(self, userPercent) -> None:
        """Set the position of the blind converting from HA to Tuiss first."""

        # connect to the blind first
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

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
        finally:
            await self.send_command(UUID, command)  # send the command

    async def stop(self) -> None:
        """Stop the blind at current position."""
        _LOGGER.debug("%s: Attempting to stop the blind.", self.name)
        command = bytes.fromhex("ff78ea415f0301")

        # skip if the blind is not moving
        if self._moving == 0:
            return

        # try to connect to blind if not connected, shouldnt really be necessary if the blind is already moving
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

        # send the stop command
        try:
            if self._client and self._client.is_connected:
                await self.send_command(UUID, command)
        except (BleakError, RuntimeError) as e:
            _LOGGER.debug("%s: Stop failed: %s", self.name, e)
            raise RuntimeError(
                "Unable to STOP as connection to your blind has been lost. Check has enough battery and within bluetooth range"
            ) from e

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


        # connect to the blind first
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()
        
        # send the command
        try:
            if self._client and self._client.is_connected:
                await self.send_command(UUID, command)
                await self.blind_disconnect()
        except (BleakError, RuntimeError) as e:
            _LOGGER.debug("%s: Unable to set the speed: %s", self.name, e)
            raise RuntimeError(
                "Unable to set the speed. Check has enough battery and within bluetooth range"
            ) from e
        


    ##################################################################################################
    ## GET METHODS ############################################################################
    ##################################################################################################

    async def get_from_blind(self, command, callback) -> None:
        """Get the battery state from the blind as good or bad."""

        # connect to the blind first
        if not self._client or not self._client.is_connected:
            await self.attempt_connection()

        assert self._client is not None
        try:
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
        except BleakError:
            # when need to overwrite the existing notification
            await self._client.stop_notify(BLIND_NOTIFY_CHARACTERISTIC)
            await self._client.start_notify(BLIND_NOTIFY_CHARACTERISTIC, callback)
        finally:
            await self.send_command(UUID, command)
            if self._client:
                while self._client.is_connected:
                    await asyncio.sleep(1)
                    

    async def get_battery_status(self) -> None:
        """Get the battery state from the blind as good or bad."""
        command = bytes.fromhex("ff78ea41f00301")
        await self.get_from_blind(command, self.battery_callback)

    async def get_blind_position(self) -> None:
        """Get the current position of the blind."""
        command = bytes.fromhex("ff78ea41d10301")
        await self.get_from_blind(command, self.position_callback)

    ##################################################################################################
    ## CALLBACK METHODS ############################################################################
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
            await self.blind_disconnect()

    async def position_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get position", self.name)

        decimals = self.split_data(data)

        blindPos = (decimals[7] + (256 * decimals[8])) / 10
        # blindPos = decimals[6]
        _LOGGER.debug("%s: Blind position is %s", self.name, blindPos)
        self._current_cover_position = blindPos
        self._moving = 0
        await self.blind_disconnect()

    async def set_position_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ):
        """Wait for response from the blind and disconnects. Used to keep alive."""
        _LOGGER.debug(
            "%s: Disconnecting based on response %s", self.name, self.split_data(data)
        )
        await self.blind_disconnect()

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
                _LOGGER.debug("%s: Sending the command", self.name)
                await self._client.write_gatt_char(UUID, command)
            except BleakError as e:
                _LOGGER.error("%s: Send Command error: %s", self.name, e)
                raise RuntimeError(e) from e

    # Creates the % open/closed hex command
    def hex_convert(self, userPercent):
        """Convert the blind position."""
        callStr = "ff78ea41bf03"
        outHex = round((((100 - userPercent) * 10) % 256), 1)
        if outHex == 256:
            outHex = 0
        if userPercent > 74.4:
            groupStr = "00"
        elif userPercent > 48.8:
            groupStr = "01"
        elif userPercent > 23.2:
            groupStr = "02"
        elif userPercent >= 0:
            groupStr = "03"
        hexVal = str(format(int(outHex), "#04x"))

        return callStr + hexVal[2:] + groupStr

    def return_hex_bytearray(self, x):
        """make sure we print ascii symbols as hex"""
        return "".join(
            [type(x).__name__, "('", *["\\x" + "{:02x}".format(i) for i in x], "')"]
        )

    def split_data(self, data):
        """Split the byte response into decimal."""
        data_hex = self.return_hex_bytearray(data)
        customdecode = str(data_hex)
        customdecodesplit = customdecode.split("\\x")
        response = ""
        decimals = []

        x = 1
        while x < len(customdecodesplit):
            resp = customdecodesplit[x][0:2]
            response += resp
            decimals.append(int(resp, 16))
            x += 1

        _LOGGER.debug("%s: As byte:%s", self.name, data_hex)
        _LOGGER.debug("%s: As string:%s", self.name, response)
        _LOGGER.debug("%s: As decimals:%s", self.name, decimals)
        return decimals
