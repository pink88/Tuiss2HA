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

OPT_RESTART_POSITION = "blind_restart_position"
DEFAULT_RESTART_POSITION = False

OPT_RESTART_ATTEMPTS = "blind_restart_attempts"
DEFAULT_RESTART_ATTEMPTS = 4

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
