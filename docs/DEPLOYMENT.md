# JouleMitra — Edge deployment (Phase 6)

```text
field device ─┬─ Modbus TCP (energy meter) ─┐
              ├─ MQTT (ESP32 sensor node) ──┤
              └─ simulator (HTTP, direct) ──┤
                                            ▼
                     protocol adapter → canonical telemetry
                                            ▼
                     SQLite store-and-forward buffer (edge_buffer.db)
                                            ▼
                     POST /telemetry, /production (JouleMitra API)
                                            ▼
                     same validation → PostgreSQL → same analytics
```

The analytics consume only canonical JouleMitra telemetry (the API
schema). Registers, topics and payload formats end at the adapter
(`edge/modbus`, `edge/mqtt`). The `edge` package never imports the
backend: it is deployed on its own (a PC or a Raspberry Pi) and talks to the
backend over HTTP only.

## Run it

```bash
pip install -e .[edge]                 # paho-mqtt, pymodbus, httpx
docker compose up -d db mqtt backend   # broker on :1883
python -m edge.device_simulator modbus-meter --machine compressor-01 --port 5020   # SIMULATED meter
python -m edge.gateway --config edge/config/gateway.example.json                    # the gateway
python -m edge.device_simulator mqtt --machines furnace-01,pump-01 --hours 0.2 --step-s 30 --burst
python -m edge.gateway --config edge/config/gateway.example.json --status           # buffer / state
```

The gateway writes `edge_status.json` every loop (atomically). It holds the
MQTT connection, each Modbus device's state (CONNECTED / TIMEOUT /
UNAVAILABLE, failures, next retry, decode issues), the API state (OK /
API_UNAVAILABLE, last error, accepted / suspect / bad / duplicate counts) and
the buffer counts (pending / dead_letter / delivered).

## MQTT

- Topics: `joulemitra/{site_id}/{machine_id}/telemetry` (one reading or
  `{"records": [...]}`) and `joulemitra/{site_id}/production`.
- Payload keys are the canonical field names (`power_kw`, `energy_kwh`, …)
  plus `ts` (ISO-8601 with offset), `machine_state` and `source`
  (default MEASURED). Unknown keys, a naive `ts`, non-numeric values or a
  `machine_id` that contradicts the topic are malformed.
- QoS 1 with a persistent session (`clean_session=False`, a fixed client id),
  so messages published while the gateway is down are delivered when it
  returns. Duplicates are expected. The buffer's key (kind|machine|ts) and
  the backend's (machine, ts) uniqueness absorb them.
- A retained last value, replayed on subscribe, goes through the same dedup
  and is not re-sent if it was already delivered.
- Reconnect: paho retries with 1–30 s backoff and re-subscribes on every
  connect. An unreachable broker never crashes the gateway.

## Modbus

- The register map is data: `edge/config/energy_meter_map.json` (an
  ILLUSTRATIVE layout). For a real meter, copy its manual's register table:
  address, dtype (uint16/int16/uint32/int32/float32), word order ("big" =
  ABCD, "little" = CDAB), byte order (for BADC/DCBA devices), scale and
  offset for unit conversion (e.g. Wh → kWh = 0.001), plausible min/max,
  and the vendor's "not available" sentinels.
- A sentinel, non-finite or out-of-range register becomes `null` plus an
  issue in the status. It is never forwarded as a number.
- A timeout or unavailable device produces no reading that cycle, and the
  poller backs off exponentially (1 s → 60 s). The next successful read
  reconnects. Readings are timestamped at the gateway (tz-aware UTC).
- `edge/modbus/tcp_server.py` is a small spec-conformant Modbus TCP
  server (function 03 and exception responses) used for the SIMULATED meter
  and the tests. It is independent of pymodbus, so the pymodbus client is
  checked against a separate implementation.

## Buffer and delivery

- Every canonical record is written to SQLite before any network I/O. The
  file survives gateway restarts.
- Delivery removes a record only on 2xx, or moves it to `dead_letter` on a
  definitive rejection. A 4xx batch is retried one record at a time so one
  bad record (e.g. an unknown machine → 404) never blocks the others.
  Connection errors and 5xx keep everything, with exponential backoff.
- The live path posts without `backfill`, so the backend's stale,
  out-of-order and duplicate checks apply exactly as for any other source.

## Plant deployment checklist (not done in the prototype)

- Mosquitto: `allow_anonymous false`, `password_file`, a TLS listener
  (8883), per-device credentials. The gateway reads `MQTT_USERNAME` /
  `MQTT_PASSWORD` from the environment (never from the config file).
  `edge/mosquitto/mosquitto.conf` is DEV ONLY.
- Confirm the meter's register table, word order and scaling on site with a
  reference reading before trusting a single value.
- Set `source` to MEASURED only for real devices. Simulated devices must stay
  SIMULATED.
- Run the gateway as a service (systemd on a Raspberry Pi), with the buffer
  on persistent storage, and monitor `edge_status.json`.
- The `delivered` dedup table grows with every record. Prune rows older
  than the redelivery horizon (e.g. 7 days) on a schedule.
