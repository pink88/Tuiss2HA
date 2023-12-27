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

from .const import DOMAIN

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
        self.blinds = [
            TuissBlind(self._host, self._name, self)
        ]
        self.online = True

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id



class TuissBlind:
    """Tuiss Blind object."""

    def __init__(self, mac: str, name: str, hub: Hub) -> None:
        """Init tuiss blind."""
        self._id = mac #also the mac address
        self._mac = mac
        self.name = name
        self.hub = hub
        self.model = "Tuiss"
        self._ble_device = bluetooth.async_ble_device_from_address(self.hub._hass, self._mac, connectable=True)
        self._client: BleakClientWithServiceCache | None = None
        _LOGGER.info("BLEDevice: %s", self._ble_device)
        self._callbacks = set()
        self._retry_count = 0
        self._max_retries = 10
        self._battery_status = "good"


    @property
    def blind_id(self) -> str:
        """Return ID for blind."""
        return self._id


    @property
    def online(self) -> float:
        """Blind is online."""
        # The dummy blind is offline about 10% of the time. Returns True if online,
        # False if offline.
        return True

    @property
    def battery_status(self) -> int:
        """Battery level as a percentage."""
        return self._battery_status



    #Attempt Connections
    async def attempt_connection(self):
        """Attempt to connect to the blind."""

        #check if the device not loaded at boot and retry a connection
        rediscover_attempts = 0
        while (self._ble_device is None and rediscover_attempts <4):
            _LOGGER.info("Unable to find device %s, attempting rediscovery", self.name)
            self._ble_device = bluetooth.async_ble_device_from_address(self.hub._hass, self._mac, connectable=True)
            rediscover_attempts+=1
        if self._ble_device is None:
            _LOGGER.info("Cannot find the device %s. Check your bluetooth adapters and proxies",self.name)


        while ((self._client is None or not self._client.is_connected) and self._retry_count <= self._max_retries):
            _LOGGER.info("%s %s: Attempting Connection to blind. Rety count: %s", self.name, self._ble_device, self._retry_count)
            await self.blind_connect()

        if self._retry_count >self._max_retries:
            _LOGGER.info("%s: Connection Failed too many times", self.name)
            self._retry_count = 0



    #Connect
    async def blind_connect(self):
        """Connect to the blind."""
        client: BleakClientWithServiceCache = await establish_connection(
            client_class = BleakClientWithServiceCache,
            device = self._ble_device,
            name = self._mac,
            use_services_cache=True,
            max_attempts=self._max_retries,
            ble_device_callback=lambda: self._device,
        )
        _LOGGER.info("%s: Connected to blind", self.name)
        #await self._client.connect(timeout=30)
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
    async def send_command(self, UUID, command):
        """Send the command to the blind."""
        _LOGGER.info("%s (%s) connected state is %s",self.name, self._ble_device,self._client.is_connected)
        if self._client.is_connected:
            try:
                _LOGGER.info("%s: Sending the command",self.name)
                await self._client.write_gatt_char(UUID, command)
            except Exception as e:
                _LOGGER.error(("%s: Send Command error: %s",self.name,e))

            finally:
                await self.blind_disconnect()


    def register_callback(self, callback) -> None:
        """Register callback, called when blind changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)



    # Set the position and send to be run
    async def set_position(self, userPercent) -> None:
        """Set the position of the blind converting from HA to Tuiss first."""
        UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
        _LOGGER.info("%s: Attempting to set position to: %s", self.name,userPercent)
        command = bytes.fromhex(self.hex_convert(userPercent))
        await self.send_command(UUID, command)




    # Waits and handles the response code from the battery and records to sensor
    async def battery_callback(self, data: bytearray):
        """Wait for response from the blind and updates entity status."""
        _LOGGER.info("%s: Attempting to get battery status", self.name)

        customdecode = str(data)
        customdecodesplit = customdecode.split('\\x')
        response = ''
        decimals = []

        x = 1
        while x < len(customdecodesplit):
            resp = customdecodesplit[x][0:2]
            response += resp
            decimals.append(int(resp,16))
            x+=1

        _LOGGER.info("%s: As byte:%s", self.name, data)
        _LOGGER.info("%s: As string:%s", self.name, response)
        _LOGGER.info("%s: As decimals:%s", self.name, decimals)

        if decimals[4] == 210:
            if  len(decimals) < 8:
                _LOGGER.info("%s: Please charge device",self.name) #think its based on the length of the response? ff010203d2 (bad) vs ff010203d202e803 (good)
                self.battery_status = True
            elif len(decimals) == 8:
                _LOGGER.info("%s: Battery is good",self.name)
                self._battery_status = False
            else:
                _LOGGER.info("%s: Battery logic is wrong",self.name)
            await self.blind_disconnect()


    # Get information on the battery status good or needs to be charged
    async def get_battery_status(self) -> None:
        """Get the battery state from the blind as good or bad."""
        UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
        command = bytes.fromhex("ff78ea41f00301")
        await self._client.start_notify(17,self.battery_callback)
        await self.send_command(UUID, command)
        while self._client.is_connected:
            await asyncio.sleep(1)


    #hass.services.register(DOMAIN,"get_battery_status",get_battery)



    # async def stop(self):
    #     UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
    #     command = bytes.fromhex("ff78ea415f0301")
    #     await self.send_command(UUID, command)