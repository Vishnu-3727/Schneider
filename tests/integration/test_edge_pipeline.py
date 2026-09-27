"""Phase 6 acceptance: device -> protocol adapter -> canonical -> buffer -> API -> DB.

Real Mosquitto broker (docker compose service `mqtt`, localhost:1883), real
Modbus TCP (edge.modbus.tcp_server + the pymodbus client), real backend
(the pytest TestClient is the gateway's HTTP client) on the test database.
"""

import json
import socket
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import paho.mqtt.client as paho
import pytest

from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory
from edge import canonical
from edge.device_simulator.__main__ import MAP_PATH, MeterRegisters
from edge.gateway.buffer import Buffer
from edge.gateway.forwarder import Forwarder
from edge.modbus.device import PymodbusTcpDevice
from edge.modbus.poller import ModbusPoller
from edge.modbus.registers import load_map
from edge.modbus.tcp_server import SimulatedModbusServer
from edge.mqtt.client import MqttIngest

SITE = "demo-foundry-01"
BROKER = ("localhost", 1883)


def _broker_up() -> bool:
    try:
        with socket.create_connection(BROKER, timeout=1):
            return True
    except OSError:
        return False


needs_broker = pytest.mark.skipif(not _broker_up(),
                                  reason="MQTT broker not running (docker compose up -d mqtt)")


def _wait(pred, timeout=15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


def _publisher():
    c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"test-pub-{uuid.uuid4()}")
    c.connect(*BROKER)
    c.loop_start()
    return c


def _ingest(buf, port=BROKER[1]):
    ing = MqttIngest(buf, BROKER[0], port, client_id=f"test-gw-{uuid.uuid4()}")
    ing.start()
    return ing


def _fresh_telemetry(machine="furnace-01", minutes=10, step_s=30, seed=3):
    spec = {"furnace-01": ("furnace", 150.0), "pump-01": ("pump", 15.0)}[machine]
    tel, prod = SimulatedFactory([MachineSpec(machine, *spec)], hours=minutes / 60, step_s=step_s,
                                 seed=seed, end=datetime.now(ZoneInfo("Asia/Kolkata"))).run()
    return tel, prod


def _rows(client, machine):
    return client.get("/telemetry", params={"machine_id": machine, "limit": 10000}).json()


# ---------------- Modbus ----------------

def test_modbus_meter_end_to_end_with_outage_and_reconnect(client, tmp_path):
    port = 5041
    meter = MeterRegisters("compressor-01", seed=5)
    srv = SimulatedModbusServer(port)
    srv.set(meter.step())
    srv.start()
    specs = load_map(json.loads(MAP_PATH.read_text(encoding="utf-8"))["registers"])
    dev = PymodbusTcpDevice("127.0.0.1", port, 1, timeout_s=1.0)
    poller = ModbusPoller("compressor-01", dev, specs, source="SIMULATED", backoff_min_s=0.5)
    buf = Buffer(str(tmp_path / "gw.db"))
    fwd = Forwarder(buf, "http://unused", client=client)
    t0 = datetime.now(UTC)
    try:
        expected = []
        for k in range(3):
            regs = meter.step(60.0)
            srv.set(regs)
            rec = poller.poll(t0 + timedelta(seconds=60 * k))
            assert rec is not None and poller.state == "CONNECTED"
            assert buf.enqueue("telemetry", canonical.dedup_key("telemetry", rec), rec)
            expected.append(rec)
        # Unit conversion + word order came through the real protocol intact.
        s = meter.model
        assert expected[-1]["energy_kwh"] == pytest.approx(s.energy_kwh, abs=1e-3)
        assert 380 <= expected[-1]["voltage_v"] <= 450 and 0 < expected[-1]["power_factor"] <= 1
        srv.stop()  # device unavailable
        assert poller.poll(t0 + timedelta(seconds=180)) is None
        assert poller.state in ("UNAVAILABLE", "TIMEOUT")
        srv = SimulatedModbusServer(port)
        srv.set(meter.step(60.0))
        srv.start()
        rec = poller.poll(t0 + timedelta(seconds=240))  # after backoff -> reconnect
        assert rec is not None and poller.state == "CONNECTED" and poller.failures == 0
        buf.enqueue("telemetry", canonical.dedup_key("telemetry", rec), rec)
    finally:
        srv.stop()
        dev.close()
    fwd.flush()
    assert buf.counts() == {"pending": 0, "dead_letter": 0, "delivered": 4}
    rows = _rows(client, "compressor-01")
    assert len(rows) == 4 and {r["source"] for r in rows} == {"SIMULATED"}
    energies = [r["energy_kwh"] for r in sorted(rows, key=lambda r: r["ts"])]
    assert energies == sorted(energies)


# ---------------- MQTT ----------------

@needs_broker
def test_mqtt_path_matches_direct_http_path(client, tmp_path):
    tel, _ = _fresh_telemetry()
    # Path A: simulator -> MQTT -> gateway -> API.
    buf = Buffer(str(tmp_path / "gw.db"))
    ing = _ingest(buf)
    assert ing.connected.wait(10)
    pub = _publisher()
    for rec in tel:
        body = {k: v for k, v in rec.items() if k != "machine_id" and v is not None}
        pub.publish(f"joulemitra/{SITE}/furnace-01/telemetry", json.dumps(body), qos=1).wait_for_publish()
    assert _wait(lambda: ing.stats["records"] == len(tel))
    ing.stop()
    pub.loop_stop()
    Forwarder(buf, "http://unused", client=client).flush()
    via_gateway = sorted(_rows(client, "furnace-01"), key=lambda r: r["ts"])
    # Path B: the same records posted directly.
    from sqlalchemy import text

    from apps.backend import db as dbmod
    with dbmod.get_engine().begin() as c:
        c.execute(text("TRUNCATE telemetry"))
    assert client.post("/telemetry", json={"records": tel}).status_code == 200
    direct = sorted(_rows(client, "furnace-01"), key=lambda r: r["ts"])
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("id", "ingested_at")} for r in rows]
    assert strip(via_gateway) == strip(direct)  # the analytics cannot tell the paths apart


@needs_broker
def test_mqtt_duplicates_malformed_unknown_stale_and_retained(client, tmp_path):
    buf = Buffer(str(tmp_path / "gw.db"))
    ing = _ingest(buf)
    assert ing.connected.wait(10)
    pub = _publisher()
    now = datetime.now(UTC).replace(microsecond=0)
    topic = f"joulemitra/{SITE}/furnace-01/telemetry"
    reading = json.dumps({"ts": now.isoformat(), "power_kw": 60.0, "energy_kwh": 1000.0,
                          "source": "SIMULATED"})
    for _ in range(2):  # duplicate (QoS 1 redelivery / sensor retry)
        pub.publish(topic, reading, qos=1).wait_for_publish()
    pub.publish(topic, b"{broken json", qos=1).wait_for_publish()
    pub.publish(f"joulemitra/{SITE}/ghost-99/telemetry",
                json.dumps({"ts": now.isoformat(), "power_kw": 1.0}), qos=1).wait_for_publish()
    stale = json.dumps({"ts": (now - timedelta(hours=2)).isoformat(), "power_kw": 55.0,
                        "energy_kwh": 900.0, "source": "SIMULATED"})
    pub.publish(topic, stale, qos=1).wait_for_publish()
    assert _wait(lambda: ing.stats["messages"] == 5)
    assert ing.stats["duplicates"] == 1 and ing.stats["dead_letter"] == 1
    fwd = Forwarder(buf, "http://unused", client=client)
    fwd.flush()
    counts = buf.counts()
    assert counts["dead_letter"] == 2 and counts["pending"] == 0  # malformed + unknown machine
    reasons = " | ".join(d["reason"] for d in buf.dead_letters())
    assert "malformed" in reasons and "404" in reasons and "ghost-99" in reasons
    rows = _rows(client, "furnace-01")
    assert len(rows) == 2  # duplicate stored once
    by_ts = {datetime.fromisoformat(r["ts"]): r for r in rows}
    assert by_ts[now - timedelta(hours=2)]["quality"] == "SUSPECT"  # stale, live path
    assert by_ts[now]["quality"] == "GOOD"

    # Retained last-value: a gateway (re)subscribing gets it replayed; it is not re-sent.
    pub.publish(topic, reading, qos=1, retain=True).wait_for_publish()
    time.sleep(0.5)
    ing.stop()
    ing2 = _ingest(buf)
    try:
        assert _wait(lambda: ing2.stats["retained"] >= 1)
        assert ing2.stats["duplicates"] >= 1 and ing2.stats["records"] == 0
    finally:
        ing2.stop()
        pub.publish(topic, b"", qos=1, retain=True).wait_for_publish()  # clear retained
        pub.loop_stop()
    fwd.flush()
    assert len(_rows(client, "furnace-01")) == 2


def test_broker_unavailable_does_not_crash(tmp_path):
    buf = Buffer(str(tmp_path / "gw.db"))
    ing = MqttIngest(buf, "127.0.0.1", 1899, client_id=f"test-{uuid.uuid4()}",
                     reconnect_min_s=1, reconnect_max_s=2)
    ing.start()  # no broker on 1899
    time.sleep(2)
    assert ing.connected.is_set() is False and ing.status()["connected"] is False
    ing.stop()


@needs_broker
def test_mqtt_reconnects_after_broker_restart(client, tmp_path):
    if subprocess.run(["docker", "compose", "ps", "-q", "mqtt"], capture_output=True, check=False).returncode != 0:
        pytest.skip("docker compose not available to restart the broker")
    buf = Buffer(str(tmp_path / "gw.db"))
    ing = MqttIngest(buf, *BROKER, client_id=f"test-gw-{uuid.uuid4()}",
                     reconnect_min_s=1, reconnect_max_s=2)
    ing.start()
    assert ing.connected.wait(10)
    subprocess.run(["docker", "compose", "restart", "mqtt"], check=True, capture_output=True)
    assert _wait(lambda: ing.stats["disconnects"] >= 1, 20)
    assert _wait(lambda: ing.connected.is_set() and ing.stats["connects"] >= 2, 30)
    assert _wait(_broker_up, 20)
    pub = _publisher()
    now = datetime.now(UTC).replace(microsecond=0)
    pub.publish(f"joulemitra/{SITE}/pump-01/telemetry",
                json.dumps({"ts": now.isoformat(), "power_kw": 10.5, "source": "SIMULATED"}),
                qos=1).wait_for_publish()
    assert _wait(lambda: ing.stats["records"] == 1)
    ing.stop()
    pub.loop_stop()
    Forwarder(buf, "http://unused", client=client).flush()
    assert len(_rows(client, "pump-01")) == 1


def test_api_outage_buffers_then_delivers(client, tmp_path):
    buf = Buffer(str(tmp_path / "gw.db"))
    tel, _ = _fresh_telemetry("pump-01", minutes=5, step_s=60)
    for r in tel:
        buf.enqueue("telemetry", canonical.dedup_key("telemetry", r), r)
    down = Forwarder(buf, "http://127.0.0.1:1", timeout_s=1.0, backoff_min_s=0)
    down.flush()
    assert down.state == "API_UNAVAILABLE" and buf.counts()["pending"] == len(tel)
    buf.close()
    buf = Buffer(str(tmp_path / "gw.db"))  # gateway restarted during the outage
    Forwarder(buf, "http://unused", client=client).flush()
    assert buf.counts()["pending"] == 0 and len(_rows(client, "pump-01")) == len(tel)
