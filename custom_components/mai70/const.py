"""Constants for the 70mai dashcam integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "mai70"

CONF_UUID = "uuid"
# Config-entry key holding the resolved 70mai API base URL. Entries created
# before region support don't have it and keep using SERVER_EU.
CONF_BASE_URL = "base_url"
# Config-flow-only field: one of SERVER_CHOICES' keys, SERVER_AUTO, or a
# server address typed by hand (the selector accepts custom values).
CONF_SERVER = "server"

# 70mai account data lives on one regional server, and a login against the
# wrong one fails like a bad password. Known hosts (2026-11):
# - eu: the one every request in client70mai's captures went to.
# - int: the 70mai app's built-in default (assets/config/app_config.json
#   in the 4.0.0 APK); confirmed working by an Australian user (issue #2).
# - us: answers like a 70mai API to an anonymous probe, but no user has
#   confirmed logging in there yet.
# The app itself learns its real server at runtime from a downloaded
# config, so this list may be incomplete; that's why the config flow also
# accepts a server address typed by hand.
SERVER_EU = "https://eu-api.70mai.com"
SERVER_INT = "https://int-api.70mai.com"
SERVER_US = "https://us-api.70mai.com"
SERVER_AUTO = "auto"
# Also the order SERVER_AUTO tries them in.
SERVER_CHOICES = {
    "eu": SERVER_EU,
    "int": SERVER_INT,
    "us": SERVER_US,
}

DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

# getPosition has its own faster, adaptive poll
# (coordinator.Mai70PositionCoordinator) instead of riding along with the
# DEFAULT_SCAN_INTERVAL poll of every other endpoint. A dashcam that is
# driving keeps pushing its position to 70mai's cloud every few seconds
# (lastUpdateTime was ~11s old in a capture taken while driving), a parked
# one stops (~10 min old in a parked capture), so the age of the newest
# lastUpdateTime picks the interval: ACTIVE while any device's position is
# at most POSITION_ACTIVE_MAX_AGE old, IDLE otherwise.
# getPosition's own "status" field (2 while driving, 3 while parked in
# those same two captures) looks like it says the same thing, but its
# meaning isn't documented, so the confirmed timestamp is used instead.
POSITION_SCAN_INTERVAL_ACTIVE = timedelta(seconds=60)
POSITION_SCAN_INTERVAL_IDLE = timedelta(minutes=2)
POSITION_ACTIVE_MAX_AGE = timedelta(minutes=3)

# get_device_status_history_daily() keyIndex/smartType for battery voltage
# telemetry (see client70mai.client.MaiClient docstring for details).
BATTERY_KEY_INDEX = "1.4"
BATTERY_SMART_TYPE = 51

# check_new_rom_from_app() requires a client-reported base_version/
# base_subversion to run the update check at all, but the version it
# actually needs to report back the dashcam's current firmware
# (resultBodyObject.version) doesn't depend on what's passed here, so a
# fixed placeholder is used instead of tracking a real "last known"
# version across polls.
FIRMWARE_CHECK_BASE_VERSION = "0.0.0"
FIRMWARE_CHECK_BASE_SUBVERSION = "0"

# 70mai's API only allows one active session per account: logging into
# the mobile app invalidates this integration's token. After detecting
# that, wait this long before logging back in, so the integration
# doesn't immediately kick the app's own session back out again.
TOKEN_INVALID_RELOGIN_DELAY = timedelta(minutes=5)

MANUFACTURER = "70mai"
