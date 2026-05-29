"""Tests for the auto-retry-with-backoff feature."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bleak.exc import BleakError

from custom_components.tuiss2ha.hub import TuissBlind
from custom_components.tuiss2ha.const import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    DEFAULT_OPERATION_RETRY,
    DeviceNotFound,
    ConnectionTimeout,
)


def _make_blind(mock_hass) -> TuissBlind:
    """Build a TuissBlind with bluetooth discovery patched."""
    fake_device = MagicMock()
    fake_device.name = "TB-01"
    with patch(
        "custom_components.tuiss2ha.hub.bluetooth.async_ble_device_from_address",
        return_value=fake_device,
    ):
        hub = MagicMock()
        hub._hass = mock_hass
        return TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)


def test_backoff_delay_doubles_then_caps():
    """Sequence is BASE, BASE*2, BASE*4, ... capped at MAX (jitter ignored)."""
    # Force jitter to zero for deterministic comparison.
    with patch("custom_components.tuiss2ha.hub.random.uniform", return_value=0.0):
        delays = [TuissBlind._backoff_delay(n) for n in range(1, 8)]

    assert delays[0] == BACKOFF_BASE_SECONDS                  # 1
    assert delays[1] == BACKOFF_BASE_SECONDS * 2              # 2
    assert delays[2] == BACKOFF_BASE_SECONDS * 4              # 4
    assert delays[3] == BACKOFF_BASE_SECONDS * 8              # 8
    assert delays[4] == BACKOFF_MAX_SECONDS                   # 16 capped
    assert delays[5] == BACKOFF_MAX_SECONDS                   # still capped
    assert delays[6] == BACKOFF_MAX_SECONDS                   # still capped


def test_backoff_delay_adds_jitter_within_bound():
    """Jitter must not exceed BACKOFF_JITTER_SECONDS."""
    base = TuissBlind._backoff_delay(1)
    assert BACKOFF_BASE_SECONDS <= base <= BACKOFF_BASE_SECONDS + 1.0  # generous slack


@pytest.mark.asyncio
async def test_retry_operation_returns_first_success(mock_hass):
    """A successful first call returns immediately and is not retried."""
    tb = _make_blind(mock_hass)
    op = AsyncMock(return_value="ok")

    result = await tb._retry_operation("test_op", op, max_attempts=3)

    assert result == "ok"
    assert op.await_count == 1


@pytest.mark.asyncio
async def test_retry_operation_recovers_on_second_attempt(mock_hass):
    """A transient failure is followed by a reconnect and a successful retry."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise BleakError("transient")
        return "second"

    # Patch the inter-attempt sleep so the test runs fast.
    with patch("custom_components.tuiss2ha.hub.asyncio.sleep", AsyncMock()):
        result = await tb._retry_operation("test_op", flaky, max_attempts=3)

    assert result == "second"
    assert calls["n"] == 2
    # disconnect must be called between attempts to drop the stale client
    tb.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_retry_operation_gives_up_after_max_attempts(mock_hass):
    """Persistent transient errors raise after the configured number of tries."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()

    op = AsyncMock(side_effect=BleakError("never recovers"))

    with patch("custom_components.tuiss2ha.hub.asyncio.sleep", AsyncMock()):
        with pytest.raises(BleakError):
            await tb._retry_operation("test_op", op, max_attempts=3)

    assert op.await_count == 3


@pytest.mark.asyncio
async def test_retry_operation_does_not_retry_devicenotfound(mock_hass):
    """DeviceNotFound is non-transient and must propagate immediately."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()

    op = AsyncMock(side_effect=DeviceNotFound("gone"))

    with pytest.raises(DeviceNotFound):
        await tb._retry_operation("test_op", op, max_attempts=5)

    assert op.await_count == 1
    tb.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_operation_uses_default_when_max_none(mock_hass):
    """Falling back to the default operation-retry count when not specified."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()
    tb._operation_retry = None  # force default fallback

    op = AsyncMock(side_effect=ConnectionTimeout("flaky"))

    with patch("custom_components.tuiss2ha.hub.asyncio.sleep", AsyncMock()):
        with pytest.raises(ConnectionTimeout):
            await tb._retry_operation("test_op", op)

    assert op.await_count == DEFAULT_OPERATION_RETRY


@pytest.mark.asyncio
async def test_retry_operation_clamps_max_attempts_to_one(mock_hass):
    """max_attempts < 1 is normalised to 1 — never run zero times."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock()
    op = AsyncMock(return_value="ok")

    result = await tb._retry_operation("test_op", op, max_attempts=0)

    assert result == "ok"
    assert op.await_count == 1


@pytest.mark.asyncio
async def test_retry_operation_disconnect_failure_is_swallowed(mock_hass):
    """If disconnect fails between attempts, the next retry still runs."""
    tb = _make_blind(mock_hass)
    tb.disconnect = AsyncMock(side_effect=RuntimeError("disconnect fail"))

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise BleakError("transient")
        return "ok"

    with patch("custom_components.tuiss2ha.hub.asyncio.sleep", AsyncMock()):
        result = await tb._retry_operation("test_op", flaky, max_attempts=3)

    assert result == "ok"
    assert calls["n"] == 2
