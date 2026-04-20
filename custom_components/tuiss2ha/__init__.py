"""Tuiss2HA integration."""
from __future__ import annotations

import logging
import asyncio

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
from homeassistant.helpers import device_registry as dr

from .hub import Hub
from .const import (
    DOMAIN,
    CONF_BLIND_HOST,
    CONF_BLIND_NAME,
    OPT_RESTART_POSITION,
    DEFAULT_RESTART_POSITION,
    OPT_RESTART_ATTEMPTS,
    DEFAULT_RESTART_ATTEMPTS,
    OPT_BLIND_SPEED,
    DEFAULT_BLIND_SPEED,
    OPT_BATTERY_CHECK_DAYS,
    DEFAULT_BATTERY_CHECK_DAYS,
    DeviceNotFound,
    ConnectionTimeout,
    SPEED_CONTROL_SUPPORTED_MODELS,
)



PLATFORMS: list[str] = ["cover", "binary_sensor", "sensor", "button"]
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuiss2HA from a config entry."""
    hub = Hub(hass, entry.data[CONF_BLIND_HOST], entry.data[CONF_BLIND_NAME])

    for blind in hub.blinds:
        
        # Clean up old duplicate network MAC connections from the device registry DEPRICATE IN FUTURE RELEASE
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, blind.blind_id)})
        if device:
            # Create a new set of connections, keeping only bluetooth and ensuring it's lowercase
            clean_connections = set()
            for conn_type, conn_val in device.connections:
                if conn_type == dr.CONNECTION_BLUETOOTH:
                    # Add the formatted (lowercase) bluetooth connection.
                    # The set will handle deduplication if there are already upper/lower case versions.
                    clean_connections.add((dr.CONNECTION_BLUETOOTH, dr.format_mac(conn_val)))

            if clean_connections != device.connections:
                _LOGGER.debug("Cleaning up device connections for %s", blind.name)
                device_registry.async_update_device(
                    device.id, new_connections=clean_connections
                )
        
        #add missing unique_ids TO DEPRICATE IN FUTURE RELEASE
        if entry.unique_id is None:
            _LOGGER.debug("Attempting to set UID for %s to %s", entry.data["name"],entry.data["host"])
            hass.config_entries.async_update_entry(entry, unique_id = entry.data["host"])
        else:
            _LOGGER.debug("Skipping, UID already set for %s.", entry.data["name"])
        
        if not entry.options:
            hass.config_entries.async_update_entry(
            entry,
            options={
                OPT_RESTART_POSITION: DEFAULT_RESTART_POSITION,
                OPT_RESTART_ATTEMPTS: DEFAULT_RESTART_ATTEMPTS,
                OPT_BLIND_SPEED: DEFAULT_BLIND_SPEED,
                OPT_BATTERY_CHECK_DAYS: DEFAULT_BATTERY_CHECK_DAYS,
            },
        )

        #only attempt to get the current position of the blind on boot if required. Required when using tuiss app or bluetooth remotes
        blind._position_on_restart = entry.options.get("blind_restart_position", False)
        _LOGGER.debug("Getting the blind position for %s if %s set TRUE",blind.name, blind._position_on_restart)

        if blind._position_on_restart:
            try:
                # Add a timeout to prevent hanging indefinitely waiting for bluetooth response
                await asyncio.wait_for(blind.get_blind_position(), timeout=15.0)
            except asyncio.TimeoutError:
                _LOGGER.warning("%s: Timeout getting blind position on startup. Retrying later.", blind.name)
                raise ConfigEntryNotReady("Timeout getting blind position - retrying later") from None
            except (DeviceNotFound, ConnectionTimeout) as e:
                raise ConfigEntryNotReady("Cannot connect to blind") from e
            except Exception as e:
                _LOGGER.warning("%s: Error getting blind position on startup: %s. Retrying later.", blind.name, e)
                raise ConfigEntryNotReady(f"Error getting blind position: {e}") from e

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

    # Apply battery check days option to all blinds immediately so changes take effect
    battery_days = entry.options.get(OPT_BATTERY_CHECK_DAYS, DEFAULT_BATTERY_CHECK_DAYS)
    for b in hub.blinds:
        try:
            b._battery_check_days = battery_days
        except Exception:
            _LOGGER.debug("Failed to apply battery_check_days to blind %s", getattr(b, "name", "unknown"))

    # Retrieve the updated option value for speed
    new_blind_speed = entry.options.get(OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED)
    current_blind_speed = blind_device._blind_speed

    # If the blind model does not support speed control, ignore speed option changes
    if blind_device.model not in SPEED_CONTROL_SUPPORTED_MODELS:
        _LOGGER.debug(
            "Model %s does not support speed control; ignoring blind_speed option for %s",
            blind_device.model,
            entry.entry_id,
        )
        return

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
