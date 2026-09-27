"""MQTT ingestion for the edge gateway (paho-mqtt 2.x, imported lazily).

- connect_async + loop_start: an unavailable broker never blocks or crashes
  the gateway; paho retries with reconnect_delay_set backoff, and the
  subscriptions are renewed in on_connect after every (re)connect.
- QoS 1 subscriptions: at-least-once delivery, so duplicates are expected.
  The buffer's dedup key and the backend's (machine, ts) dedup absorb them.
- Retained messages (the broker replays the last value on subscribe) are
  counted as replays and pass through the same dedup: a retained reading
  already delivered is not sent again, and an old one is flagged stale by
  the backend.
- A malformed payload or unsupported topic goes to dead_letter with its
  reason. It is never dropped silently.
"""

from __future__ import annotations

import os
import threading

from edge import canonical
from edge.canonical import CanonicalError
from edge.gateway.buffer import Buffer
from edge.mqtt.adapter import PRODUCTION_SUB, TELEMETRY_SUB, to_records


class MqttIngest:
    def __init__(self, buffer: Buffer, host: str, port: int = 1883, client_id: str = "jm-gateway",
                 username_env: str = "MQTT_USERNAME", password_env: str = "MQTT_PASSWORD",
                 reconnect_min_s: int = 1, reconnect_max_s: int = 30) -> None:
        import paho.mqtt.client as mqtt

        self.buffer = buffer
        self.host, self.port = host, port
        self.connected = threading.Event()
        self.stats = {"messages": 0, "records": 0, "duplicates": 0, "retained": 0,
                      "dead_letter": 0, "connects": 0, "disconnects": 0}
        self.last_error: str | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                                  clean_session=False)
        user, pwd = os.environ.get(username_env), os.environ.get(password_env)
        if user:
            self.client.username_pw_set(user, pwd)
        self.client.reconnect_delay_set(min_delay=reconnect_min_s, max_delay=reconnect_max_s)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self.last_error = f"connect refused: {reason_code}"
            return
        self.stats["connects"] += 1
        client.subscribe([(TELEMETRY_SUB, 1), (PRODUCTION_SUB, 1)])
        self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected.clear()
        self.stats["disconnects"] += 1
        self.last_error = f"disconnected: {reason_code}"

    def _on_message(self, client, userdata, msg):
        self.handle(msg.topic, msg.payload, bool(msg.retain))

    def handle(self, topic: str, payload: bytes, retained: bool = False) -> None:
        """Adapter + buffer step (also called directly by tests)."""
        self.stats["messages"] += 1
        if retained:
            self.stats["retained"] += 1
        try:
            kind, records = to_records(topic, payload)
        except CanonicalError as exc:
            self.stats["dead_letter"] += 1
            self.buffer.dead_letter("mqtt", {"topic": topic,
                                             "payload": payload.decode("utf-8", "replace")},
                                    f"malformed: {exc}")
            return
        for rec in records:
            if self.buffer.enqueue(kind, canonical.dedup_key(kind, rec), rec):
                self.stats["records"] += 1
            else:
                self.stats["duplicates"] += 1

    def status(self) -> dict:
        return {"broker": f"{self.host}:{self.port}", "connected": self.connected.is_set(),
                "last_error": self.last_error, **self.stats}
