# JouleMitra — Gateway provisioning checklist (Phase 7, docs only)

Companion to `docs/DEPLOYMENT.md` (edge protocol, buffer, and plant
checklist) and `docs/deployment/WIRING.md` (physical wiring). This file is
the per-site checklist only; it does not repeat the DEPLOYMENT.md protocol
detail. No firmware and no physical hardware are provisioned by this doc.

## 1. Base setup

- [ ] Flash the gateway OS (Raspberry Pi or industrial PC per WIRING.md §1)
  and set a unique hostname (ASSUMPTION: `jm-gateway-<site>` — confirm with
  the plant; record the final hostname below).
- [ ] Set the timezone to Asia/Kolkata and enable NTP/time sync
  (ASSUMPTION: `timedatectl set-timezone Asia/Kolkata` + systemd-timesyncd
  or chrony — verify against the site image). Confirm `timedatectl` shows
  synchronized before trusting any timestamp.
- [ ] Create the service user, install the gateway code, and place the
  SQLite buffer on persistent storage (see `docs/DEPLOYMENT.md` buffer
  section).

Deployed hostname: ____________________ (fill at deploy time).

## 2. Config from the example (never commit secrets)

- [ ] Copy `edge/config/gateway.example.json` to the deploy-time
  `gateway.json` (outside the repo or otherwise uncommitted).
- [ ] Set `api_base` to the plant backend URL.
- [ ] Set each Modbus entry: `machine_id`, transport (`host`/`port` for
  Modbus TCP — the meter itself, or the RS-485-to-TCP converter for an RTU
  meter), `device_id` (slave/unit ID), `map`
  (`edge/config/energy_meter_map.json` or the site-confirmed copy),
  `poll_interval_s`, and `source` = MEASURED for real devices
  (SIMULATED stays only for test devices — DEPLOYMENT.md). There is no
  serial-device transport in the current software (Modbus TCP only).
- [ ] Record the meter's serial settings from its front panel/manual:
  slave ID, baud, parity, stop bits. Baud/parity/stop bits are configured
  on the converter (and the meter), not in `gateway.json`; only the slave
  ID goes into `gateway.json` as `device_id`.

Slave ID: ______ Baud: ______ Parity: ______ Stop bits: ______.

## 3. MQTT credentials and TLS (provided at deploy time)

- [ ] The site provides per-device MQTT credentials and the TLS
  certificate(s) at deploy time. They are never written into `gateway.json`
  or committed to the repo.
- [ ] Export `MQTT_USERNAME` / `MQTT_PASSWORD` in the gateway service
  environment (DEPLOYMENT.md plant checklist: broker with
  `allow_anonymous false`, password file, TLS listener on 8883).
- [ ] Confirm the gateway connects with TLS and its client id matches the
  site's device registry.

## 4. Commissioning checks

- [ ] Register-map check: compare each gateway reading (V, A, kW, PF, kWh,
  kvar per the map in WIRING.md §8) against the meter's own display. Do
  not trust any value until addresses, dtype, word/byte order, scale, and
  sentinels are confirmed on site.
- [ ] Plausibility check: voltage near nominal (415 V LT nominal per
  `docs/ASSUMPTIONS.md` A3), PF in [0, 1], energy counter
  non-decreasing, power sign consistent with CT polarity (WIRING.md §2).
- [ ] Stale-data check: unplug the meter (or stop its poller) and confirm
  the dashboard shows the stale badge with age
  (`last_packet_age_s > STALE_AFTER_S` per ARCHITECTURE.md §6) rather than
  silent zeros. Reconnect and confirm the stream resumes.
- [ ] Buffer check: stop the backend briefly and confirm records buffer in
  SQLite and resync (DEPLOYMENT.md buffer section); monitor
  `edge_status.json`.

Checked by: ____________________ Date: ____________________.
