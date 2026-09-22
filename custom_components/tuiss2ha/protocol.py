"""Protocol encoding and decoding for Tuiss Smartview BLE."""
from __future__ import annotations

import datetime
import logging

from .const import CMD_TIMESTAMP_BASE

_LOGGER = logging.getLogger(__name__)


def hex_convert(user_percent: float) -> str:
    """Convert the Home Assistant position percentage (0-100) to the Tuiss hex command."""
    # Tuiss uses an inverted percentage (0=open, 100=closed)
    tuiss_percent = 100 - user_percent

    # Calculate the absolute position value (0-1000)
    total_val = int(round(tuiss_percent * 10))

    # Extract lower byte (position) and upper byte (group)
    position_value = total_val % 256
    group_value = total_val // 256

    # Format the position value as a two-character hex (e.g., 0A, FF)
    hex_val = f"{position_value:02x}"
    group_str = f"{group_value:02x}"

    # Build the final command
    command_prefix = "ff78ea41bf03"
    return f"{command_prefix}{hex_val}{group_str}"


def split_data(data: bytearray) -> list[int]:
    """Convert the byte response into a list of decimals."""
    return list(data)


def create_timer_command(index: str, days: list[str], time: str, position: float) -> str:
    """Create the hex command to program a timer slot."""
    # Convert days to bitmask
    day_map = {"sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64}
    day_bits = sum(day_map[day] for day in days if day in day_map)

    # Convert time to minutes since midnight
    time_parts = time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])

    # Convert position to fixed-point (e.g., multiply by 10)
    target_position_value = int(float(position) * 10)
    position_byte_1 = target_position_value % 256
    position_byte_2 = target_position_value // 256

    timer_index = int(index)
    command_prefix = "ff78ea410300"
    command_type = "b23f"

    hex_command = (
        f"{command_prefix}{timer_index:02x}{command_type}"
        f"{day_bits:02x}{hours:02x}{minutes:02x}00"
        f"{position_byte_1:02x}{position_byte_2:02x}"
    )
    return hex_command


def build_timestamp_command(now: datetime.datetime) -> bytes:
    """Build the current timestamp command bytes."""
    timestamp_hex = (
        f"{CMD_TIMESTAMP_BASE}{now.year - 2000:02x}{now.month:02x}"
        f"{now.day:02x}{now.hour:02x}{now.minute:02x}{now.second:02x}"
    )
    return bytes.fromhex(timestamp_hex)
