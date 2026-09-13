# Home Assistant Integration for 70mai Dashcam

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/github/v/release/lorenzo-deluca/homeassistant-70mai)
![Downloads](https://img.shields.io/github/downloads/lorenzo-deluca/homeassistant-70mai/total)
[![](https://img.shields.io/static/v1?label=Sponsor&message=%E2%9D%A4&logo=GitHub&color=%23fe8e86)](https://github.com/sponsors/lorenzo-deluca)
[![buy me a coffee](https://img.shields.io/badge/support-buymeacoffee-222222.svg?style=flat-square)](https://www.buymeacoffee.com/lorenzodeluca)

> Bring your 70mai dashcam's GPS position, car battery voltage and alarms into [Home Assistant](https://www.home-assistant.io/).

This custom component talks to the 70mai cloud API (`eu-api.70mai.com`) and turns it into native Home Assistant entities, so you don't need the
app open to see where your car is, how the battery's holding up, or that an alarm just fired. 
If it's useful to you, a :coffee: or a GitHub :star: is always appreciated, thanks! :blush:

<a href="https://www.buymeacoffee.com/lorenzodeluca" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="150px"></a>

# Disclaimer
This integration is built on [`70maiclient`](https://github.com/lorenzo-deluca/70maiclient), a Python
client reverse-engineered from the 70mai iOS app's own network traffic (installed automatically from PyPI as a dependency). 
It's **not affiliated with, endorsed by, or supported by 70mai**. 
The underlying API is undocumented and can change without notice, so if something breaks, open an issue here rather than contacting 70mai support (they won't know what this is).

If someone from 70mai would like to contribute or collaborate please contact me at [me@lorenzodeluca.dev](mailto:me@lorenzodeluca.dev?subject=[GitHub]homeassistant-70mai)

---

## Supported devices

Every call this integration makes goes through 70mai's **cloud** API
(`eu-api.70mai.com`), not a local/Bluetooth/WiFi-direct connection. That
means a dashcam only shows up with useful data here if it can talk to
70mai's cloud on its own, which in practice requires the **4G/cellular
add-on module** (the SIM plugin 70mai sells alongside some dashcam
models) to be installed and active - that's what keeps the dashcam
online and reporting when it's not connected to the 70mai app's phone
hotspot/WiFi.

A dashcam bound to your account but without an active 4G module will
still be *discovered*, but most entities won't appear for it: GPS
position, the cellular/SIM sensors, and alarms all depend on cloud
connectivity that a WiFi-only device doesn't have. This integration
detects that capability **empirically** (an entity is only created once
its underlying API call actually succeeds for that device) rather than
by hardcoding a device model/type check, since there's no confirmed
field that reliably tells 4G-equipped and WiFi-only devices apart - see
`custom_components/mai70/device_tracker.py` and `sensor.py`'s
`should_add` predicates.

### Tested models

| Model | 4G/SIM module | Status |
| ----- | -------------- | ------ |
| A810  | Yes            | Confirmed working (author's own device). |

This is the only model I can personally verify, since it's the only one
I own. The API itself isn't model-specific, so other 4G-equipped 70mai
dashcams likely work too - they just haven't been confirmed yet. **If
you run this integration on a different model, please
[open an issue](https://github.com/lorenzo-deluca/homeassistant-70mai/issues)
or a discussion saying which model, whether it has the 4G/SIM add-on,
and which entities showed up** - that's the only way this table (and the
"supported devices" story in general) grows beyond one data point.

## Features

- **`device_tracker`**: live GPS position for any cloud-connected
  dashcam on the account.
- **`sensor`**: car battery voltage (from telemetry history), last
  report time, raw device/SIM/geofence status, cellular modem firmware
  version, SIM IMEI, account country, and the dashcam's current
  firmware version.
- **`event`**: fires whenever a new dashcam alarm (motion/impact
  detection, etc.) is reported.

All of these are added automatically for every device found on the
account, no manual entity configuration needed.

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

## ⚠️ Exclusive account access: the 70mai app and this integration fight over one login

**70mai's cloud API only allows one active session per account at a
time.** There's no separate "API session" vs "app session" - logging
into the 70mai mobile app invalidates whatever session was already
active, including this integration's. The reverse is just as true: if
the integration logs back in while you're using the app, *your app*
gets logged out instead. This is a property of 70mai's backend, not
something this integration can opt out of.

What this integration does about it:

- Every poll checks whether 70mai's response says the session was
  invalidated (a specific error code/message 70mai returns instead of
  just rejecting the request). It doesn't guess based on missing data,
  so it won't confuse "this device has no GPS" with "we got logged
  out."
- When that happens, it logs a **warning** in Home Assistant's log
  explaining what happened, then **waits 5 minutes before logging back
  in** instead of retrying immediately. Logging back in right away would
  just immediately kick your app session back out, which is exactly the
  annoying loop this delay avoids.
- Entities will stop updating (and eventually show as unavailable) for
  that ~5 minute window, then recover on their own once the integration
  logs back in - no action needed on your part, and a second warning is
  logged once it's back.

In practice: opening the 70mai app to check on your dashcam will cause a
short (~5 minute) gap in this integration's data every time, and if you
need the app open for longer (e.g. to watch a live view), expect the
integration to keep waiting/retrying quietly in the background rather
than fighting the app for the session. Check **Settings → System →
Logs** (or your `configuration.yaml` logger settings for
`custom_components.mai70`) if you want to see this happening.

## Entities

Per discovered dashcam (device name = the nickname set in the 70mai app,
falling back to its WiFi SSID):

| Platform         | Entity                            | Notes |
| ---------------- | ---------------------------------- | ----- |
| `device_tracker` | *Device* Position                  | GPS source, only created for devices that actually report a position. |
| `sensor`         | *Device* Battery voltage            | Car battery voltage in volts. The unit is a strong inference from the raw telemetry (not officially documented by 70mai); the entity attributes flag this via `unit_confirmed: false`. |
| `sensor`         | *Device* Last report                | Diagnostic timestamp of the last time the dashcam reported to the cloud (`getDashcamDetail`'s `device.reportTime`). |
| `sensor`         | *Device* Status                     | Diagnostic passthrough of `getDashcamDetail`'s `deviceStatus` (plus `simPluginActiveStatus`/`geofenceActiveStatus` as attributes). Field names are confirmed but the exact value meaning isn't, so this exposes the raw value rather than an on/off state; flagged via `value_confirmed: false`. |
| `sensor`         | *Device* Cellular firmware version | Diagnostic firmware version of the cellular add-on (`getSimPluginDetail`'s `pluginSoftwareVersion`, with the sub-version as an attribute). Only created for devices that actually have a SIM plugin (detected empirically, like Position). |
| `sensor`         | *Device* SIM                        | Diagnostic SIM identity: IMEI as the state, plugin device id and beta-device flag as attributes (`getSimPluginDetail`). Same 4G-only gating as Cellular firmware version. |
| `sensor`         | *Device* Country                    | Diagnostic account country code (`getUserCountryCode`). Account-level, so the same value is shown on every device on the account. |
| `sensor`         | *Device* Firmware version            | Diagnostic current firmware version installed on the dashcam (`checkNewRomFromApp`'s `resultBodyObject.version`, confirmed to report the device's own installed firmware rather than the request's `base_version`), with release notes/date/size as attributes. |
| `event`          | *Device* Alarm                      | Fires a generic `alarm` event per new alarm, with the raw alarm payload as an attribute (specific alarm-type meanings aren't confirmed yet). |

Polling runs every 5 minutes by default.

## Example Lovelace dashboard

[`examples/lovelace.yaml`](./examples/lovelace.yaml) is a ready-to-paste
dashboard covering every entity above: a map for the live position, an
at-a-glance status/battery/last-report card, a 24h battery voltage
graph, a connectivity/firmware diagnostics card, and an alarm logbook.
It only uses Lovelace's built-in cards (`map`, `glance`, `entities`,
`history-graph`, `logbook`) - no HACS frontend cards required - plus an
optional, commented-out
[`mini-graph-card`](https://github.com/kalkih/mini-graph-card) battery
graph for a nicer look, the same card used by
[noiwid/silence-scooter-homeassistant](https://github.com/noiwid/silence-scooter-homeassistant)'s
dashboard if you already have it installed.

Open the file for the exact steps (paste it into a new dashboard's raw
configuration editor after swapping in your device's own entity slugs).

## Sending positions to Traccar

If you already run a [Traccar](https://www.traccar.org/) server, my other
project [homeassistant-traccar](https://github.com/lorenzo-deluca/homeassistant-traccar)
forwards any Home Assistant `device_tracker` entity's position to it, so
you can feed this integration's `device_tracker.<device>_position`
entity straight into Traccar for fleet-style tracking/history alongside
your other GPS sources. It works as an HA automation blueprint (no
Python/custom component involved): install its `rest_command` package,
import the blueprint, and pick this integration's position entity/-ies
in the blueprint's `device_trackers` input.

Two things to know when pairing it with this integration:
- Traccar's device "Identifier" must match the HA entity_id you select
  (e.g. `device_tracker.rearview_mirror_position`), not just the device
  name - see that project's README.
- The blueprint auto-fills Traccar's battery field from a
  `sensor.<object_id>_battery_level`-named entity if one exists. This
  integration's battery sensor is named `..._battery_voltage` and
  reports **volts**, not a percentage, so it won't be picked up
  automatically (and shouldn't be renamed to `_battery_level`, since
  that would misrepresent a voltage as a charge percentage) - Traccar
  will just report battery as 0 unless you add your own template sensor
  to translate it.

## Known limitations

- The 70mai API is unofficial and reverse-engineered, so some data (like
  the battery sensor's unit, or alarm-type meanings) is a best-effort
  inference rather than a documented contract. Check
  [`70maiclient`](https://github.com/lorenzo-deluca/70maiclient)'s own
  docstrings for what is and isn't confirmed at the API level.
- No options flow yet to change the poll interval from the UI.

## Work in progress

- Options flow for scan interval / alarm filtering.
- Additional entities from `70maiclient` methods whose response shape
  isn't confirmed yet (e.g. device switches, value-added-service
  status). PRs welcome.

## Other integrations by me

- [homeassistant-silence](https://github.com/lorenzo-deluca/homeassistant-silence): Home Assistant integration for Silence electric scooters.
- [homeassistant-traccar](https://github.com/lorenzo-deluca/homeassistant-traccar): forwards Home Assistant `device_tracker` positions to a Traccar server.

## License

GNU AGPLv3 © Lorenzo De Luca
