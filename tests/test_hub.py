# tests/test_hub.py
import pytest
from unittest.mock import MagicMock, patch

# Now import your code
from custom_components.tuiss2ha.hub import Hub, TuissBlind


@pytest.fixture
def mock_hub(mock_hass):
    """A mock Hub object that can be used to initialize a TuissBlind."""
    # We patch the bluetooth device lookup for the blind inside the hub
    with patch("custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address", MagicMock()):
        hub = Hub(mock_hass, "AA:BB:CC:DD:EE:FF", "Test Blind")
    return hub


@pytest.fixture
def tuiss_blind(mock_hub):
    """A TuissBlind object for testing, taken from the mock_hub."""
    return mock_hub.blinds[0]


def test_hub_initialization(mock_hub):
    """Test the initialization of the Hub class."""
    assert mock_hub.host == "AA:BB:CC:DD:EE:FF"
    assert mock_hub.name == "Test Blind"
    assert mock_hub.hub_id == "AA:BB:CC:DD:EE:FF"


def test_hub_blinds_list(mock_hub):
    """Test that the hub creates a list of TuissBlind objects."""
    assert isinstance(mock_hub.blinds, list)
    assert len(mock_hub.blinds) == 1
    assert isinstance(mock_hub.blinds[0], TuissBlind)


def test_tuiss_blind_initialization(tuiss_blind, mock_hub):
    """Test the initialization of the TuissBlind object."""
    assert tuiss_blind.host == "AA:BB:CC:DD:EE:FF"
    assert tuiss_blind.name == "Test Blind"
    assert tuiss_blind.hub == mock_hub
    assert tuiss_blind.blind_id == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize(
    "user_percent, expected_hex",
    [
        (100, "ff78ea41bf030000"),  # Fully open
        (0, "ff78ea41bf03e803"),    # Fully closed
        (50, "ff78ea41bf03f401"),   # 50%
        (75, "ff78ea41bf03fa00"),   # 75%
        (25, "ff78ea41bf03ee02"),   # 25%
        (23.2, "ff78ea41bf030003"), # group 3 boundary
        (48.8, "ff78ea41bf030002"), # group 2 boundary
        (74.4, "ff78ea41bf030001"), # group 1 boundary
    ],
)
def test_hex_convert(tuiss_blind, user_percent, expected_hex):
    """Test the hex_convert method with various percentages."""
    assert tuiss_blind.hex_convert(user_percent) == expected_hex