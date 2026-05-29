"""Constants for the ha2tuiss integration."""

# name for the integration.
DOMAIN = "tuiss2ha"

CONF_BLIND_HOST = "host"
CONF_BLIND_NAME = "name"

SPEED_CONTROL_SUPPORTED_MODELS = ["TS5200","TS5101","TS5001","TS2600"]

TIMEOUT_SECONDS = 120
TRAVERSAL_UPDATE_THRESHOLD = 5
BLIND_NOTIFY_CHARACTERISTIC = "00010304-0405-0607-0809-0a0b0c0d1910"
CONNECTION_MESSAGE = "ff03030303787878787878"
INITIALIZATION_MESSAGE = "ff78ea41d10301"
UUID = "00010405-0405-0607-0809-0a0b0c0d1910"

# BLE Protocol Commands
CMD_HEARTBEAT = "ff010101010101"
CMD_STOP = "ff78ea415f0301"
CMD_BATTERY_STATUS = "ff78ea41f00301"
CMD_SPEED_STANDARD = "ff78ea41f202"
CMD_SPEED_COMFORT = "ff78ea41f201"
CMD_SPEED_SLOW = "ff78ea41f200"
CMD_LIMITS_INIT_2 = "ff78ea41210301"
CMD_LIMITS_STEP_UP = "ff78ea41220301"
CMD_LIMITS_STEP_DOWN = "ff78ea41230301"
CMD_LIMITS_MOVE_UP = "ff78ea41cf0301"
CMD_LIMITS_MOVE_DOWN = "ff78ea411f0301"
CMD_LIMITS_SET = "ff78ea41410301"
CMD_TIMER_REQUEST = "ff78ea4104"
CMD_TIMESTAMP_BASE = "ff78ea410200"
CMD_TIMER_DELETE_BASE = "ff78ea410301"
CMD_TIMER_RESET = "ff04040404"
CMD_BLIND_REACTIVATE = "ff02020202787878787878"

OPT_RESTART_POSITION = "blind_restart_position"
DEFAULT_RESTART_POSITION = False

OPT_RESTART_ATTEMPTS = "blind_restart_attempts"
DEFAULT_RESTART_ATTEMPTS = 4

# Per-operation retry: how many times a user-facing BLE op (set_position,
# stop, set_speed, get_battery_status, etc.) may be re-attempted on a
# transient failure before the error surfaces to HA. 1 disables retries.
OPT_OPERATION_RETRY = "blind_operation_retry"
DEFAULT_OPERATION_RETRY = 2

# Exponential backoff between connection retries. Sequence is
# BASE * 2 ** (n-1), capped at MAX, plus up to JITTER seconds of
# randomness so multiple blinds don't re-try in lockstep.
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 16.0
BACKOFF_JITTER_SECONDS = 0.5

OPT_BLIND_SPEED = "blind_speed"
DEFAULT_BLIND_SPEED = "Standard"
BLIND_SPEED_LIST = ["Standard", "Comfort", "Slow"]

OPT_FAVORITE_POSITION = "blind_favorite_position"
DEFAULT_FAVORITE_POSITION = 50

#Exceptions
OPT_BATTERY_CHECK_DAYS = "blind_battery_check_days"
DEFAULT_BATTERY_CHECK_DAYS = 0

class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidHost(Exception):
    """Error to indicate there is an invalid hostname."""


class InvalidName(Exception):
    """Error to indicate there is an invalid device name."""


class DeviceNotFound(Exception):
    """Error to indicate the device is not found."""


class ConnectionTimeout(Exception):
    """Error to indicate a connection timeout."""


class NoConnectableBluetoothAdapter(Exception):
    """Error to indicate no Bluetooth adapter can connect (e.g. Shelly is passive-only)."""
