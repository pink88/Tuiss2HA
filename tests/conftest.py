# tests/conftest.py
import sys
from unittest.mock import MagicMock
import pytest

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
        "SensorEntity": type("SensorEntity", (MockEntity,), {}),
        "BinarySensorEntity": type("BinarySensorEntity", (MockEntity,), {}),
        "ButtonEntity": type("ButtonEntity", (MockEntity,), {}),
    }

    # Create a mock for the 'homeassistant' root module
    sys.modules["homeassistant"] = MagicMock()

    # Mock the 'homeassistant.helpers.restore_state' module
    sys.modules["homeassistant.helpers.restore_state"] = MagicMock(**mock_entity_classes)

    # Mock the 'homeassistant.components' parent module
    sys.modules["homeassistant.components"] = MagicMock()

    # Mock the individual component modules, injecting the mock entity classes
    # and any other required attributes.
    sys.modules["homeassistant.components.sensor"] = MagicMock(**mock_entity_classes)
    sys.modules["homeassistant.components.binary_sensor"] = MagicMock(**mock_entity_classes)
    sys.modules["homeassistant.components.button"] = MagicMock(**mock_entity_classes)

    # Mock other required modules that don't contain entity base classes
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
        if module_name not in sys.modules:
            sys.modules[module_name] = MagicMock()

@pytest.fixture
def mock_hass():
    """A mock Home Assistant instance for testing."""
    return MagicMock()