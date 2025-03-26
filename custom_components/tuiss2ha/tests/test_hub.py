import pytest
from unittest.mock import MagicMock

from tuiss2ha.hub import Hub, TuissBlind


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_hub(mock_hass):
    return Hub(mock_hass, "host", "name")


@pytest.fixture
def mock_blind(mock_hub):
    return TuissBlind("host", "name", mock_hub)


def test_hub_init(mock_hass):
    hub = Hub(mock_hass, "host", "name")
    assert hub._host == "host"
    assert hub._hass == mock_hass
    assert hub._name == "name"
    assert hub._id == "host"
    assert len(hub.blinds) == 1
    assert isinstance(hub.blinds[0], TuissBlind)


def test_hub_hub_id(mock_hub):
    assert mock_hub.hub_id == "host"


def test_blind_init(mock_hub):
    blind = TuissBlind("host", "name", mock_hub)
    assert blind._id == "host"
    assert blind._host == "host"
    assert blind.name == "name"
    assert blind.hub == mock_hub
    assert blind.model == "Tuiss"
    assert blind._ble_device is None
    assert blind._client is None
    assert blind._callbacks == set()
    assert blind._battery_status is False
    assert blind._moving == 0
    assert blind._current_cover_position is None
    assert blind._desired_position is None


def test_blind_blind_id(mock_blind):
    assert mock_blind.blind_id == "host"


def test_blind_register_callback(mock_blind):
    callback = MagicMock()
    mock_blind.register_callback(callback)
    assert callback in mock_blind._callbacks


def test_blind_remove_callback(mock_blind):
    callback = MagicMock()
    mock_blind.register_callback(callback)
    mock_blind.remove_callback(callback)
    assert callback not in mock_blind._callbacks


@pytest.mark.asyncio
async def test_blind_attempt_connection(mock_blind):
    mock_blind._ble_device = MagicMock()
    mock_blind._client = MagicMock()
    await mock_blind.attempt_connection()
    assert mock_blind._ble_device is not None
    assert mock_blind._client is not None


@pytest.mark.asyncio
async def test_blind_blind_connect(mock_blind):
    mock_blind._ble_device = MagicMock()
    mock_blind._device = MagicMock()
    mock_blind._client = None
    await mock_blind.blind_connect()
    assert mock_blind._client is not None


@pytest.mark.asyncio
async def test_blind_blind_disconnect(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.blind_disconnect()
    assert mock_blind._client.disconnect.called


@pytest.mark.asyncio
async def test_blind_set_position(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.set_position(50)
    assert mock_blind._client.start_notify.called
    assert mock_blind._client.write_gatt_char.called


@pytest.mark.asyncio
async def test_blind_stop(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.stop()
    assert mock_blind._client.is_connected
    assert mock_blind._client.write_gatt_char.called


@pytest.mark.asyncio
async def test_blind_check_connection(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.check_connection()
    assert mock_blind._client.is_connected


@pytest.mark.asyncio
async def test_blind_get_battery_status(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.get_battery_status()
    assert mock_blind._client.start_notify.called
    assert mock_blind._client.write_gatt_char.called


@pytest.mark.asyncio
async def test_blind_get_blind_position(mock_blind):
    mock_blind._client = MagicMock()
    await mock_blind.get_blind_position()
    assert mock_blind._client.start_notify.called
    assert mock_blind._client.write_gatt_char.called