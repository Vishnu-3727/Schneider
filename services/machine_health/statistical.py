"""JouleMitra-native statistical health model (clean-room, written here).

Per machine, learns a robust NORMAL reference (median + MAD) per signal
(vibration_mm_s, temperature_c, current_a), conditioned on the exact
machine_state (melting vs holding vs idle vs running, ...): a resting
furnace idles near 600 C / 1.2 mm/s while melting runs near 1550 C /
3.0 mm/s, and holding sits between, so any merged reference would
false-flag normal state changes. Buckets with fewer than min_bucket_rows
reference rows score OUT_OF_DOMAIN (never a forced verdict).

Scoring: robust z per signal (modified z-score 0.6745*(x-median)/MAD with
a relative MAD floor so near-flat references never explode), combined
into anomaly_score = max signal |z| and health_score = 100*exp(-(a/crit)^2)
(100 = exactly reference-like, decaying smoothly toward 0). States via
config thresholds: a >= crit_z -> CRITICAL, a >= warn_z -> WARNING.

The MAD floor (default 10 % of |median|) deliberately desensitises
load-confounded current: a healthy 25 % load uplift moves current ~25 %
(z ~ 1.7, silent), while degradation moves vibration far beyond the floor.
Vibration/temperature are the primary degradation witnesses; current
rises (and contributes to the score) only when the fault also adds
mechanical load (simulator energy_penalty > 0) — a health-only fault
leaves current at its NORMAL operating point.

Missing signals -> status UNAVAILABLE for that interval (never zeros,
never a crash). Too little reference (< min_ref_intervals fitted
intervals) -> INSUFFICIENT_HISTORY. Scoring bucket never seen (with enough
rows) in fit -> OUT_OF_DOMAIN. Pure: no DB, no config imports; thresholds
are constructor arguments (the router passes settings in).
"""

from __future__ import annotations

import math
from datetime import timedelta
from statistics import median

from services.machine_health.model import HEALTH_SIGNALS, MachineHealthModel


def state_bucket(machine_state: str | None) -> str:
    """Exact-state conditioning bucket (lower-cased; None -> 'unknown')."""
    if machine_state is None or str(machine_state).strip() == "":
        return "unknown"
    return str(machine_state).lower()


def robust_z(value: float, med: float, mad: float,
             floor_frac: float, epsilon: float) -> float:
    """Modified robust z-score with a MAD floor (never inf/NaN)."""
    mad_eff = max(mad, floor_frac * abs(med), epsilon)
    if mad_eff <= 0:
        return 0.0
    return 0.6745 * (value - med) / mad_eff


def health_score_from_anomaly(anomaly: float, crit_z: float) -> float:
    """0-100 health score, smooth decay with anomaly (crit_z -> ~37)."""
    return round(100.0 * math.exp(-((anomaly / crit_z) ** 2)), 1)


class StatisticalHealthModel(MachineHealthModel):
    """Native robust-reference health model. JSON params round-trip via
    fit() -> params dict -> from_params() so the router can persist the
    reference in machine_health_reference.params."""

    model_id = "statistical-v1"

    def __init__(
        self,
        min_ref_intervals: int = 24,
        min_bucket_rows: int = 5,
        warn_z: float = 3.0,
        crit_z: float = 5.0,
        mad_floor_frac: float = 0.05,
        mad_epsilon: float = 1e-6,
    ) -> None:
        self.min_ref_intervals = min_ref_intervals
        self.min_bucket_rows = min_bucket_rows
        self.warn_z = warn_z
        self.crit_z = crit_z
        self.mad_floor_frac = mad_floor_frac
        self.mad_epsilon = mad_epsilon
        self._params: dict | None = None

    # -- metadata ------------------------------------------------------
    def metadata(self) -> dict:
        return {
            "model_id": self.model_id,
            "family": "robust-reference (median + MAD per signal, state-conditioned)",
            "training_domain": (
                "NORMAL-operation telemetry of the same machine being scored; "
                "reference intervals must be fitted per machine (no cross-machine transfer)"
            ),
            "valid_input_signals": list(HEALTH_SIGNALS),
            "state_conditioning": "intervals bucketed by exact machine_state "
                                  "(dominant state in the interval: melting / "
                                  "holding / idle / running, ...)",
            "evidence_source_class": "DERIVED",
            "limitations": [
                "Hourly means only: sub-hour transients are smoothed away.",
                "Linear-gauge view: gradual drift below the WARNING threshold "
                "lowers the health score but never raises the state.",
                "The MAD floor desensitises load-confounded current (a healthy "
                "load uplift is silent); vibration/temperature are the primary "
                "degradation witnesses.",
                "State buckets need >= min_bucket_rows reference rows or "
                "intervals score OUT_OF_DOMAIN; rare states may be uncovered.",
            ],
            "thresholds": {
                "min_ref_intervals": self.min_ref_intervals,
                "min_bucket_rows": self.min_bucket_rows,
                "warn_z": self.warn_z,
                "crit_z": self.crit_z,
            },
        }

    # -- fit -----------------------------------------------------------
    def fit(self, reference_rows: list[dict]) -> dict:
        """Learn per-(bucket, signal) median + MAD. Only complete rows with
        at least one present signal contribute; rows are never mutated."""
        by_bucket: dict[str, dict[str, list[float]]] = {}
        n = 0
        for r in reference_rows:
            if not r.get("complete"):
                continue
            vals = {s: r.get(s) for s in HEALTH_SIGNALS if r.get(s) is not None}
            if not vals:
                continue
            n += 1
            b = state_bucket(r.get("machine_state"))
            bucket = by_bucket.setdefault(b, {s: [] for s in HEALTH_SIGNALS})
            for s, v in vals.items():
                bucket[s].append(float(v))
        buckets: dict[str, dict] = {}
        for b, sigs in by_bucket.items():
            buckets[b] = {}
            for s, vals in sigs.items():
                if not vals:
                    continue
                med = float(median(vals))
                mad = float(median([abs(v - med) for v in vals]))
                buckets[b][s] = {"median": med, "mad": mad, "n": len(vals)}
        self._params = {"buckets": buckets, "n_intervals": n,
                        "signals": list(HEALTH_SIGNALS)}
        return self._params

    @classmethod
    def from_params(cls, params: dict, **thresholds) -> "StatisticalHealthModel":
        m = cls(**thresholds)
        m._params = params
        return m

    # -- score ---------------------------------------------------------
    def _signal_zs(self, row: dict) -> tuple[str, list[dict] | None, str | None]:
        """Return (bucket, contributions, error_reason). Contributions is
        None when the bucket reference is unusable (OUT_OF_DOMAIN)."""
        b = state_bucket(row.get("machine_state"))
        buckets = (self._params or {}).get("buckets", {})
        ref = buckets.get(b)
        if ref is None:
            return b, None, f"state bucket '{b}' not seen in reference"
        contribs = []
        for s in HEALTH_SIGNALS:
            v = row.get(s)
            if v is None:
                continue
            r = ref.get(s)
            if r is None or r.get("n", 0) < self.min_bucket_rows:
                continue
            med = float(r["median"])
            z = robust_z(float(v), med, float(r["mad"]),
                         self.mad_floor_frac, self.mad_epsilon)
            pct = (float(v) - med) / abs(med) * 100.0 if med != 0 else None
            contribs.append({"signal": s, "value": float(v), "median": med,
                             "z": round(z, 2),
                             "pct_change": round(pct, 1) if pct is not None else None,
                             "weight": 0.0})
        if not contribs:
            # Bucket known but no usable signal overlap (all missing, or the
            # reference bucket is too thin on every present signal).
            present = [s for s in HEALTH_SIGNALS if row.get(s) is not None]
            if not present:
                return b, [], "no health signals present"
            return b, None, f"state bucket '{b}' reference too thin"
        denom = sum(abs(c["z"]) for c in contribs)
        for c in contribs:
            c["weight"] = round(abs(c["z"]) / denom, 3) if denom > 0 else 0.0
        contribs.sort(key=lambda c: abs(c["z"]), reverse=True)
        # Renormalise after rounding so weights sum to exactly 1.0.
        if denom > 0 and contribs:
            rest = round(sum(c["weight"] for c in contribs[1:]), 3)
            contribs[0]["weight"] = round(1.0 - rest, 3)
        return b, contribs, None

    def predict(self, rows: list[dict]) -> list[dict]:
        out = []
        if self._params is None or self._params.get("n_intervals", 0) < self.min_ref_intervals:
            n = (self._params or {}).get("n_intervals", 0)
            for _ in rows:
                out.append({"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "INSUFFICIENT_HISTORY",
                            "reason": f"reference has {n} interval(s), "
                                      f"need >= {self.min_ref_intervals}"})
            return out
        for r in rows:
            if not r.get("complete"):
                out.append({"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "UNAVAILABLE",
                            "reason": "incomplete interval (telemetry coverage "
                                      "below minimum)"})
                continue
            bucket, contribs, err = self._signal_zs(r)
            if contribs is None:
                out.append({"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "OUT_OF_DOMAIN",
                            "reason": err or "reference does not cover bucket"})
                continue
            if not contribs:
                out.append({"health_score": None, "anomaly_score": None,
                            "state": "NORMAL", "status": "UNAVAILABLE",
                            "reason": "no health signals present in interval "
                                      "(vibration/temperature/current all null)"})
                continue
            anomaly = round(max(abs(c["z"]) for c in contribs), 2)
            top = contribs[0]
            health = health_score_from_anomaly(anomaly, self.crit_z)
            if anomaly >= self.crit_z:
                state = "CRITICAL"
            elif anomaly >= self.warn_z:
                state = "WARNING"
            else:
                state = "NORMAL"
            if state == "NORMAL":
                reason = (f"max |z| {anomaly:.1f} ({top['signal']}) within "
                          f"NORMAL range for '{bucket}' reference")
            else:
                bits = ", ".join(
                    f"{c['signal']} z {c['z']:+.1f}"
                    + (f" ({c['pct_change']:+.1f}%)" if c["pct_change"] is not None else "")
                    for c in contribs[:2]
                )
                reason = (f"{state}: {bits} vs '{bucket}' reference "
                          f"(health {health:.0f}/100)")
            out.append({"health_score": health, "anomaly_score": anomaly,
                        "state": state, "status": "OK", "reason": reason})
        return out

    def explain(self, rows: list[dict]) -> list[list[dict]]:
        if self._params is None:
            return [[] for _ in rows]
        out = []
        for r in rows:
            _, contribs, _ = self._signal_zs(r)
            out.append(contribs or [])
        return out


def build_health_intervals(
    machine_id: str,
    telemetry_rows: list[dict],
    start,
    end,
    interval_s: int,
    min_coverage_pct: float,
) -> list[dict]:
    """Bucket GOOD telemetry into fixed hourly windows (pure, no DB).

    Per interval: signal means over non-null values, dominant machine_state
    (mode), row counts, span coverage. BAD rows fail the interval; SUSPECT
    rows are excluded like in services/energy/aggregate.py. Missing signals
    stay None (never zero-filled).
    """
    n = max(0, int((end - start).total_seconds() // interval_s))
    buckets: list[list[dict]] = [[] for _ in range(n)]
    bad = [0] * n
    for r in telemetry_rows:
        ts = r["ts"]
        if not (start <= ts < end):
            continue
        k = int((ts - start).total_seconds() // interval_s)
        if 0 <= k < n:
            if r.get("quality") == "BAD":
                bad[k] += 1
            elif r.get("quality") == "GOOD":
                buckets[k].append(r)
    out: list[dict] = []
    for k in range(n):
        ws = start + timedelta(seconds=k * interval_s)
        we = ws + timedelta(seconds=interval_s)
        rows = sorted(buckets[k], key=lambda r: r["ts"])
        iv: dict = {"machine_id": machine_id, "window_start": ws,
                    "window_end": we, "machine_state": None,
                    "vibration_mm_s": None, "temperature_c": None,
                    "current_a": None, "n_rows": len(rows),
                    "n_bad": bad[k], "coverage_pct": 0.0, "complete": False,
                    "incomplete_reasons": []}
        reasons: list[str] = []
        if bad[k]:
            reasons.append(f"contains {bad[k]} BAD-quality row(s)")
        if rows:
            span_s = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() if len(rows) > 1 else 0.0
            iv["coverage_pct"] = round(min(100.0, span_s / interval_s * 100.0), 2)
        if iv["coverage_pct"] < min_coverage_pct:
            reasons.append(f"coverage {iv['coverage_pct']}% below minimum {min_coverage_pct}%")
        if rows:
            for s in HEALTH_SIGNALS:
                vals = [float(r[s]) for r in rows if r.get(s) is not None]
                if vals:
                    iv[s] = sum(vals) / len(vals)
            counts: dict[str, int] = {}
            for r in rows:
                st = r.get("machine_state") or "unknown"
                counts[st] = counts.get(st, 0) + 1
            iv["machine_state"] = max(counts, key=lambda k2: counts[k2])
        else:
            reasons.append("no GOOD telemetry rows")
        iv["incomplete_reasons"] = reasons
        iv["complete"] = not reasons
        out.append(iv)
    return out
