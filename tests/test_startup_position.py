"""Tests for the background, rate-limited startup position fetch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.tuiss2ha as integ


def _blind(name="Blind", side_effect=None):
    blind = MagicMock()
    blind.name = name
    blind.host = "AA:BB:CC:DD:EE:FF"
    blind.get_blind_position = AsyncMock(side_effect=side_effect)
    return blind


@pytest.mark.asyncio
async def test_fetch_succeeds_first_try():
    hass = MagicMock()
    hass.data = {}
    blind = _blind()
    with patch.object(integ.bluetooth, "async_ble_device_from_address", return_value=object()), \
         patch.object(integ.asyncio, "sleep", AsyncMock()) as sleep:
        await integ._async_fetch_position_on_start(hass, blind)
    blind.get_blind_position.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_retries_then_gives_up_without_raising():
    hass = MagicMock()
    hass.data = {}
    blind = _blind(side_effect=asyncio.TimeoutError)
    with patch.object(integ.bluetooth, "async_ble_device_from_address", return_value=object()), \
         patch.object(integ.asyncio, "sleep", AsyncMock()):
        await integ._async_fetch_position_on_start(hass, blind)
    assert blind.get_blind_position.await_count == integ.STARTUP_FETCH_ATTEMPTS


@pytest.mark.asyncio
async def test_fetch_waits_until_seen_by_scanner():
    hass = MagicMock()
    hass.data = {}
    blind = _blind()
    seen = iter([None, None, object()])
    with patch.object(integ.bluetooth, "async_ble_device_from_address", side_effect=lambda *a, **k: next(seen)), \
         patch.object(integ.asyncio, "sleep", AsyncMock()) as sleep:
        await integ._async_fetch_position_on_start(hass, blind)
    blind.get_blind_position.assert_awaited_once()
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_concurrency_is_limited():
    hass = MagicMock()
    hass.data = {}
    running = 0
    peak = 0

    async def slow():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    blinds = [_blind(f"B{i}", side_effect=slow) for i in range(6)]
    with patch.object(integ.bluetooth, "async_ble_device_from_address", return_value=object()):
        await asyncio.gather(*(integ._async_fetch_position_on_start(hass, b) for b in blinds))
    assert peak <= integ.STARTUP_MAX_CONCURRENT
    assert all(b.get_blind_position.await_count == 1 for b in blinds)
