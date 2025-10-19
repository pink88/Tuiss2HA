"""Test cover state and transitions."""
from unittest.mock import MagicMock
import pytest

from homeassistant.const import STATE_CLOSED, STATE_OPEN, STATE_OPENING, STATE_CLOSING
from homeassistant.components.cover import CoverDeviceClass
from custom_components.tuiss2ha.cover import Tuiss

@pytest.mark.parametrize("moving,position,expected_state", [
    (0, 0, STATE_CLOSED),      # not moving, position 0
    (0, 24, STATE_CLOSED),     # not moving, position < 25
    (0, 25, STATE_OPEN),       # not moving, position = 25
    (0, 50, STATE_OPEN),       # not moving, position > 25
    (0, 100, STATE_OPEN),      # not moving, position = 100
    (1, 50, STATE_OPENING),    # moving up
    (-1, 50, STATE_CLOSING),   # moving down
])
def test_cover_state_transitions(mock_hass, moving, position, expected_state):
    """Test cover entity state property based on _moving and position values."""
    # Create a fake blind
    blind = MagicMock()
    blind._moving = moving
    blind._current_cover_position = position
    blind.name = "Test Blind"
    blind.model = "TB-01"
    blind.blind_id = "aa:bb:cc:dd:ee:ff"
    blind.host = blind.blind_id
    blind.hub = MagicMock(manufacturer="Tuiss")
    
    # Create a fake config entry
    config = MagicMock()
    config.options = {}

    cover = Tuiss(blind, config)
    assert cover.state == expected_state


@pytest.mark.parametrize("position,expected_closed", [
    (0, True),     # position 0 is closed
    (1, False),    # position > 0 is not closed
    (50, False),   # middle position is not closed
    (100, False),  # fully open is not closed
    (None, None),  # None position returns None
])
def test_cover_is_closed_property(mock_hass, position, expected_closed):
    """Test is_closed property based on current position."""
    blind = MagicMock()
    blind._current_cover_position = position
    blind.name = "Test Blind"
    blind.model = "TB-01"
    blind.blind_id = "aa:bb:cc:dd:ee:ff"
    blind.host = blind.blind_id
    blind.hub = MagicMock(manufacturer="Tuiss")

    config = MagicMock()
    config.options = {}

    cover = Tuiss(blind, config)
    assert cover.is_closed is expected_closed


def test_cover_properties(mock_hass):
    """Test basic cover properties."""
    blind = MagicMock()
    blind.name = "Test Blind"
    blind.model = "TB-01"
    blind.blind_id = "aa:bb:cc:dd:ee:ff"
    blind.host = blind.blind_id
    blind.hub = MagicMock(manufacturer="Tuiss")
    blind._attr_traversal_speed = 5.0

    config = MagicMock()
    config.options = {}

    cover = Tuiss(blind, config)

    assert cover.device_class == CoverDeviceClass.SHADE
    assert cover.available is True
    assert cover.should_poll is False
    assert cover._attr_name == "Test Blind"
    assert cover._attr_unique_id == "aa:bb:cc:dd:ee:ff_cover"
    assert "traversal_speed" in cover.extra_state_attributes
    assert "mac_address" in cover.extra_state_attributes