"""Phase 6 edge units: register decoding, Modbus poller, MQTT adapter, buffer + forwarder."""

import json
import struct
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from edge import canonical
from edge.canonical import CanonicalError
from edge.gateway.buffer import Buffer
from edge.gateway.forwarder import Forwarder
from edge.modbus.device import MockModbusDevice
from edge.modbus.poller import ModbusPoller
from edge.modbus.registers import RegisterSpec, decode, encode, load_map, raw_value
from edge.mqtt.adapter import parse_topic, to_records

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


# ---------- registers ----------

def test_word_and_byte_order_against_known_vectors():
    # 123.456 as IEEE-754 float32 is 0x42F6E979.
    abcd = RegisterSpec("x", 0, "float32", word_order="big")
    cdab = RegisterSpec("x", 0, "float32", word_order="little")
    badc = RegisterSpec("x", 0, "float32", word_order="big", byte_order="little")
    assert raw_value(abcd, [0x42F6, 0xE979]) == pytest.approx(123.456, rel=1e-6)
    assert raw_value(cdab, [0xE979, 0x42F6]) == pytest.approx(123.456, rel=1e-6)
    assert raw_value(badc, [0xF642, 0x79E9]) == pytest.approx(123.456, rel=1e-6)
    # The same registers read with the wrong word order give a different number.
    assert raw_value(cdab, [0x42F6, 0xE979]) != pytest.approx(123.456, rel=1e-3)
    assert raw_value(RegisterSpec("x", 0, "int32"), [0xFFFF, 0xFFFE]) == -2
    assert raw_value(RegisterSpec("x", 0, "int16"), [0x8000]) == -32768
    assert raw_value(RegisterSpec("x", 0, "uint32", "little"), [0x5678, 0x1234]) == 0x12345678


def test_encode_decode_roundtrip_every_layout():
    for dt, v in (("uint16", 54321), ("int16", -1234), ("uint32", 305419896),
                  ("int32", -305419896), ("float32", -1234.5)):
        for wo in ("big", "little"):
            for bo in ("big", "little"):
                s = RegisterSpec("x", 0, dt, wo, bo)
                assert raw_value(s, encode(s, v)) == v


def test_mapping_unit_conversion_and_invalid_values():
    specs = load_map([
        {"field": "voltage_v", "address": 10, "dtype": "uint16", "scale": 0.1, "min": 0, "max": 600,
         "invalid": [65535]},
        {"field": "energy_kwh", "address": 11, "dtype": "uint32", "word_order": "little",
         "scale": 0.001, "min": 0},
        {"field": "current_a", "address": 13, "dtype": "uint16", "scale": 0.01, "max": 600},
        {"field": "power_factor", "address": 14, "dtype": "int16", "scale": 0.001, "min": 0, "max": 1},
    ])
    block = {10: 4150, 11: 0x5678, 12: 0x1234, 13: 12345, 14: 850}
    fields, issues = decode(specs, block)
    assert fields == {"voltage_v": 415.0, "energy_kwh": pytest.approx(305419.896),
                      "current_a": 123.45, "power_factor": 0.85}
    assert issues == []
    bad = {10: 65535, 11: 0x5678, 12: 0x1234, 13: 12345, 14: 1500}  # sentinel + PF 1.5
    fields, issues = decode(specs, bad)
    assert fields["voltage_v"] is None and fields["power_factor"] is None
    assert any("not available" in i for i in issues) and any("outside" in i for i in issues)
    fields, issues = decode(specs, {10: 4150})
    assert fields["energy_kwh"] is None and any("not read" in i for i in issues)


def test_float_nan_register_is_rejected():
    nan = struct.unpack(">HH", struct.pack(">f", float("nan")))
    fields, issues = decode([RegisterSpec("reactive_power_kvar", 0, "float32")], {0: nan[0], 1: nan[1]})
    assert fields["reactive_power_kvar"] is None and issues


# ---------- poller ----------

def _meter():
    specs = load_map([{"field": "voltage_v", "address": 0, "scale": 0.1},
                      {"field": "energy_kwh", "address": 1, "dtype": "uint32", "scale": 0.001}])
    return MockModbusDevice({0: 4150, 1: 0, 2: 12000}), specs


def test_poller_emits_canonical_record():
    dev, specs = _meter()
    rec = ModbusPoller("compressor-01", dev, specs).poll(NOW)
    assert rec == {"machine_id": "compressor-01", "ts": NOW.isoformat(), "source": "MEASURED",
                   "voltage_v": 415.0, "energy_kwh": 12.0}


@pytest.mark.parametrize("mode,state", [("timeout", "TIMEOUT"), ("unavailable", "UNAVAILABLE")])
def test_poller_failure_backoff_and_reconnect(mode, state):
    dev, specs = _meter()
    p = ModbusPoller("compressor-01", dev, specs, backoff_min_s=2, backoff_max_s=8)
    dev.fail = mode
    assert p.poll(NOW) is None and p.state == state and p.failures == 1
    reads = dev.reads
    assert p.poll(NOW + timedelta(seconds=1)) is None and dev.reads == reads  # backing off
    assert p.poll(NOW + timedelta(seconds=3)) is None and p.failures == 2     # retried, failed
    assert p.next_attempt == NOW + timedelta(seconds=3 + 4)                   # doubled delay
    dev.fail = None
    rec = p.poll(NOW + timedelta(seconds=8))                                  # device back
    assert rec is not None and p.state == "CONNECTED" and p.failures == 0


# ---------- MQTT adapter ----------

def test_topics():
    assert parse_topic("joulemitra/site-1/furnace-01/telemetry") == ("telemetry", "site-1", "furnace-01")
    assert parse_topic("joulemitra/site-1/production") == ("production", "site-1", None)
    with pytest.raises(CanonicalError):
        parse_topic("joulemitra/site-1/furnace-01/debug")


def test_payload_single_and_batch():
    t = "joulemitra/s/furnace-01/telemetry"
    kind, recs = to_records(t, json.dumps({"ts": NOW.isoformat(), "power_kw": 50,
                                           "machine_state": "melting"}).encode())
    assert kind == "telemetry" and recs[0]["machine_id"] == "furnace-01"
    assert recs[0]["source"] == "MEASURED" and recs[0]["power_kw"] == 50.0
    _, recs = to_records(t, json.dumps({"records": [{"ts": NOW.isoformat(), "power_kw": 1},
                                                    {"ts": NOW.isoformat(), "power_kw": 2}]}).encode())
    assert len(recs) == 2


@pytest.mark.parametrize("payload", [
    b"{not json", b"\xff\xfe", b"[1, 2]", json.dumps({"power_kw": 5}).encode(),
    json.dumps({"ts": "2026-09-27T12:00:00", "power_kw": 5}).encode(),
    json.dumps({"ts": NOW.isoformat(), "power_kw": "high"}).encode(),
    json.dumps({"ts": NOW.isoformat(), "flux_capacitor": 1}).encode(),
    json.dumps({"ts": NOW.isoformat(), "machine_id": "pump-01"}).encode(),
    json.dumps({"ts": NOW.isoformat(), "source": "GUESS"}).encode(),
])
def test_malformed_payloads_raise(payload):
    with pytest.raises(CanonicalError):
        to_records("joulemitra/s/furnace-01/telemetry", payload)


# ---------- buffer + forwarder ----------

def _rec(i, machine="furnace-01"):
    return canonical.telemetry(machine, NOW + timedelta(minutes=i), "SIMULATED", {"power_kw": 10.0 + i})


def _fill(buf, n, machine="furnace-01"):
    for i in range(n):
        r = _rec(i, machine)
        buf.enqueue("telemetry", canonical.dedup_key("telemetry", r), r)


def _client(handler):
    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


def test_buffer_dedup_and_persistence(tmp_path):
    path = str(tmp_path / "b.db")
    b = Buffer(path)
    r = _rec(0)
    assert b.enqueue("telemetry", canonical.dedup_key("telemetry", r), r) is True
    assert b.enqueue("telemetry", canonical.dedup_key("telemetry", r), r) is False
    b.close()
    b2 = Buffer(path)  # gateway restart
    assert b2.counts()["pending"] == 1


def test_api_down_keeps_data_then_delivers_in_order(tmp_path):
    buf = Buffer(str(tmp_path / "b.db"))
    _fill(buf, 5)
    up = {"on": False}
    seen = []

    def handler(req):
        if not up["on"]:
            raise httpx.ConnectError("refused")
        recs = json.loads(req.content)["records"]
        seen.extend(r["ts"] for r in recs)
        return httpx.Response(200, json={"accepted": len(recs), "suspect": 0, "bad": 0, "duplicate": 0})

    fwd = Forwarder(buf, "http://api", batch_size=2, backoff_min_s=0, client=_client(handler))
    fwd.flush()
    assert fwd.state == "API_UNAVAILABLE" and buf.counts()["pending"] == 5  # nothing discarded
    up["on"] = True
    fwd.flush()
    assert buf.counts() == {"pending": 0, "dead_letter": 0, "delivered": 5}
    assert seen == sorted(seen) and fwd.results["accepted"] == 5
    # A replayed (e.g. retained) message that was already delivered is not re-queued.
    r = _rec(0)
    assert buf.enqueue("telemetry", canonical.dedup_key("telemetry", r), r) is False


def test_server_error_is_retried_not_dropped(tmp_path):
    buf = Buffer(str(tmp_path / "b.db"))
    _fill(buf, 2)
    fwd = Forwarder(buf, "http://api", backoff_min_s=0,
                    client=_client(lambda req: httpx.Response(503, json={"detail": "db down"})))
    fwd.flush()
    assert buf.counts()["pending"] == 2 and buf.counts()["dead_letter"] == 0
    assert "503" in fwd.last_error


def test_bad_record_isolated_to_dead_letter(tmp_path):
    buf = Buffer(str(tmp_path / "b.db"))
    _fill(buf, 3)
    _fill(buf, 1, machine="ghost-99")

    def handler(req):
        recs = json.loads(req.content)["records"]
        if any(r["machine_id"] == "ghost-99" for r in recs):
            return httpx.Response(404, json={"detail": "Unknown machine_id(s): ghost-99"})
        return httpx.Response(200, json={"accepted": len(recs), "suspect": 0, "bad": 0, "duplicate": 0})

    fwd = Forwarder(buf, "http://api", batch_size=10, client=_client(handler))
    fwd.flush()
    assert buf.counts() == {"pending": 0, "dead_letter": 1, "delivered": 3}
    dl = buf.dead_letters()[0]
    assert "ghost-99" in dl["raw"] and "404" in dl["reason"]
