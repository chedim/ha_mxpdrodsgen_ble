# MaxPeedingRods Generator — Home Assistant (BLE, local)

A Home Assistant integration for **MaxPeedingRods inverter generators** that use
the MXR Home / Tuya Bluetooth LE protocol (tested on the **MXR4000 GT**,
model `MXR4000GT-BL`, Tuya category `qt`, product `jlblyn8z`).

It talks to the generator **directly over Bluetooth LE** — through any Home
Assistant Bluetooth adapter or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html).
**No cloud connection is made at runtime.** The Tuya cloud is only used **once**,
by you, to read out the device's local key (see below); after that everything is
local.

> This integration is a trimmed, generator-only fork of the excellent
> [ha-tuya-ble/ha_tuya_ble](https://github.com/ha-tuya-ble/ha_tuya_ble), with the
> cloud login removed in favour of entering the key by hand. All of the BLE
> protocol/crypto is their work — see [Credits](#credits).

## Entities

| Entity | DP | Notes |
|--------|----|-------|
| Generator (switch) | 101 | Start / stop |
| ECO mode (switch) | 108 | |
| Power output | 104 | W |
| Load | 102 | % |
| Voltage | 110 | V |
| Frequency | 111 | Hz |
| Engine speed | 112 | rpm |
| Run time | 103 | minutes since start |
| Total run time | 105 | minutes (lifetime) |
| Starter battery | 115 | % |
| Link state | 106 | offline / online / protected |
| Fault code | 107 | raw bitmap |
| Charging capacity | 116 | raw |
| Serial number | 114 | |

Scaling is assumed 1:1 from the Tuya data model. If a value looks off by a
factor of ten, open an issue with the reading — it's a one-line coefficient fix.

## Install

1. **HACS** → ⋮ → *Custom repositories* → add `https://github.com/chedim/ha_mxpdrodsgen_ble`
   as an *Integration*, then install it and restart Home Assistant. (Or copy
   `custom_components/mxpdrodsgen_ble/` into your HA `config/custom_components/`.)
2. **Settings → Devices & Services → Add Integration → "MaxPeedingRods Generator"**.
3. Pick the generator from the discovered Bluetooth list (or type its MAC), then
   enter the three values from the step below.

## Getting the local key (one time)

The generator encrypts all BLE traffic with a per-device key that is not
broadcast. You retrieve it once from the Tuya cloud:

1. Add the generator to the **Smart Life** app (Bluetooth; close the MXR Home app
   first so it isn't holding the single BLE connection).
2. Create a free project at [iot.tuya.com](https://iot.tuya.com) in the
   **Western America** data centre, then **Devices → Link App Account** and scan
   the QR with Smart Life.
3. Read the device's **Device ID**, **Local key** and **UUID** (via *Devices →
   Device Details*, or the cloud API `GET /v1.0/iot-01/associated-users/devices`).
4. Enter those three in the integration's setup form. You can then delete the
   Tuya project — nothing contacts the cloud again.

## Credits

- BLE protocol, crypto and the entire device stack:
  [ha-tuya-ble/ha_tuya_ble](https://github.com/ha-tuya-ble/ha_tuya_ble) and the
  upstream [PlusPlus-ua/ha_tuya_ble](https://github.com/PlusPlus-ua/ha_tuya_ble),
  MIT licensed. See `custom_components/mxpdrodsgen_ble/LICENSE.tuya_ble`.
- Generator data-point mapping: this repo.

> 🤖 The generator mapping and the local-only config flow in this fork were
> written with the help of Claude (Claude Code).

## License

MIT — see [LICENSE](LICENSE).
