import pytest
from unittest.mock import MagicMock

from tuiss2ha.cover import Tuiss

@pytest.fixture
def mock_blind():
    mock_hub = MagicMock()
    mock_blind = MagicMock()
    mock_blind._id = "host"
    mock_blind.name = "name"
    mock_blind.model = "Tuiss"
    mock_blind.hub = mock_hub
    mock_blind._moving = 0
    mock_blind._current_cover_position = None
    mock_blind._client.is_connected = False
    return mock_blind

def test_tuiss_init(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss._blind == mock_blind
    assert tuiss._attr_unique_id == "host_cover"
    assert tuiss._attr_name == "name"
    assert tuiss._state is None

def test_tuiss_state_opening(mock_blind):
    mock_blind._moving = 1
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "opening"

def test_tuiss_state_closing(mock_blind):
    mock_blind._moving = -1
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "closing"

def test_tuiss_state_open(mock_blind):
    mock_blind._moving = 0
    mock_blind._current_cover_position = 75
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "open"

def test_tuiss_state_closed(mock_blind):
    mock_blind._moving = 0
    mock_blind._current_cover_position = 0
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "closed"

def test_tuiss_should_poll(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.should_poll == False

def test_tuiss_available(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.available == True

def test_tuiss_current_cover_position(mock_blind):
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.current_cover_position == 50

def test_tuiss_is_closed(mock_blind):
    mock_blind._current_cover_position = 0
    tuiss = Tuiss(mock_blind)
    assert tuiss.is_closed == True

def test_tuiss_supported_features(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.supported_features == 15  # 15 is the sum of CoverEntityFeature.OPEN, CoverEntityFeature.CLOSE, CoverEntityFeature.SET_POSITION, and CoverEntityFeature.STOP

def test_tuiss_device_info(mock_blind):
    mock_hub = MagicMock()
    mock_hub.manufacturer = "Manufacturer"
    mock_blind.hub = mock_hub
    tuiss = Tuiss(mock_blind)
    assert tuiss.device_info == {
        "identifiers": {("tuiss2ha", "host")},
        "name": "name",
        "model": "Tuiss",
        "manufacturer": "Manufacturer"
    }

@pytest.mark.asyncio
async def test_tuiss_async_open_cover(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_open_cover()
    assert mock_blind._moving == 1
    assert tuiss._state == "opening"

@pytest.mark.asyncio
async def test_tuiss_async_close_cover(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_close_cover()
    assert mock_blind._moving == -1
    assert tuiss._state == "closing"

@pytest.mark.asyncio
async def test_tuiss_async_set_cover_position(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_set_cover_position(**{"position": 50})
    assert mock_blind._moving == -1
    assert tuiss._state == "closing"

@pytest.mark.asyncio
async def test_tuiss_async_stop_cover(mock_blind):
    tuiss = Tuiss(mock_blind)
    await tuiss.async_stop_cover()
    assert tuiss._state is None
from unittest.mock import MagicMock

from tuiss2ha.cover import Tuiss

@pytest.fixture
def mock_blind():
    mock_hub = MagicMock()
    mock_blind = MagicMock()
    mock_blind._id = "host"
    mock_blind.name = "name"
    mock_blind.model = "Tuiss"
    mock_blind.hub = mock_hub
    mock_blind._moving = 0
    mock_blind._current_cover_position = None
    mock_blind._client.is_connected = False
    return mock_blind

def test_tuiss_init(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss._blind == mock_blind
    assert tuiss._attr_unique_id == "host_cover"
    assert tuiss._attr_name == "name"
    assert tuiss._state is None

def test_tuiss_state_opening(mock_blind):
    mock_blind._moving = 1
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "opening"

def test_tuiss_state_closing(mock_blind):
    mock_blind._moving = -1
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "closing"

def test_tuiss_state_open(mock_blind):
    mock_blind._moving = 0
    mock_blind._current_cover_position = 75
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "open"

def test_tuiss_state_closed(mock_blind):
    mock_blind._moving = 0
    mock_blind._current_cover_position = 0
    tuiss = Tuiss(mock_blind)
    assert tuiss.state == "closed"

def test_tuiss_should_poll(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.should_poll == False

def test_tuiss_available(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.available == True

def test_tuiss_current_cover_position(mock_blind):
    mock_blind._current_cover_position = 50
    tuiss = Tuiss(mock_blind)
    assert tuiss.current_cover_position == 50

def test_tuiss_is_closed(mock_blind):
    mock_blind._current_cover_position = 0
    tuiss = Tuiss(mock_blind)
    assert tuiss.is_closed == True

def test_tuiss_supported_features(mock_blind):
    tuiss = Tuiss(mock_blind)
    assert tuiss.supported_features == 15  # 15 is the sum of CoverEntityFeature.OPEN, CoverEntityFeature.CLOSE, CoverEntityFeature.SET_POSITION, and CoverEntityFeature.STOP

def test_tuiss_device_info(mock_blind):
    mock_hub = MagicMock()
    mock_hub.manufacturer = "Manufacturer"
    mock_blind.hub = mock_hub
    tuiss = Tuiss(mock_blind)
    assert tuiss.device_info == {
        "identifiers": {("tuiss2ha", "host")},
        "name": "name",
        "model": "Tuiss",
        "manufacturer": "Manufacturer"
    }

@pytest.mark.asyncio
async def test_tuiss_async_open_cover(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_open_cover()
    assert mock_blind._moving == 1
    assert tuiss._state == "opening"

@pytest.mark.asyncio
async def test_tuiss_async_close_cover(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_close_cover()
    assert mock_blind._moving == -1
    assert tuiss._state == "closing"

@pytest.mark.asyncio
async def test_tuiss_async_set_cover_position(mock_blind):
    mock_blind._client.is_connected = True
    tuiss = Tuiss(mock_blind)
    await tuiss.async_set_cover_position(**{"position": 50})
    assert mock_blind._moving == -1
    assert tuiss._state == "closing"

@pytest.mark.asyncio
async def test_tuiss_async_stop_cover(mock_blind):
    tuiss = Tuiss(mock_blind)
    await tuiss.async_stop_cover()
    assert tuiss._state is None