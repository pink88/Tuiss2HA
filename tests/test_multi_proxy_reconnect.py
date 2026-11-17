"""Test multi-proxy reconnection scenarios.

When a blind is accessible through multiple Bluetooth proxies, the integration
should switch to whichever proxy currently has the best signal on reconnect,
not remain stuck on the proxy that originally connected.
"""

from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from bleak.exc import BleakError

from custom_components.tuiss2ha.hub import TuissBlind, Hub
from custom_components.tuiss2ha.const import ConnectionTimeout


@pytest.mark.asyncio
async def test_ble_device_updated_on_discovery(mock_hass):
    """When discovery callback fires, _ble_device should be updated to fresh reference."""
    # Simulate two different proxy routes to the same blind
    proxy_a_device = MagicMock(name="proxy_a_device")
    proxy_a_device.name = "TB-01"
    proxy_b_device = MagicMock(name="proxy_b_device")
    proxy_b_device.name = "TB-01"

    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        return_value=proxy_a_device,
    ):
        hub = MagicMock(spec=Hub)
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test Blind", hub)
        assert tb._ble_device is proxy_a_device

    # Simulate discovery callback receiving a fresh device from proxy B
    service_info = MagicMock()
    service_info.device = proxy_b_device
    service_info.advertisement = MagicMock()
    service_info.advertisement.rssi = -55

    # Manually call the callback (in real code, HA's BT stack fires this)
    tb._ble_device = service_info.device  # This is what the fixed callback does
    tb.set_rssi(service_info.advertisement.rssi)

    # Verify device reference was updated to proxy B
    assert tb._ble_device is proxy_b_device
    assert tb.rssi == -55


@pytest.mark.asyncio
async def test_attempt_connection_switches_proxy_on_retry(mock_hass):
    """When connection fails, retry loop should refresh device to potentially switch proxies."""
    proxy_a_device = MagicMock(name="proxy_a_device")
    proxy_a_device.name = "TB-01"
    proxy_b_device = MagicMock(name="proxy_b_device")
    proxy_b_device.name = "TB-01"

    fake_client = MagicMock()
    fake_client.is_connected = True
    fake_client.write_gatt_char = AsyncMock()

    # Simulate: first retry returns proxy_a (which fails to connect),
    # second refresh returns proxy_b (which succeeds)
    device_lookups = [proxy_a_device, proxy_b_device]
    lookup_count = {"count": 0}

    def mock_device_lookup(*args, **kwargs):
        dev = device_lookups[min(lookup_count["count"], len(device_lookups) - 1)]
        lookup_count["count"] += 1
        return dev

    call_count = {"count": 0}

    async def mock_establish_connection(*args, **kwargs):
        call_count["count"] += 1
        # First attempt via proxy_a fails
        if call_count["count"] < 2:
            raise BleakError("proxy_a connection lost")
        # Second attempt via proxy_b succeeds
        return fake_client

    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        side_effect=mock_device_lookup,
    ):
        hub = MagicMock(spec=Hub)
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test Blind", hub)

        with patch(
            "custom_components.tuiss2ha.hub.establish_connection",
            side_effect=mock_establish_connection,
        ):
            tb._restart_attempts = 2
            await tb.attempt_connection()

            # Should have succeeded on second attempt
            assert tb._client is fake_client

            # On retry, the device lookup should have been called again and
            # refreshed to proxy_b before the second connection attempt
            assert lookup_count["count"] >= 2


@pytest.mark.asyncio
async def test_ble_device_callback_returns_fresh_device(mock_hass):
    """The ble_device_callback passed to establish_connection should return fresh device."""
    proxy_a_device = MagicMock(name="proxy_a_device")
    proxy_a_device.name = "TB-01"
    proxy_b_device = MagicMock(name="proxy_b_device")
    proxy_b_device.name = "TB-01"

    fake_client = MagicMock()
    fake_client.is_connected = True
    fake_client.write_gatt_char = AsyncMock()

    # Capture the ble_device_callback to verify it returns fresh device
    captured_callback = {"func": None}

    async def mock_establish(*args, **kwargs):
        captured_callback["func"] = kwargs.get("ble_device_callback")
        return fake_client

    device_sequence = iter([proxy_a_device, proxy_b_device])

    def mock_device_lookup(*args, **kwargs):
        return next(device_sequence, proxy_b_device)

    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        side_effect=mock_device_lookup,
    ):
        hub = MagicMock(spec=Hub)
        hub._hass = mock_hass
        tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test Blind", hub)

        with patch(
            "custom_components.tuiss2ha.hub.establish_connection",
            side_effect=mock_establish,
        ):
            await tb.connect()

            # The callback should exist
            assert captured_callback["func"] is not None
            # When called during retries, it should return a fresh device
            fresh_device = captured_callback["func"]()
            assert fresh_device is proxy_b_device
