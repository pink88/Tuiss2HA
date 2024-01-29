"""Tuiss Smartview and Blinds2go BLE Home."""

from __future__ import annotations

import asyncio
import logging

from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    BATTERY_NOTIFY_CHARACTERISTIC,
    UUID,
)

_LOGGER = logging.getLogger(__name__)
hass = HomeAssistant


class Hub:
    """Tuiss BLE hub."""

    manufacturer = "Tuiss and Blinds2go"

    def __init__(self, hass: HomeAssistant, host: str, name: str) -> None:
        """Init dummy hub."""
        self._host = host
        self._hass = hass
        self._name = name
        self._id = host.lower()
        self.blinds = [TuissBlind(self._host, self._name, self)]

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id


class TuissBlind:
    """Tuiss Blind object."""

    def __init__(self, mac: str, name: str, hub: Hub) -> None:
        """Init tuiss blind."""
        self._id = mac  # also the mac address
        self._mac = mac
        self.name = name
        self.hub = hub
        self.model = "Tuiss"
        self._ble_device = bluetooth.async_ble_device_from_address(
            self.hub._hass, self._mac, connectable=True
        )
        self._client: BleakClientWithServiceCache | None = None
        _LOGGER.debug("BLEDevice: %s", self._ble_device)
        self._callbacks = set()
        self._retry_count = 0
        self._max_retries = 10
        self._battery_status = False

    @property
    def blind_id(self) -> str:
        """Return ID for blind."""
        return self._id

    # Attempt Connections
    async def attempt_connection(self):
        """Attempt to connect to the blind."""

        # check if the device not loaded at boot and retry a connection
        rediscover_attempts = 0
        while self._ble_device is None and rediscover_attempts < 4:
            _LOGGER.debug("Unable to find device %s, attempting rediscovery", self.name)
            self._ble_device = bluetooth.async_ble_device_from_address(
                self.hub._hass, self._mac, connectable=True
            )
            rediscover_attempts += 1
        if self._ble_device is None:
            _LOGGER.debug(
                "Cannot find the device %s. Check your bluetooth adapters and proxies",
                self.name,
            )

        while (
            self._client is None or not self._client.is_connected
        ) and self._retry_count <= self._max_retries:
            _LOGGER.debug(
                "%s %s: Attempting Connection to blind. Rety count: %s",
                self.name,
                self._ble_device,
                self._retry_count,
            )
            await self.blind_connect()

        if self._retry_count > self._max_retries:
            _LOGGER.debug("%s: Connection Failed too many times", self.name)
            self._retry_count = 0

    # Connect
    async def blind_connect(self):
        """Connect to the blind."""
        client: BleakClientWithServiceCache = await establish_connection(
            client_class=BleakClientWithServiceCache,
            device=self._ble_device,
            name=self._mac,
            use_services_cache=True,
            max_attempts=self._max_retries,
            ble_device_callback=lambda: self._device,
        )
        _LOGGER.debug("%s: Connected to blind", self.name)
        # await self._client.connect(timeout=30)
        self._client = client

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

    # Send the data
    async def send_command(self, UUID, command, disconnect=True):
        """Send the command to the blind."""
        _LOGGER.debug(
            "%s (%s) connected state is %s",
            self.name,
            self._ble_device,
            self._client.is_connected,
        )
        if self._client.is_connected:
            try:
                _LOGGER.debug("%s: Sending the command", self.name)
                await self._client.write_gatt_char(UUID, command)
            except Exception as e:
                _LOGGER.error(("%s: Send Command error: %s", self.name, e))

            finally:
                if disconnect:
                    await self.blind_disconnect()

    def register_callback(self, callback) -> None:
        """Register callback, called when blind changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    async def set_position(self, userPercent) -> None:
        """Set the position of the blind converting from HA to Tuiss first."""
        _LOGGER.debug("%s: Attempting to set position to: %s", self.name, userPercent)
        command = bytes.fromhex(self.hex_convert(userPercent))
        await self.send_command(UUID, command)

    async def battery_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get battery status", self.name)

        decimals = self.split_data(data)

        if decimals[4] == 210:
            if len(decimals) == 5:
                _LOGGER.debug(
                    "%s: Please charge device", self.name
                )  # think its based on the length of the response? ff010203d2 (bad) vs ff010203d202e803 (good)
                self._battery_status = True
            elif decimals[5] > 10:
                _LOGGER.debug(
                    "%s: Please charge device", self.name
                )  # think its based on the length of the response? ff010203d2 (bad) vs ff010203d202e803 (good)
                self._battery_status = True
            elif decimals[5] <= 10:
                _LOGGER.debug("%s: Battery is good", self.name)
                self._battery_status = False
            else:
                _LOGGER.debug("%s: Battery logic is wrong", self.name)
                self._battery_status = None
            await self.blind_disconnect()

    def return_hex_bytearray(self, x):
        """make sure we print ascii symbols as hex"""
        return ''.join([type(x).__name__, "('",
                    *['\\x'+'{:02x}'.format(i) for i in x], "')"])

    async def position_callback(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.debug("%s: Attempting to get position", self.name)

        decimals = self.split_data(data)

        blindPos = (decimals[-4] + (decimals[-3] * 256)) / 10
        _LOGGER.debug("%s: Blind position is %s", self.name, blindPos)
        self._current_cover_position = blindPos

        await self.blind_disconnect()


    def split_data(self, data):
        """Split the byte response into decimal."""
        customdecode = str(self.return_hex_bytearray(data))
        customdecodesplit = customdecode.split("\\x")
        response = ""
        decimals = []

        x = 1
        while x < len(customdecodesplit):
            resp = customdecodesplit[x][0:2]
            response += resp
            decimals.append(int(resp, 16))
            x += 1

        _LOGGER.debug("%s: As byte:%s", self.name, data)
        _LOGGER.debug("%s: As string:%s", self.name, response)
        _LOGGER.debug("%s: As decimals:%s", self.name, decimals)
        return decimals

    async def get_from_blind(self, command, callback) -> None:
        """Get the battery state from the blind as good or bad."""

        # connect to the blind first
        await self.attempt_connection()
        await self._client.start_notify(BATTERY_NOTIFY_CHARACTERISTIC, callback)
        await self.send_command(UUID, command, False)
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
