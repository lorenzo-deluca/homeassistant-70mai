# Home Assistant Integration for 70mai Dashcam

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/github/v/release/lorenzo-deluca/homeassistant-70mai)
![Downloads](https://img.shields.io/github/downloads/lorenzo-deluca/homeassistant-70mai/total)
[![](https://img.shields.io/static/v1?label=Sponsor&message=%E2%9D%A4&logo=GitHub&color=%23fe8e86)](https://github.com/sponsors/lorenzo-deluca)
[![buy me a coffee](https://img.shields.io/badge/support-buymeacoffee-222222.svg?style=flat-square)](https://www.buymeacoffee.com/lorenzodeluca)

> Bring your 70mai dashcam's GPS position, car battery voltage and alarms into [Home Assistant](https://www.home-assistant.io/).

This custom component talks to the 70mai cloud API (`eu-api.70mai.com`)
and turns it into native Home Assistant entities, so you don't need the
app open to see where your car is, how the battery's holding up, or that
an alarm just fired. If it's useful to you, a :coffee: or a GitHub :star:
is always appreciated, thanks! :blush:

<a href="https://www.buymeacoffee.com/lorenzodeluca" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="150px"></a>

# Disclaimer

This integration is built on
[`70maiclient`](https://github.com/lorenzo-deluca/70maiclient), a Python
client reverse-engineered from the 70mai iOS app's own network traffic
(installed automatically from PyPI as a dependency). It's **not
affiliated with, endorsed by, or supported by 70mai**. The underlying API
is undocumented and can change without notice, so if something breaks,
open an issue here rather than contacting 70mai support (they won't know
what this is).

---

## Features

- **`device_tracker`**: live GPS position for any cloud-connected
  dashcam on the account.
- **`sensor`**: car battery voltage, read from the dashcam's telemetry
  history.
- **`event`**: fires whenever a new dashcam alarm (motion/impact
  detection, etc.) is reported.

All three are added automatically for every device found on the account,
no manual entity configuration needed.

## Installation

You can install this integration like any other HACS custom integration.

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lorenzo-deluca&repository=homeassistant-70mai&category=integration)

- Click the badge above to open this repository directly in HACS, then
  click Install.
- Or add it manually: HACS → custom repositories → paste this
  repository's URL under the "Integration" category → search for
  "70mai Dashcam" → Install.

### Manual

Copy or link the [`custom_components/mai70`](./custom_components/mai70)
folder into your Home Assistant `config/custom_components` directory, then
restart Home Assistant.

## Configuration

Configuration is done entirely from the UI, there's no YAML setup.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mai70)

1. Click the badge above, or go to **Settings → Devices & Services → Add
   Integration** and search for **70mai Dashcam**.
2. Enter the email and password of your 70mai account (the same one used
   in the mobile app).

Every dashcam bound to that account is discovered automatically and shows
up as its own Home Assistant device.

## Entities

Per discovered dashcam (device name = the nickname set in the 70mai app,
falling back to its WiFi SSID):

| Platform         | Entity                            | Notes |
| ---------------- | ---------------------------------- | ----- |
| `device_tracker` | *Device* Position                  | GPS source, only created for devices that actually report a position. |
| `sensor`         | *Device* Battery voltage            | Car battery voltage in volts. The unit is a strong inference from the raw telemetry (not officially documented by 70mai); the entity attributes flag this via `unit_confirmed: false`. |
| `sensor`         | *Device* Last report                | Diagnostic timestamp of the last time the dashcam reported to the cloud (`getDashcamDetail`'s `device.reportTime`). |
| `sensor`         | *Device* Status                     | Diagnostic passthrough of `getDashcamDetail`'s `deviceStatus` (plus `simPluginActiveStatus`/`geofenceActiveStatus` as attributes). Field names are confirmed but the exact value meaning isn't, so this exposes the raw value rather than an on/off state; flagged via `value_confirmed: false`. |
| `sensor`         | *Device* Cellular firmware version | Diagnostic firmware version of the cellular add-on (`getSimPluginDetail`'s `pluginSoftwareVersion`, with IMEI as an attribute). Only created for devices that actually have a SIM plugin (detected empirically, like Position). |
| `event`          | *Device* Alarm                      | Fires a generic `alarm` event per new alarm, with the raw alarm payload as an attribute (specific alarm-type meanings aren't confirmed yet). |

Polling runs every 5 minutes by default.

## Known limitations

- The 70mai API is unofficial and reverse-engineered, so some data (like
  the battery sensor's unit, or alarm-type meanings) is a best-effort
  inference rather than a documented contract. Check
  [`70maiclient`](https://github.com/lorenzo-deluca/70maiclient)'s own
  docstrings for what is and isn't confirmed at the API level.
- `getAllDeviceForUser` pagination isn't implemented, so accounts with
  more than 50 bound devices will only see the first page.
- No options flow yet to change the poll interval from the UI.

## Work in progress

- Options flow for scan interval / alarm filtering.
- Additional entities from `70maiclient` methods whose response shape
  isn't confirmed yet (e.g. device switches, value-added-service
  status). PRs welcome.

## Other integrations by me

- [homeassistant-silence](https://github.com/lorenzo-deluca/homeassistant-silence): Home Assistant integration for Silence electric scooters.

## License

GNU AGPLv3 © Lorenzo De Luca
