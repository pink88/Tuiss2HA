"""Config flow for Tuiss2ha integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_BLIND_HOST, CONF_BLIND_NAME, DOMAIN
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BLIND_HOST): str,
        vol.Required(CONF_BLIND_NAME): str,
    }
)


# def name_from_discovery(discovery: SwitchBotAdvertisement) -> str:
#     """Get the name from a discovery."""
#     return f"{discovery.data['modelFriendlyName']} {short_address(discovery.address)}"




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
            errors["host"] = (
                "Your mac address must be in the format XX:XX:XX:XX:XX:XX"
            )
        except InvalidName:
            errors["name"] = "Your name must be longer than 0 characters"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            user_input["host"] = user_input["host"].upper()
            return self.async_create_entry(title=_title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_DATA_SCHEMA, user_input if user_input is not None else {}
            ),
            errors=errors,
        )


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    matches = re.search("^([A-F0-9]{2}:){5}[A-F0-9]{2}$", data["host"])
    if matches is None:
        raise InvalidHost

    if len(data["name"]) == 0:
        raise InvalidName

    try:
        hub = Hub(hass, data["host"], data["name"])
        await hub.blinds[0].get_blind_position()
        await hub.blinds[0].blind_disconnect()
    except:
        raise CannotConnect()

    return data["name"]







class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidName(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid device name."""
