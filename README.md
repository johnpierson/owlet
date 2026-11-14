# Owlet Custom Integration (maintained fork)

[![Validate](https://github.com/johnpierson/owlet/actions/workflows/validate.yml/badge.svg)](https://github.com/johnpierson/owlet/actions/workflows/validate.yml)
[![Tests](https://github.com/johnpierson/owlet/actions/workflows/tests.yml/badge.svg)](https://github.com/johnpierson/owlet/actions/workflows/tests.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom component for the Owlet Smart Sock (Smart Sock 2, Smart Sock 3 / Dream Sock).

This is a fork of [ryanbdclark/owlet](https://github.com/ryanbdclark/owlet), which was archived in 2025 and no longer loads cleanly on current Home Assistant releases. The fork keeps the same domain (`owlet`) and the same entity unique IDs, so it is a drop-in replacement. See the [changelog](CHANGELOG.md) for what was fixed.

> **Not a medical device, and not a replacement for the Owlet app.** This integration reads an unofficial cloud API that can change or stop at any time. Do not rely on Home Assistant for alerts about your child.

## Installation

1. In [HACS](https://hacs.xyz/), open the menu (⋮) > **Custom repositories**, add `https://github.com/johnpierson/owlet` with type **Integration**.
2. Search HACS for "Owlet" and download it. If you had the original integration installed, remove its HACS entry first (keep the integration configured in Home Assistant, your entities are preserved).
3. Restart Home Assistant.
4. [![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=owlet) or go to **Settings > Devices & services > Add integration** and search for "Owlet Smart Sock".
5. Pick your region (`world` or `europe`) and sign in with your Owlet account. Only tokens are stored, never the password.

Manual install: copy `custom_components/owlet` into your Home Assistant `config/custom_components` folder and restart.

Requires Home Assistant 2026.1 or newer.

## Entities

- **Sensors** - heart rate, oxygen saturation, 10 minute oxygen average, skin temperature, sleep state, battery level, battery time remaining, signal strength. Movement, movement bucket and "Last vitals update" are created disabled.
- **Binary sensors** - charging, awake, sock off, sock disconnected, and the high/low heart rate, high/low/critical oxygen, low/critical battery and lost power alerts.
- **Readings stale** (binary sensor, Smart Sock 3) - turns on when the Owlet cloud has not received new vitals from the base station for 5 minutes. While it is on, the vitals sensors become unavailable instead of showing frozen numbers. Restarting the base station is the usual cure. Use this entity to get notified.
- **Switch** - base station on/off.

Vitals are unavailable while the sock is charging.

## Options

- **Polling interval** - seconds between calls to the Owlet cloud, default 5, minimum 5. Changes apply immediately.

## Troubleshooting

- *Email, password or region is incorrect* - Owlet no longer says which one is wrong. Try the other region before resetting the password.
- Download diagnostics from the integration page before opening an issue; tokens and your email are redacted.
- Debug logging: enable it from the integration page, or set `custom_components.owlet: debug` under `logger:`.

## Development

```
uv venv && uv pip install -r requirements_test.txt
pytest
```

The tests run the integration inside a real Home Assistant test instance against a fake Owlet cloud. Home Assistant does not run on Windows; use Linux, macOS or WSL.

## Credits

Original integration and `pyowletapi` by [Ryan Clark (@ryanbdclark)](https://github.com/ryanbdclark). Licensed under Apache-2.0.
