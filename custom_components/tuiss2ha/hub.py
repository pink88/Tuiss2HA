"""Tuiss Smartview and Blinds2go BLE Home, for connecting more than 1 blind"""
from __future__ import annotations

import asyncio
import random
import bleak_retry_connector
from homeassistant.components import bluetooth
from bleak import BleakClient
import logging

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant


class Hub:
    """Tuiss BLE hub"""

    manufacturer = "Tuiss and Blinds2go"

    def __init__(self, hass: HomeAssistant, host: str, name: str) -> None:
        """Init dummy hub."""
        self._host = host
        self._hass = hass
        self._name = name
        self._id = host.lower()
        self.rollers = [
            TuissBlind(self._host, self._name, self)
        ]
        self.online = True

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    async def test_connection(self) -> bool:
        """Test connectivity to the Dummy hub is OK."""
        await asyncio.sleep(1)
        return True


class TuissBlind:
    """Tuiss Blind object"""

    def __init__(self, mac: str, name: str, hub: hub) -> None:
        """Init tuiss blind"""
        self._id = mac #also the mac address
        self._mac = mac
        self.name = name
        self.hub = hub
        self.model = "Tuiss"
        self._ble_device = bluetooth.async_ble_device_from_address(self.hub._hass, self._mac, connectable=True)
        self._client = BleakClient(self._ble_device)
        _LOGGER.info("BLEDevice: %s", self._ble_device)
        self._callbacks = set()
        self._retry_count = 0
        self._max_retries = 10


    @property
    def blind_id(self) -> str:
        """Return ID for roller."""
        return self._id


    @property
    def online(self) -> float:
        """Roller is online."""
        # The dummy roller is offline about 10% of the time. Returns True if online,
        # False if offline.
        return True




    #Attempt Connections
    async def attempt_connection(self):
        while ((not self._client.is_connected) and self._retry_count <= self._max_retries):
            _LOGGER.info("Attempting Connection to blind. Rety count: %s", self._retry_count)
            await self.blind_connect()
        
        if self._retry_count >self._max_retries:
            _LOGGER.info("Connection Failed too many times")
            self._retry_count = 0



    #Connect
    async def blind_connect(self):
        try:
            await self._client.connect(timeout=30)
            if (self._client.is_connected):
                    _LOGGER.info("BleakClient Connected")
        except Exception as err:
            self._retry_count += 1
            _LOGGER.info("Connection Failed: %s",err)
            


    # Disconnect
    async def blind_disconnect(self):
        if self._client.is_connected:
            _LOGGER.info("BleakClient Disconnected")
            self._retry_count = 0
            await self._client.disconnect()



    # Creates the % open/closed hex command
    def hex_convert(self, userPercent):
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

        _LOGGER.info("BleakClient connected state is %s",self._client.is_connected)
        if self._client.is_connected:
            try:
                _LOGGER.info("Sending the command")
                await self._client.write_gatt_char(UUID, command)
            except Exception as e:
                _LOGGER.error(("Send Command error: %s",e))
                
            finally:
                await self.blind_disconnect()


    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)



    # Set the position and send to be run
    async def set_position(self, userPercent) -> None:
        UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
        _LOGGER.info("Attempting to set position to: %s", userPercent)
        command = bytes.fromhex(self.hex_convert(userPercent))
        await self.send_command(UUID, command)

    # async def stop(self):
    #     UUID = "00010405-0405-0607-0809-0a0b0c0d1910"
    #     command = bytes.fromhex("ff78ea415f0301")
    #     await self.send_command(UUID, command)