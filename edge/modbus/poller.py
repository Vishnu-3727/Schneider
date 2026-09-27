"""Poll one Modbus device, decode its register map, emit canonical telemetry.

Failure handling (never crashes the gateway, never invents a value):
  timeout / unavailable -> no record this cycle, state TIMEOUT / UNAVAILABLE,
                           exponential backoff before the next attempt
                           (reconnect happens on the next successful read)
  invalid register      -> that field None, the issue recorded in status
Readings are timestamped at the gateway (tz-aware) because meters rarely
carry a clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edge import canonical
from edge.modbus.device import DeviceTimeout, DeviceUnavailable
from edge.modbus.registers import RegisterSpec, decode, span


class ModbusPoller:
    def __init__(self, machine_id: str, device, specs: list[RegisterSpec],
                 source: str = "MEASURED", backoff_min_s: float = 1.0,
                 backoff_max_s: float = 60.0) -> None:
        self.machine_id = machine_id
        self.device = device
        self.specs = specs
        self.source = source
        self.backoff_min_s = backoff_min_s
        self.backoff_max_s = backoff_max_s
        self.state = "INIT"
        self.failures = 0
        self.next_attempt: datetime | None = None
        self.last_ok: datetime | None = None
        self.last_issues: list[str] = []
        self.first, self.count = span(specs)

    def poll(self, now: datetime | None = None) -> dict | None:
        now = now or datetime.now(UTC)
        if self.next_attempt is not None and now < self.next_attempt:
            return None  # backing off after a failure
        try:
            regs = self.device.read(self.first, self.count)
        except (DeviceTimeout, DeviceUnavailable) as exc:
            self.failures += 1
            self.state = "TIMEOUT" if isinstance(exc, DeviceTimeout) else "UNAVAILABLE"
            delay = min(self.backoff_max_s, self.backoff_min_s * 2 ** (self.failures - 1))
            self.next_attempt = now + timedelta(seconds=delay)
            self.last_issues = [f"{self.state}: {exc}"]
            return None
        block = {self.first + k: r for k, r in enumerate(regs)}
        fields, issues = decode(self.specs, block)
        self.state, self.failures, self.next_attempt = "CONNECTED", 0, None
        self.last_ok, self.last_issues = now, issues
        return canonical.telemetry(self.machine_id, now, self.source, fields)

    def status(self) -> dict:
        return {"machine_id": self.machine_id, "state": self.state, "failures": self.failures,
                "last_ok": self.last_ok.isoformat() if self.last_ok else None,
                "next_attempt": self.next_attempt.isoformat() if self.next_attempt else None,
                "issues": self.last_issues}
