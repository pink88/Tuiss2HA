"""Tuiss2HA integration."""
from __future__ import annotations

import logging
import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothScanningMode,
    async_register_callback,
)
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

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



PLATFORMS: list[str] = ["cover", "binary_sensor", "sensor", "button", "select"]
_LOGGER = logging.getLogger(__name__)

SERVICE_SAVE_PRESET = "save_preset"
SERVICE_SAVE_CURRENT_AS_PRESET = "save_current_position_as_preset"
SERVICE_DELETE_PRESET = "delete_preset"
SERVICE_APPLY_PRESET = "apply_preset"

def _normalize_preset_name(value) -> str:
    """Strip and reject empty/blank preset names."""
    if not isinstance(value, str):
        raise vol.Invalid("preset name must be a string")
    stripped = value.strip()
    if not stripped:
        raise vol.Invalid("Preset name cannot be empty or whitespace only")
    return stripped


def _normalize_preset_position(value) -> float:
    """Coerce to float bound 0..100; preserves 0.1% hardware resolution."""
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise vol.Invalid(f"position must be a number, got {value!r}") from exc
    if not 0 <= v <= 100:
        raise vol.Invalid("position must be between 0 and 100")
    return v


_PRESET_NAME_SCHEMA = vol.All(_normalize_preset_name, vol.Length(min=1, max=64))
_PRESET_POSITION_SCHEMA = _normalize_preset_position

SAVE_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("name"): _PRESET_NAME_SCHEMA,
        vol.Required("position"): _PRESET_POSITION_SCHEMA,
    }
)
SAVE_CURRENT_AS_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("name"): _PRESET_NAME_SCHEMA,
    }
)
DELETE_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("name"): _PRESET_NAME_SCHEMA,
    }
)
APPLY_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("name"): _PRESET_NAME_SCHEMA,
    }
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuiss2HA from a config entry."""
    hub = Hub(hass, entry.data[CONF_BLIND_HOST], entry.data[CONF_BLIND_NAME])

    for blind in hub.blinds:

        # Load timers
        await blind.async_load_timers()

        # Load position presets (HA-side named positions)
        await blind.async_load_presets()
        
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

        # Seed blind state from options at boot. update_listener only fires on
        # option CHANGES — without seeding here, _blind_speed stays None until
        # user touches the option, which makes set_speed() raise UnboundLocalError
        # (no default case in match statement) and TuissBlindSpeedSensor read None.
        blind._blind_speed = entry.options.get(OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED)
        blind._battery_check_days = entry.options.get(
            OPT_BATTERY_CHECK_DAYS, DEFAULT_BATTERY_CHECK_DAYS
        )
        blind._restart_attempts = entry.options.get(
            OPT_RESTART_ATTEMPTS, DEFAULT_RESTART_ATTEMPTS
        )

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

    # Register preset services once per HA process.
    _async_register_preset_services(hass)

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
            b.publish_updates()  # Notify sensors of the change
        except (AttributeError, TypeError) as e:
            _LOGGER.debug("Failed to apply battery_check_days to blind %s: %s", getattr(b, "name", "unknown"), e)

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
    blind_device.publish_updates()  # Notify sensors of the change

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


def _resolve_blind_from_entity_id(hass: HomeAssistant, entity_id: str):
    """Resolve a TuissBlind from a cover or preset-select entity_id, or None."""
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get(entity_id)
    if not entry or entry.platform != DOMAIN:
        return None
    unique_id = entry.unique_id or ""
    # Only cover/preset-select are valid preset-service targets.
    blind_id: str | None = None
    for suffix in ("_preset_select", "_cover"):
        if unique_id.endswith(suffix):
            blind_id = unique_id[: -len(suffix)]
            break
    if not blind_id:
        return None
    for hub in hass.data.get(DOMAIN, {}).values():
        if not isinstance(hub, Hub):
            continue
        for blind in hub.blinds:
            if blind.blind_id == blind_id:
                return blind
    return None


@callback
def _async_register_preset_services(hass: HomeAssistant) -> None:
    """Register preset services once per HA process."""
    if hass.services.has_service(DOMAIN, SERVICE_SAVE_PRESET):
        return

    async def _handle_save_preset(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        name = call.data["name"]
        position = call.data["position"]
        blind = _resolve_blind_from_entity_id(hass, entity_id)
        if not blind:
            raise HomeAssistantError(
                f"save_preset: cannot resolve a Tuiss blind for {entity_id}"
            )
        blind.presets[name] = float(position)
        await blind.async_save_presets()
        blind.publish_updates()
        _LOGGER.info(
            "%s: Saved preset %r at %s%%", blind.name, name, position
        )

    async def _handle_save_current_as_preset(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        name = call.data["name"]
        blind = _resolve_blind_from_entity_id(hass, entity_id)
        if not blind:
            raise HomeAssistantError(
                "save_current_position_as_preset: cannot resolve a Tuiss "
                f"blind for {entity_id}"
            )
        # Helper returns None when the live position has never been read;
        # surface that as an error so automations can branch.
        result = await blind.async_save_current_as_preset(name)
        if result is None:
            raise HomeAssistantError(
                f"{blind.name}: cannot save preset — current position is "
                "unknown. Move the blind once so its position is read, then "
                "try again."
            )

    async def _handle_delete_preset(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        name = call.data["name"]
        blind = _resolve_blind_from_entity_id(hass, entity_id)
        if not blind:
            raise HomeAssistantError(
                f"delete_preset: cannot resolve a Tuiss blind for {entity_id}"
            )
        if name not in blind.presets:
            raise HomeAssistantError(
                f"{blind.name}: preset {name!r} not found"
            )
        blind.presets.pop(name)
        await blind.async_save_presets()
        blind.publish_updates()
        _LOGGER.info("%s: Deleted preset %r", blind.name, name)

    async def _handle_apply_preset(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        name = call.data["name"]
        blind = _resolve_blind_from_entity_id(hass, entity_id)
        if not blind:
            raise HomeAssistantError(
                f"apply_preset: cannot resolve a Tuiss blind for {entity_id}"
            )
        # Helper raises HomeAssistantError on unknown preset.
        await blind.async_apply_preset(name)

    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_PRESET, _handle_save_preset, schema=SAVE_PRESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_CURRENT_AS_PRESET,
        _handle_save_current_as_preset,
        schema=SAVE_CURRENT_AS_PRESET_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_PRESET, _handle_delete_preset, schema=DELETE_PRESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_PRESET, _handle_apply_preset, schema=APPLY_PRESET_SCHEMA
    )
