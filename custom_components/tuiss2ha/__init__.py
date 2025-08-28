"""Tuiss2HA integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothScanningMode,
    async_register_callback,
)
from homeassistant.const import CONF_ADDRESS, Platform

from .hub import Hub
from .const import DOMAIN,CONF_BLIND_HOST,CONF_BLIND_NAME, OPT_RESTART_POSITION, DEFAULT_RESTART_POSITION, OPT_RESTART_ATTEMPTS, DEFAULT_RESTART_ATTEMPTS, OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED, DeviceNotFound, ConnectionTimeout



PLATFORMS: list[str] = ["cover", "binary_sensor", "sensor", "button"]
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
            options={OPT_RESTART_POSITION: DEFAULT_RESTART_POSITION, OPT_RESTART_ATTEMPTS: DEFAULT_RESTART_ATTEMPTS, OPT_BLIND_SPEED: DEFAULT_BLIND_SPEED},
        )

        #only attempt to get the current position of the blind on boot if required. Required when using tuiss app or bluetooth remotes
        blind._position_on_restart = entry.options.get("blind_restart_position", False)
        _LOGGER.debug("Getting the blind position for %s if %s set TRUE",blind.name, blind._position_on_restart)

        if blind._position_on_restart:
            try:
                await blind.get_blind_position()
            except (DeviceNotFound, ConnectionTimeout) as e:
                raise ConfigEntryNotReady("Cannot connect to blind") from e

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    entry.async_on_unload(entry.add_update_listener(update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _async_discovered_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update RSSI on device discovery."""
        if adv := service_info.advertisement:
            hub.blinds[0].set_rssi(adv.rssi)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _async_discovered_device,
            BluetoothCallbackMatcher(address=entry.data[CONF_BLIND_HOST]),
            BluetoothScanningMode.PASSIVE,
        )
    )

    return True



async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    hub: Hub | None = hass.data[DOMAIN].get(entry.entry_id)
    if not hub:
        _LOGGER.warning("Could not find hub instance for entry %s", entry.entry_id)
        return

    blind_device = hub.blinds[0]

    # Retrieve the updated option value
    new_blind_speed = entry.options.get(OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED)
    current_blind_speed = blind_device._blind_speed

    # Check if the speed actually changed
    if new_blind_speed == current_blind_speed:
        _LOGGER.debug("Blind speed option did not change for %s", entry.entry_id)
        return

    _LOGGER.debug(
        "Blind speed changed from %s to %s",
        current_blind_speed,
        new_blind_speed,
    )
    # Update the speed on the blind object.
    blind_device._blind_speed = new_blind_speed

    # If the blind is currently moving, don't send the command.
    # The new speed will be used on the next operation.
    if blind_device._moving != 0:
        _LOGGER.info(
            "Blind '%s' is currently moving. Deferring speed change command.",
            blind_device.name,
        )
        return

    _LOGGER.info(
        "Options updated: Calling set_blind_speed for %s", entry.entry_id
    )
    await blind_device.set_speed()

    # The reload is handled by the options flow, so we don't need to do it here.


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
