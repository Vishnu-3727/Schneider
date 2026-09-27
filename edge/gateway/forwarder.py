"""Forward buffered canonical records to the JouleMitra API, oldest first.

Outcome per batch (a record is removed from the outbox ONLY on success or
on a definitive rejection that moves it to dead_letter):
  2xx                      -> delivered (removed, remembered for local dedup)
  connection error / 5xx   -> kept, exponential backoff, state API_UNAVAILABLE
  4xx for a batch of >1    -> retried one record at a time to isolate the bad one
  4xx for a single record  -> dead_letter with the API's reason
Live path: records go to /telemetry (no backfill flag), so the backend's
stale / out-of-order / duplicate checks apply unchanged.
"""

from __future__ import annotations

import time

import httpx

from edge.gateway.buffer import Buffer

PATHS = {"telemetry": "/telemetry", "production": "/production"}


class Forwarder:
    def __init__(self, buffer: Buffer, api_base: str, batch_size: int = 200,
                 timeout_s: float = 10.0, backoff_min_s: float = 1.0,
                 backoff_max_s: float = 60.0, client: httpx.Client | None = None) -> None:
        self.buffer = buffer
        self.batch_size = batch_size
        self.client = client or httpx.Client(base_url=api_base, timeout=timeout_s)
        self.backoff_min_s, self.backoff_max_s = backoff_min_s, backoff_max_s
        self.state = "IDLE"
        self.failures = 0
        self.retry_at = 0.0
        self.last_error: str | None = None
        self.results = {"accepted": 0, "suspect": 0, "bad": 0, "duplicate": 0}

    def _post(self, kind: str, recs: list[dict]) -> httpx.Response | None:
        try:
            r = self.client.post(PATHS[kind], json={"records": recs})
        except httpx.HTTPError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        if r.status_code >= 500:
            self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            return None
        return r

    def _unavailable(self, ids: list[int]) -> bool:
        self.buffer.bump_attempts(ids)
        self.failures += 1
        self.state = "API_UNAVAILABLE"
        self.retry_at = time.monotonic() + min(
            self.backoff_max_s, self.backoff_min_s * 2 ** (self.failures - 1))
        return False

    def _ok(self, r: httpx.Response, batch) -> None:
        for k, v in r.json().items():
            if k in self.results:
                self.results[k] += v
        self.buffer.delivered([(i, key) for i, key, _ in batch])

    def flush_once(self, kind: str) -> bool:
        """Send one batch. True if progress was made, False if nothing to do / API down."""
        if time.monotonic() < self.retry_at:
            return False
        batch = self.buffer.oldest(kind, self.batch_size)
        if not batch:
            return False
        r = self._post(kind, [rec for _, _, rec in batch])
        if r is None:
            return self._unavailable([i for i, _, _ in batch])
        self.failures, self.state = 0, "OK"
        if r.is_success:
            self._ok(r, batch)
            return True
        # 4xx: isolate the offending record(s); the good ones still go through.
        for item in batch:
            row_id, _key, rec = item
            single = self._post(kind, [rec])
            if single is None:
                return self._unavailable([row_id])
            if single.is_success:
                self._ok(single, [item])
            else:
                detail = single.text[:300]
                self.buffer.reject(row_id, kind, rec, f"API {single.status_code}: {detail}")
        return True

    def flush(self, max_batches: int = 1000) -> None:
        for kind in PATHS:
            for _ in range(max_batches):
                if not self.flush_once(kind):
                    break

    def status(self) -> dict:
        return {"state": self.state, "failures": self.failures, "last_error": self.last_error,
                "results": dict(self.results), **self.buffer.counts()}
