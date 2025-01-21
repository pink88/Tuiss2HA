"""Config flow for Tuiss2ha integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_BLIND_HOST, CONF_BLIND_NAME, DOMAIN

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        try:
            _title = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["name"] = "Cannot connect"
        except InvalidHost:
            errors["host"] = "Your mac address must be in the format XX:XX:XX:XX:XX:XX"
        except InvalidName:
            errors["name"] = "Your name must be longer than 0 characters"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            user_input["host"] = user_input["host"].upper()
            return self.async_create_entry(title=_title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
        )


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    if len(data["host"]) < 17:
        raise InvalidHost

    if len(data["name"]) == 0:
        raise InvalidName

    return data["name"]


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidName(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid device name."""
