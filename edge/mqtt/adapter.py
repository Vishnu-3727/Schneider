"""MQTT topic + JSON payload -> canonical records (pure, no network).

Topics (docs/spec MASTER_SPEC §9):
  joulemitra/{site_id}/{machine_id}/telemetry   one reading or {"records": [...]}
  joulemitra/{site_id}/production               one window or {"records": [...]}
Telemetry payload keys are the canonical field names plus "ts",
"machine_state" and "source" (default MEASURED). The machine id comes from
the topic. A payload naming a different machine is malformed.
"""

from __future__ import annotations

import json

from edge import canonical
from edge.canonical import CanonicalError

TELEMETRY_SUB = "joulemitra/+/+/telemetry"
PRODUCTION_SUB = "joulemitra/+/production"


def parse_topic(topic: str) -> tuple[str, str, str | None]:
    """-> (kind, site_id, machine_id or None). Raise CanonicalError when unsupported."""
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "joulemitra" and parts[3] == "telemetry":
        return "telemetry", parts[1], parts[2]
    if len(parts) == 3 and parts[0] == "joulemitra" and parts[2] == "production":
        return "production", parts[1], None
    raise CanonicalError(f"unsupported topic {topic!r}")


def to_records(topic: str, payload: bytes) -> tuple[str, list[dict]]:
    kind, _site, machine = parse_topic(topic)
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalError(f"payload is not UTF-8 JSON: {exc}") from exc
    items = body.get("records") if isinstance(body, dict) and "records" in body else [body]
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise CanonicalError("payload must be a JSON object or {'records': [objects]}")
    out = []
    for it in items:
        it = dict(it)
        source = it.pop("source", "MEASURED")
        if kind == "telemetry":
            mid = it.pop("machine_id", machine)
            if mid != machine:
                raise CanonicalError(f"payload machine_id {mid!r} does not match topic {machine!r}")
            ts = it.pop("ts", None)
            state = it.pop("machine_state", None)
            out.append(canonical.telemetry(machine, ts, source, it, state))
        else:
            mid = it.pop("machine_id", None)
            ws, we = it.pop("window_start", None), it.pop("window_end", None)
            batch = it.pop("batch_id", "")
            out.append(canonical.production(mid, ws, we, source, it, batch))
    return kind, out
