# tests/conftest.py
import sys
from unittest.mock import MagicMock, AsyncMock
import pytest

@pytest.fixture
def mock_hub(mock_hass):
    """Provide a fake hub with a single TuissBlind-like object for cover tests."""
    # Create a minimal object that matches the TuissBlind interface used by the cover
    blind = MagicMock()
    blind.async_move_cover = AsyncMock()
    blind.stop = AsyncMock()
    blind._moving = 0
    blind._current_cover_position = 0
    blind._client = None
    blind._is_stopping = False
    blind.name = "Test Blind"
    blind.model = "TB-01"

    hub = MagicMock()
    hub.blinds = [blind]
    return hub

# This hook is run by pytest before test collection begins.
def pytest_sessionstart(session):
    """
    Mocks the Home Assistant modules required by the integration.
    This allows tests to be run standalone without a HA installation.
    """
    # Create a dummy base class for all entities. This is crucial to solve the
    # "metaclass conflict" error when a class inherits from multiple mocked
    # base classes (e.g., CoverEntity and RestoreEntity).
    class MockEntity:
        pass

    # Create mock versions of the HA entity base classes.
    # All of them will inherit from our single MockEntity.
    mock_entity_classes = {
        "RestoreEntity": type("RestoreEntity", (MockEntity,), {}),
        "CoverEntity": type("CoverEntity", (MockEntity,), {}),
        "SensorEntity": type("SensorEntity", (MockEntity,), {}),
        "BinarySensorEntity": type("BinarySensorEntity", (MockEntity,), {}),
        "ButtonEntity": type("ButtonEntity", (MockEntity,), {}),
    }

    # Create a mock for the 'homeassistant' root module
    sys.modules["homeassistant"] = MagicMock()

    # Mock the 'homeassistant.helpers.restore_state' module
    sys.modules["homeassistant.helpers.restore_state"] = MagicMock(**mock_entity_classes)

    # Mock the 'homeassistant.components' parent module as a real module object
    import types
    components_module = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components_module

    # Mock the individual component modules, injecting the mock entity classes
    # and any other required attributes. Provide a mocked 'cover' module as well.
    sys.modules["homeassistant.components.sensor"] = MagicMock(**mock_entity_classes)
    sys.modules["homeassistant.components.binary_sensor"] = MagicMock(**mock_entity_classes)
    sys.modules["homeassistant.components.button"] = MagicMock(**mock_entity_classes)
    sys.modules["homeassistant.components.cover"] = MagicMock(**mock_entity_classes)

    # Mock other required modules that don't contain entity base classes
    import types

    # Create mock for data_entry_flow first since it's needed by config_entries
    class FlowResultType:
        FORM = "form"
        CREATE_ENTRY = "create_entry"
        ABORT = "abort"

    class FlowResult(dict):
        pass

    sys.modules["homeassistant.data_entry_flow"] = types.SimpleNamespace(
        FlowResultType=FlowResultType,
        FlowResult=FlowResult,
    )

    other_modules = [
        "homeassistant.components.bluetooth",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.config_validation",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_platform",
    ]
    for module_name in other_modules:
        if module_name in sys.modules:
            continue
        # Provide a real HomeAssistantError class for the exceptions module so tests can raise it
        if module_name == "homeassistant.exceptions":
            # Create a HomeAssistantError that accepts HA-style translation kwargs
            class HomeAssistantError(Exception):
                def __init__(self, *args, **kwargs):
                    # If translation kwargs are provided, create a readable message
                    if "translation_key" in kwargs:
                        key = kwargs.get("translation_key")
                        placeholders = kwargs.get("translation_placeholders")
                        msg = f"{key}: {placeholders}"
                    elif args:
                        msg = args[0]
                    else:
                        msg = ""
                    super().__init__(msg)

            ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
            sys.modules[module_name] = types.SimpleNamespace(
                HomeAssistantError=HomeAssistantError,
                ConfigEntryNotReady=ConfigEntryNotReady,
            )
        else:
            sys.modules[module_name] = MagicMock()

@pytest.fixture
def mock_hass():
    """A mock Home Assistant instance for testing."""
    return MagicMock()