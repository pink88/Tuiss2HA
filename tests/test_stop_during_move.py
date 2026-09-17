"""Stopping a blind mid-move must end the move straight away.

Regression test: since the position-read guards added in 1.16.0, stop() no
longer ends the move. The post-stop position read is skipped while the move
holds _locked, and nothing else wakes wait_for_stop(). The blind physically
stops, but the entity keeps reporting opening/closing, every open/close is
rejected as "device_locked" until the move's timeout (about a minute), and the
timeout then records the blind as having reached its target.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tuiss2ha.hub import TuissBlind


def _moving_blind(mock_hass):
    hub = MagicMock()
    hub._hass = mock_hass
    tb = TuissBlind("AA:BB:CC:DD:EE:FF", "Test", hub)
    tb._battery_check_days = 0
    tb._attr_traversal_speed = 2.5   # full travel ~40s -> move timeout ~58s
    tb._current_cover_position = 0

    client = MagicMock()
    client.is_connected = True
    client.write_gatt_char = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()

    async def fake_disconnect():
        client.is_connected = False

    client.disconnect = AsyncMock(side_effect=fake_disconnect)

    async def fake_connect():
        client.is_connected = True
        tb._client = client

    tb.attempt_connection = AsyncMock(side_effect=fake_connect)
    tb.set_position = AsyncMock()
    return tb, client


async def _start_move(tb):
    task = asyncio.create_task(
        tb.async_move_cover(movement_direction=-1, target_position=100)
    )
    for _ in range(50):          # let the move reach its wait for the stop event
        await asyncio.sleep(0)
    assert tb._locked and tb._moving == -1
    return task


async def _stop_like_the_cover_entity(tb):
    # async_stop_cover sets this before calling stop()
    tb._is_stopping = True
    await tb.stop()


@pytest.mark.asyncio
async def test_stop_releases_move_promptly(mock_hass):
    tb, client = _moving_blind(mock_hass)
    task = await _start_move(tb)

    await _stop_like_the_cover_entity(tb)
    await asyncio.wait_for(task, timeout=2)

    assert not tb._locked
    assert not client.is_connected


@pytest.mark.asyncio
async def test_stop_before_move_starts_waiting_is_not_lost(mock_hass):
    """A stop that lands while the move command is still being sent must count."""
    tb, client = _moving_blind(mock_hass)
    sent = asyncio.Event()
    release = asyncio.Event()

    async def slow_set_position(_):
        sent.set()
        await release.wait()

    tb.set_position = AsyncMock(side_effect=slow_set_position)
    task = asyncio.create_task(
        tb.async_move_cover(movement_direction=-1, target_position=100)
    )
    await asyncio.wait_for(sent.wait(), timeout=2)

    await _stop_like_the_cover_entity(tb)
    release.set()
    await asyncio.wait_for(task, timeout=2)

    assert not tb._locked


@pytest.mark.asyncio
async def test_new_move_accepted_after_stop(mock_hass):
    tb, client = _moving_blind(mock_hass)
    task = await _start_move(tb)
    await _stop_like_the_cover_entity(tb)
    await asyncio.wait_for(task, timeout=2)
    tb._moving = 0                # async_stop_cover's finally does this

    second = await _start_move(tb)   # would raise device_locked if still locked
    tb._stopped_event.set()          # blind reports it reached the target
    await asyncio.wait_for(second, timeout=2)
    assert not tb._locked
