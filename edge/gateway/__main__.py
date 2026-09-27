"""JouleMitra edge gateway: MQTT + Modbus -> canonical telemetry -> buffer -> API.

    python -m edge.gateway --config edge/config/gateway.example.json
    python -m edge.gateway --config ... --status     # print buffer/status and exit

Runs until interrupted. Every loop it polls Modbus devices that are due,
flushes the buffer to the API, and writes a JSON status file (MQTT
connection, per-device Modbus state, API state, pending / dead-letter
counts). The same code runs on a PC (simulated devices) or a Raspberry Pi.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from edge import canonical
from edge.gateway.buffer import Buffer
from edge.gateway.forwarder import Forwarder
from edge.modbus.device import PymodbusTcpDevice
from edge.modbus.poller import ModbusPoller
from edge.modbus.registers import load_map

log = logging.getLogger("edge.gateway")


def build(cfg: dict, base: Path):
    buf = Buffer(str(base / cfg.get("buffer_path", "edge_buffer.db")))
    fwd = Forwarder(buf, cfg["api_base"], batch_size=cfg.get("batch_size", 200))
    mqtt = None
    if cfg.get("mqtt"):
        from edge.mqtt.client import MqttIngest

        m = cfg["mqtt"]
        mqtt = MqttIngest(buf, m["host"], m.get("port", 1883), m.get("client_id", "jm-gateway"))
    pollers = []
    for d in cfg.get("modbus", []):
        regs = json.loads((base / d["map"]).read_text(encoding="utf-8"))["registers"]
        dev = PymodbusTcpDevice(d["host"], d.get("port", 502), d.get("device_id", 1),
                                d.get("timeout_s", 2.0))
        pollers.append((ModbusPoller(d["machine_id"], dev, load_map(regs), d.get("source", "MEASURED")),
                        float(d.get("poll_interval_s", cfg.get("poll_interval_s", 5.0)))))
    return buf, fwd, mqtt, pollers


def write_status(path: Path, data: dict) -> None:
    """Atomic replace, so a reader (monitoring, the operator) never sees half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def status(buf, fwd, mqtt, pollers) -> dict:
    return {"at": datetime.now(UTC).isoformat(), "api": fwd.status(),
            "mqtt": mqtt.status() if mqtt else None,
            "modbus": [p.status() for p, _ in pollers], "buffer": buf.counts()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after N seconds (tests/demo)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg_path = Path(a.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = Path(cfg.get("base_dir", ".")).resolve()
    buf, fwd, mqtt, pollers = build(cfg, base)
    status_path = base / cfg.get("status_path", "edge_status.json")
    if a.status:
        print(json.dumps(status(buf, fwd, mqtt, pollers), indent=2))
        return
    if mqtt:
        mqtt.start()
    due = [0.0] * len(pollers)
    t0 = time.monotonic()
    try:
        while a.max_seconds is None or time.monotonic() - t0 < a.max_seconds:
            now = time.monotonic()
            for k, (p, every) in enumerate(pollers):
                if now >= due[k]:
                    due[k] = now + every
                    rec = p.poll()
                    if rec is not None:
                        buf.enqueue("telemetry", canonical.dedup_key("telemetry", rec), rec)
            fwd.flush()
            write_status(status_path, status(buf, fwd, mqtt, pollers))
            time.sleep(float(cfg.get("loop_interval_s", 1.0)))
    except KeyboardInterrupt:
        pass
    finally:
        if mqtt:
            mqtt.stop()
        fwd.flush()
        write_status(status_path, status(buf, fwd, mqtt, pollers))
        log.info("gateway stopped: %s", buf.counts())


if __name__ == "__main__":
    main()
