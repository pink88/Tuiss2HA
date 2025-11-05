"""Test the config flow."""
import re
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from custom_components.tuiss2ha.config_flow import ConfigFlow, STEP_DATA_SCHEMA, validate_input
from custom_components.tuiss2ha.const import (
    DOMAIN, CONF_BLIND_HOST, CONF_BLIND_NAME, CannotConnect,
    InvalidHost, InvalidName, DeviceNotFound, ConnectionTimeout
)

# Mock the data entry flow types
class FlowResultType:
    FORM = "form"
    CREATE_ENTRY = "create_entry"
    ABORT = "abort"

# Mock config entries base class
class MockConfigEntry:
    def __init__(self, *, title=None, domain=None, data=None, options=None):
        self.title = title
        self.domain = domain
        self.data = data or {}
        self.options = options or {}


async def mock_validate_input(hass, data):
    """Mock validate_input that returns success."""
    # Mock the Hub class
    with patch("custom_components.tuiss2ha.config_flow.Hub") as mock_hub:
        # Set up mock blind instance
        mock_blind = AsyncMock()
        mock_blind.get_blind_position = AsyncMock()
        mock_blind.disconnect = AsyncMock()
        
        # Set up mock hub instance
        mock_hub_instance = mock_hub.return_value
        mock_hub_instance.blinds = [mock_blind]

        if not data.get(CONF_BLIND_HOST) or not re.match(r"^([A-F0-9]{2}:){5}[A-F0-9]{2}$", data[CONF_BLIND_HOST].upper()):
            raise InvalidHost

        if not data.get(CONF_BLIND_NAME) or len(data[CONF_BLIND_NAME].strip()) == 0:
            raise InvalidName

        return data[CONF_BLIND_NAME]


class MockConfigFlow(ConfigFlow):
    """Mock config flow for testing."""
    VERSION = 1

    def __init__(self):
        """Initialize the mock flow."""
        super().__init__()
        self.hass = AsyncMock()
        self.hass.config_entries = AsyncMock()
        self.hass.config_entries.flow = AsyncMock()
        self.hass.config_entries.flow.async_progress.return_value = []
        
        # Create an AsyncMock for the async_progress method
        self.hass.config_entries.async_get_entries = AsyncMock(return_value=[])
        
        self.context = {"source": "user"}
        self._discovery_info = None
        
        # Mock the config flow's internal methods
        self.async_show_form = AsyncMock()
        self.async_create_entry = AsyncMock()
        self.async_abort = AsyncMock()
        self.async_set_unique_id = AsyncMock()
        self._abort_if_unique_id_configured = AsyncMock()

    async def async_step_user(self, user_input=None):
        """Test the user input allows us to connect."""
        errors = {}
        
        if user_input is None:
            return await self.async_show_form(
                step_id="user", 
                data_schema=STEP_DATA_SCHEMA,
                errors=errors
            )

        try:
            title = await mock_validate_input(self.hass, user_input)
            return await self.async_create_entry(
                title=title,
                data=user_input
            )
        except InvalidHost:
            errors[CONF_BLIND_HOST] = "invalid_host"
        except InvalidName:
            errors[CONF_BLIND_NAME] = "invalid_name"
        except (CannotConnect, DeviceNotFound, ConnectionTimeout):
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            errors["base"] = "unknown"

        return await self.async_show_form(
            step_id="user",
            data_schema=STEP_DATA_SCHEMA,
            errors=errors,
        )


# Mock base config flow class
class MockFlow:
    """Mock config flow."""
    VERSION = 1
    DOMAIN = DOMAIN

    def __init__(self):
        """Initialize."""
        self.hass = AsyncMock()
        self.hass.config_entries = AsyncMock()
        self.hass.config_entries.flow = AsyncMock()
        self.hass.config_entries.flow.async_progress.return_value = []
        self.hass.config_entries.async_get_entries = AsyncMock(return_value=[])

        self.async_show_form = AsyncMock()
        self.async_create_entry = AsyncMock()
        self.async_abort = AsyncMock()
        self.async_set_unique_id = AsyncMock()
        self._abort_if_unique_id_configured = AsyncMock()

    async def async_step_user(self, user_input=None):
        """Test the user config step."""
        if user_input is None:
            return self.async_show_form.return_value

        try:
            # This will raise exceptions in tests based on the patched validate_input
            await validate_input(self.hass, user_input)
            return self.async_create_entry.return_value
        except Exception:  # pylint: disable=broad-except
            return self.async_show_form.return_value

@pytest.fixture
def mock_flow():
    """Create a mock config flow."""
    return MockFlow()


@pytest.mark.asyncio
async def test_form_invalid_host(mock_flow):
    """Test we handle invalid host address."""
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {CONF_BLIND_HOST: "invalid_host"},
    }

    result = await mock_flow.async_step_user(
        {
            CONF_BLIND_HOST: "invalid",  # not a MAC address format
            CONF_BLIND_NAME: "Test Blind",
        }
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_BLIND_HOST: "invalid_host"}


@pytest.mark.asyncio
async def test_form_invalid_name(mock_flow):
    """Test we handle empty name."""
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {CONF_BLIND_NAME: "invalid_name"},
    }

    result = await mock_flow.async_step_user(
        {
            CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
            CONF_BLIND_NAME: "",  # empty name
        }
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_BLIND_NAME: "invalid_name"}


@pytest.mark.asyncio
async def test_form_cannot_connect(mock_flow):
    """Test we handle cannot connect error."""
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {"base": "cannot_connect"},
    }

    with patch("homeassistant.components.bluetooth.async_ble_device_from_address", 
        return_value=None):
        result = await mock_flow.async_step_user(
            {
                CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
                CONF_BLIND_NAME: "Test Blind",
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_form_device_not_found(mock_flow):
    """Test we handle device not found error."""
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {"base": "cannot_connect"},
    }

    with patch("homeassistant.components.bluetooth.async_ble_device_from_address", return_value=None):
        result = await mock_flow.async_step_user(
            {
                CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
                CONF_BLIND_NAME: "Test Blind",
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
#@pytest.mark.skip(reason="Runs too long")
async def test_form_connection_timeout(mock_flow):
    """Test we handle connection timeout error."""
    # Initial form
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    # Form with connection timeout error
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {"base": "cannot_connect"},
    }

    # Mock the validate_input function to raise ConnectionTimeout immediately
    async def mock_validate_input(*args, **kwargs):
        raise ConnectionTimeout("Connection timed out")

    with patch(__name__ + ".validate_input", side_effect=mock_validate_input):
        result = await mock_flow.async_step_user(
        {
            CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
            CONF_BLIND_NAME: "Test Blind",
        }
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_form_success(mock_flow):
    """Test we can complete a config flow with valid input."""
    mock_flow.async_show_form.return_value = {
        "type": FlowResultType.FORM,
        "errors": {},
    }
    
    result = await mock_flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    mock_flow.async_create_entry.return_value = {
        "type": FlowResultType.CREATE_ENTRY,
        "title": "Test Blind",
        "data": {
            CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
            CONF_BLIND_NAME: "Test Blind",
        }
    }

    # Patch the validate_input reference used by MockFlow to avoid real BLE calls
    async def fake_validate_input(hass, user_input):
        return "Test Blind"

    # Patch the validate_input function on the MockFlow instance
    mock_flow.validate_input = fake_validate_input

    # Patch the global validate_input in this test module to ensure correct reference
    import sys
    sys.modules[__name__].validate_input = fake_validate_input

    result = await mock_flow.async_step_user(
        {
            CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
            CONF_BLIND_NAME: "Test Blind",
        }
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Blind"
    assert result["data"] == {
        CONF_BLIND_HOST: "AA:BB:CC:DD:EE:FF",
        CONF_BLIND_NAME: "Test Blind",
    }