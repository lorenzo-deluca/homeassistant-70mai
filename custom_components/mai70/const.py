"""Constants for the 70mai dashcam integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "mai70"

CONF_UUID = "uuid"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

# get_device_status_history_daily() keyIndex/smartType for battery voltage
# telemetry (see client70mai.client.MaiClient docstring for details).
BATTERY_KEY_INDEX = "1.4"
BATTERY_SMART_TYPE = 51

# get_device_alarm_list() alarm_types filter.
ALARM_TYPES = [105, 108]

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
