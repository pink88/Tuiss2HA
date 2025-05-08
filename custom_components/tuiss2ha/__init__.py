"""Tuiss2HA integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform

from .hub import Hub
from .const import DOMAIN,CONF_BLIND_HOST,CONF_BLIND_NAME, OPT_BLIND_ORIENTATION, DEFAULT_BLIND_ORIENTATION



PLATFORMS: list[str] = ["cover", "binary_sensor"]
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuiss2HA from a config entry."""
    hub = Hub(hass, entry.data[CONF_BLIND_HOST], entry.data[CONF_BLIND_NAME])

    for blind in hub.blinds:
        
        #add missing unique_ids TO DEPRICATE IN FUTURE RELEASE
        if entry.unique_id is None:
            _LOGGER.debug("Attempting to set UID for %s to %s", entry.data["name"],entry.data["host"])
            hass.config_entries.async_update_entry(entry, unique_id = entry.data["host"])
        else:
            _LOGGER.debug("Skipping, UID already set for %s.", entry.data["name"])
        
        if not entry.options:
            hass.config_entries.async_update_entry(
            entry,
            options={OPT_BLIND_ORIENTATION: DEFAULT_BLIND_ORIENTATION},
        )


        try:
            await blind.get_blind_position()
        except:
            raise ConfigEntryNotReady("Cannot connect to blind")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    entry.async_on_unload(entry.add_update_listener(update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    

    @callback
    def _async_discovered_device(service_info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange) -> None:
        """Subscribe to bluetooth changes."""
        _LOGGER.warning("New service_info: %s", service_info)
        ble_device = bluetooth.async_ble_device_from_address(hass, service_info.address)
        _LOGGER.warning("Got ble device " + str(ble_device))

        entry.async_on_unload(
        async_register_callback(
            hass,
            _async_discovered_device,
            BluetoothCallbackMatcher(address=entry.data[CONF_ADDRESS]),
            BluetoothScanningMode.ACTIVE,
        )
    )

    return True

async def update_listener(hass, entry):
    """Handle options update."""
    
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok