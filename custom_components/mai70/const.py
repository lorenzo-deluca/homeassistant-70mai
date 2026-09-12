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

MANUFACTURER = "70mai"
