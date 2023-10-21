"""Config flow for Hello World integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

from .const import DOMAIN  # pylint:disable=unused-import
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host", default="XX:XX:XX:XX:XX:XX"): str,
        vol.Required("name", default="Name for device"): str
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hello World."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_ASSUMED

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                _title = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=_title, data=user_input)
            except InvalidName:
                errors["name"] = "Your name must be longer than 0 characters"
            except InvalidHost:
                errors["host"] = "Your host should be a valid MAC address in the format XX:XX:XX:XX:XX:XX"
            except Exception:  
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    
    if len(data["host"]) < 17:
        raise InvalidHost

    if len(data["name"]) == 0 :
        raise InvalidName

    return data["name"]


class InvalidName(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""