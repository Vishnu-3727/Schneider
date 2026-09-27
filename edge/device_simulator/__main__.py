"""Simulated field devices for the edge gateway (SIMULATED data, clearly labelled).

  mqtt          ESP32-style sensor nodes: publish SimulatedFactory telemetry
                (source SIMULATED) to joulemitra/{site}/{machine}/telemetry and
                hourly production to joulemitra/{site}/production.
  modbus-meter  A simulated 3-phase energy meter served over Modbus TCP,
                registers laid out per edge/config/energy_meter_map.json and
                updated every second from the simulator's machine model.

    python -m edge.device_simulator mqtt --machines furnace-01,pump-01 --hours 2 --burst
    python -m edge.device_simulator modbus-meter --machine compressor-01 --port 5020

The same readings reach the backend through the gateway as through the
direct HTTP simulator path, which is the point: the analytics cannot tell them
apart, except by the source tag each record carries.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory
from apps.simulator.machine_models import make_machine
from edge.modbus.registers import encode, load_map

MAP_PATH = Path(__file__).resolve().parents[1] / "config" / "energy_meter_map.json"


def publish_mqtt(a) -> None:
    import paho.mqtt.client as mqtt

    specs = [m for m in DEFAULT_MACHINES if m.machine_id in a.machines.split(",")]
    tel, prod = SimulatedFactory(specs, hours=a.hours, step_s=a.step_s, seed=a.seed,
                                 end=datetime.now(ZoneInfo("Asia/Kolkata"))).run()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jm-sim-node")
    c.connect(a.host, a.port)
    c.loop_start()
    for rec in sorted(tel, key=lambda r: r["ts"]):
        body = {k: v for k, v in rec.items() if k != "machine_id" and v is not None}
        c.publish(f"joulemitra/{a.site}/{rec['machine_id']}/telemetry", json.dumps(body), qos=1).wait_for_publish()
        if not a.burst:
            time.sleep(a.step_s)
    for p in prod:
        c.publish(f"joulemitra/{a.site}/production", json.dumps(p), qos=1).wait_for_publish()
    c.loop_stop()
    c.disconnect()
    print(f"published {len(tel)} telemetry + {len(prod)} production messages")


class MeterRegisters:
    """Machine model -> meter registers (one encode per mapped field)."""

    def __init__(self, machine_id: str, seed: int) -> None:
        spec = next(m for m in DEFAULT_MACHINES if m.machine_id == machine_id)
        self.model = make_machine(spec.machine_id, spec.machine_type, spec.rated_power_kw,
                                  np.random.default_rng(seed))
        self.specs = load_map(json.loads(MAP_PATH.read_text(encoding="utf-8"))["registers"])
        self.i = 0

    def step(self, dt_s: float = 1.0) -> dict[int, int]:
        s = self.model.step(self.i, dt_s / 3600.0)
        self.i += 1
        raw = {"voltage_v": s.voltage_v / 0.1, "current_a": s.current_a / 0.01,
               "power_kw": s.power_kw / 0.001, "power_factor": s.power_factor / 0.001,
               "energy_kwh": s.energy_kwh / 0.001, "reactive_power_kvar": s.reactive_power_kvar}
        regs: dict[int, int] = {}
        for sp in self.specs:
            v = raw[sp.field]
            for k, w in enumerate(encode(sp, v if sp.dtype == "float32" else math.floor(v + 0.5))):
                regs[sp.address + k] = w
        return regs


def serve_meter(a) -> None:
    from edge.modbus.tcp_server import SimulatedModbusServer

    meter = MeterRegisters(a.machine, a.seed)
    srv = SimulatedModbusServer(a.port, unit_id=a.device_id, host="0.0.0.0")
    srv.set(meter.step(1.0))
    srv.start()
    print(f"simulated meter for {a.machine} on :{a.port} (unit {a.device_id}); Ctrl+C to stop")
    try:
        while True:
            time.sleep(1.0)
            srv.set(meter.step(1.0))
    except KeyboardInterrupt:
        srv.stop()

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mqtt")
    m.add_argument("--host", default="localhost")
    m.add_argument("--port", type=int, default=1883)
    m.add_argument("--site", default="demo-foundry-01")
    m.add_argument("--machines", default="furnace-01,pump-01")
    m.add_argument("--hours", type=float, default=1.0)
    m.add_argument("--step-s", type=int, default=60)
    m.add_argument("--seed", type=int, default=1)
    m.add_argument("--burst", action="store_true", help="publish as fast as possible")
    mm = sub.add_parser("modbus-meter")
    mm.add_argument("--machine", default="compressor-01")
    mm.add_argument("--port", type=int, default=5020)
    mm.add_argument("--device-id", type=int, default=1)
    mm.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    publish_mqtt(a) if a.cmd == "mqtt" else serve_meter(a)


if __name__ == "__main__":
    main()
