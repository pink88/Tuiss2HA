"""Config flow for Tuiss2ha integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.helpers import device_registry, selector
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak


from .const import (
    CONF_BLIND_HOST,
    CONF_BLIND_NAME,
    DOMAIN,
    OPT_BLIND_ORIENTATION,
    DEFAULT_BLIND_ORIENTATION,
    OPT_RESTART_POSITION,
    OPT_RESTART_ATTEMPTS,
    DEFAULT_RESTART_ATTEMPTS,
    DEFAULT_RESTART_POSITION,
    SPEED_CONTROL_SUPPORTED_MODELS,
    OPT_BLIND_SPEED,
    DEFAULT_BLIND_SPEED,
    BLIND_SPEED_LIST
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
        self._discovery_info: BluetoothServiceInfoBleak | BLEDevice | None = None
        # self._mac_code: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        await self.async_set_unique_id(user_input[CONF_BLIND_HOST])
        self._abort_if_unique_id_configured()

        try:
            _title = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors[CONF_BLIND_NAME] = "Cannot connect"
        except InvalidHost:
            errors[CONF_BLIND_HOST] = (
                "Your mac address must be in the format XX:XX:XX:XX:XX:XX"
            )
        except InvalidName:
            errors[CONF_BLIND_NAME] = "Your name must be longer than 0 characters"
        except Exception:
            _LOGGER.exception("Unexpected exception")
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
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Discovered bluetooth device: %s", discovery_info.as_dict())
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": discovery_info.address}
        self._discovery_info = discovery_info
        return await self.async_step_confirm()


    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
        await hub.blinds[0].blind_disconnect()
    except:
        raise CannotConnect()

    return data[CONF_BLIND_NAME]


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tuiss options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Tuiss options."""
        
        dr = device_registry.async_get(self.hass)
        model_type = ""
        _LOGGER.debug("Options flow, config entry: %s",self.config_entry.entry_id)

        for device in dr.devices.values():
            if self.config_entry.entry_id in device.config_entries:
                model_type = device.model
                break
        _LOGGER.debug("Options flow, model_type %s",model_type)    
        

        if user_input is not None:
            # Update common entity options for all other entities.
            return self.async_create_entry(title="", data=user_input)

        options: dict[vol.Optional, Any] = dict()
            
        options[vol.Optional(
                OPT_BLIND_ORIENTATION,
                default=self.config_entry.options.get(
                    OPT_BLIND_ORIENTATION, DEFAULT_BLIND_ORIENTATION
                ),
            )] = bool
        options[vol.Optional(
                OPT_RESTART_POSITION,
                default=self.config_entry.options.get(
                    OPT_RESTART_POSITION, DEFAULT_RESTART_POSITION
                ),
            )] = bool
        options[vol.Optional(
                OPT_RESTART_ATTEMPTS,
                default=self.config_entry.options.get(
                    OPT_RESTART_ATTEMPTS, DEFAULT_RESTART_ATTEMPTS
                ),
            )] = int
        #MAKE AN OPTION FOR SOME DEVICES AS APPLICABLE
        if model_type in SPEED_CONTROL_SUPPORTED_MODELS:
            _LOGGER.debug("Found model_type for %s",self.config_entry.entry_id)
            options[vol.Optional(
                OPT_BLIND_SPEED,
                default=self.config_entry.options.get(
                    OPT_BLIND_SPEED, DEFAULT_BLIND_SPEED
                ),
            )] = selector.selector({
                "select": {
                    "multiple": False, 
                    "options": BLIND_SPEED_LIST,
                    "mode": selector.SelectSelectorMode.DROPDOWN 
                }
            })

        return self.async_show_form(step_id="init", data_schema=vol.Schema(options))


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidName(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid device name."""
