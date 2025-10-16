"""Config flow for Tuiss2ha integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry, selector

from .const import (
    CONF_BLIND_HOST,
    CONF_BLIND_NAME,
    DOMAIN,
    OPT_RESTART_POSITION,
    OPT_RESTART_ATTEMPTS,
    DEFAULT_RESTART_ATTEMPTS,
    DEFAULT_RESTART_POSITION,
    SPEED_CONTROL_SUPPORTED_MODELS,
    OPT_BLIND_SPEED,
    DEFAULT_BLIND_SPEED,
    BLIND_SPEED_LIST,
    CannotConnect,
    InvalidHost,
    InvalidName,
    DeviceNotFound,
    ConnectionTimeout,
    OPT_FAVORITE_POSITION,
    DEFAULT_FAVORITE_POSITION,
)
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BLIND_HOST): str,
        vol.Required(CONF_BLIND_NAME): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Tuiss2HA."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_ASSUMED

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    def __init__(self) -> None:
        """Initialise a config flow"""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        # self._mac_code: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        host = user_input[CONF_BLIND_HOST].upper()

        _LOGGER.debug("Starting user initiated flow")
        # Check if a discovery flow is already in progress for this device
        for progress_flow in self.hass.config_entries.flow.async_progress():
            if (
                progress_flow["context"].get("source") == config_entries.SOURCE_BLUETOOTH
                and progress_flow["context"].get("unique_id") == host
            ):
                return self.async_abort(reason="already_configured_by_discovery")


        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        try:
            _title = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidHost:
            errors[CONF_BLIND_HOST] = "invalid_host"
        except InvalidName:
            errors[CONF_BLIND_NAME] = "invalid_name"
        except Exception as exc:
            _LOGGER.exception("Unexpected exception: %s", exc)
            errors["base"] = "unknown"
        else:
            _LOGGER.debug("Creating entry for %s", user_input[CONF_BLIND_HOST])
            user_input[CONF_BLIND_HOST] = user_input[CONF_BLIND_HOST].upper()
            return self.async_create_entry(title=_title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_DATA_SCHEMA, user_input if user_input is not None else {}
            ),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered bluetooth device: %s", discovery_info.as_dict())
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": discovery_info.address}
        self._discovery_info = discovery_info
        return await self.async_step_confirm()


    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        _LOGGER.debug("Ready to add the device %s", self._discovery_info.address)

        if user_input is not None:
            _LOGGER.debug(
                "Ready to add the device %s, %s",
                self._discovery_info.address,
                user_input[CONF_BLIND_NAME],
            )
            user_input[CONF_BLIND_HOST] = self._discovery_info.address
            _title = await validate_input(self.hass, user_input)

            _LOGGER.debug("Creating the entry for %s", user_input[CONF_BLIND_NAME])
            return self.async_create_entry(title=_title, data=user_input)

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_BLIND_NAME): str}),
            description_placeholders=self.context["title_placeholders"],
        )


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    matches = re.search("^([A-F0-9]{2}:){5}[A-F0-9]{2}$", data["host"])
    if matches is None:
        raise InvalidHost

    if len(data[CONF_BLIND_NAME]) == 0:
        raise InvalidName

    try:
        hub = Hub(hass, data[CONF_BLIND_HOST], data[CONF_BLIND_NAME])
        await hub.blinds[0].get_blind_position()
        await hub.blinds[0].disconnect()
    except DeviceNotFound:
        raise
    except ConnectionTimeout:
        raise
    except Exception as e:
        raise CannotConnect() from e

    return data[CONF_BLIND_NAME]


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tuiss options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage Tuiss options."""
        errors: dict[str, str] = {}
        hub: Hub | None = self.hass.data[DOMAIN].get(self.config_entry.entry_id)

        if not hub:
            # This should not happen, but handle it gracefully.
            return self.async_abort(reason="hub_not_found")

        blind_device = hub.blinds[0]

        if user_input is not None:
            # Check if the user is trying to change the speed while the blind is moving
            is_moving = blind_device._moving != 0
            current_speed = self.config_entry.options.get(
                OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED
            )
            new_speed = user_input.get(OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED)
            speed_has_changed = new_speed != current_speed

            if is_moving and speed_has_changed:
                errors["base"] = "blind_is_moving"
            else:
                return self.async_create_entry(title="", data=user_input)

        # Build the options form
        dr = device_registry.async_get(self.hass)
        model_type = ""
        for device in dr.devices.values():
            if self.config_entry.entry_id in device.config_entries:
                model_type = device.model
                break

        options_schema = {
            vol.Optional(
                OPT_RESTART_POSITION,
                default=self.config_entry.options.get(
                    OPT_RESTART_POSITION, DEFAULT_RESTART_POSITION
                ),
            ): bool,
            vol.Optional(
                OPT_RESTART_ATTEMPTS,
                default=self.config_entry.options.get(
                    OPT_RESTART_ATTEMPTS, DEFAULT_RESTART_ATTEMPTS
                ),
            ): int,
            vol.Required(
                OPT_FAVORITE_POSITION,
                default=self.config_entry.options.get(
                    OPT_FAVORITE_POSITION, DEFAULT_FAVORITE_POSITION
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100, step=1, mode="slider")
            ),
        }

        # Add speed control option only for supported models
        if model_type in SPEED_CONTROL_SUPPORTED_MODELS:
            options_schema[
                vol.Optional(
                    OPT_BLIND_SPEED,
                    default=self.config_entry.options.get(
                        OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED
                    ),
                )
            ] = selector.selector(
                {
                    "select": {
                        "multiple": False,
                        "options": BLIND_SPEED_LIST,
                        "mode": selector.SelectSelectorMode.DROPDOWN,
                    }
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema),
            errors=errors,
        )
