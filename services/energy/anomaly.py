"""Energy anomaly detection: L1 rules + L2 robust statistics (pure, no DB).

Wording rule (spec): energy "above expected baseline for the production
achieved". Never "failure".

L1 rules (thresholds passed in from config, no magic numbers):
  - DEVIATION: deviation_pct above warn/crit threshold for N consecutive
    complete intervals (severity WARNING / CRITICAL).
  - IDLE_WASTE: idle/holding hour share above threshold while good production
    is zero, for IDLE_CONSECUTIVE_N consecutive complete intervals. Persistence
    — not deviation — is the signal: sustained powered holding is predictable
    (the baseline identifies the holding coefficient, so a waste hour deviates
    only ~+5 %), while a single melt-free hour is normal inter-heat batch
    rhythm. The threshold (default 4) exceeds the longest legitimate melt-free
    span (~2.6 h: holding + plan idle + lunch + shift extras); see
    docs/ASSUMPTIONS.md.
  - POWER: interval max power_kw above rated_power_kw * multiple.
  - POWER_FACTOR: interval mean PF below threshold.

L2 statistical: rolling median + MAD robust z-score on the residual
(actual - expected) over a trailing window; z above threshold flags.
Only EXCESS energy flags (z positive): an anomaly is energy "above expected
baseline for the production achieved"; under-consumption (negative residual)
is not energy waste and is out of Phase-2 scope. (Sparse telemetry sampling
leaves hourly energy deltas over slightly-shorter spans than the state-hour
shares assume; the resulting negative residuals must never flag.)
Uses the modified z-score 0.6745*(x - median)/MAD. MAD == 0 -> z = 0
(a flat window carries no information, never inf). L2 additionally requires
deviation_pct above the practical-significance gate (the L1 warn
threshold): simulator duty-cycle beating leaves structured residuals of a
few percent whose rolling MAD is tiny, so a pure z-score test false-flags
NORMAL data. L2 is therefore the abrupt-large-jump detector (single
interval), while L1_DEVIATION catches sustained smaller shifts.

Only complete intervals are scored. Consecutive flagged intervals with the
same rule merge into one AnomalyEvent dict (machine_id, window_start/end,
metric, rule_id, level, score, severity, expected/actual/deviation,
evidence, status=OPEN, source=DERIVED, dedup_key).
"""

from __future__ import annotations

from statistics import median


def mad_zscores(residuals: list[float], window: int) -> list[float]:
    """Rolling robust z per position (trailing window incl. current, min 3 rows)."""
    out: list[float] = []
    for i, x in enumerate(residuals):
        w = residuals[max(0, i - window + 1) : i + 1]
        if len(w) < 3:
            out.append(0.0)
            continue
        med = median(w)
        mad = median([abs(v - med) for v in w])
        if mad <= 0:
            out.append(0.0)
            continue
        out.append(0.6745 * (x - med) / mad)
    return out


def l1_flags(
    scored: list[dict],
    deviation_warn_pct: float,
    deviation_crit_pct: float,
    consecutive_n: int,
    idle_share_threshold: float,
    rated_power_kw: float,
    rated_power_multiple: float,
    pf_min_threshold: float,
    idle_consecutive_n: int | None = None,
) -> list[dict]:
    """Per-interval L1 flags. Each item: {idx, rule_id, metric, severity, score, evidence}.

    `scored` items: {complete, deviation_pct, deviation_kwh, hours_by_state,
    good_production_kg, power_max_kw, pf_mean, expected_kwh, actual_kwh}.
    Incomplete intervals are never flagged. The idle rule fires after
    `idle_consecutive_n` consecutive qualifying intervals (defaults to
    `consecutive_n` when None).
    """
    flags: list[dict] = []
    dev_run = 0  # consecutive complete intervals above warn threshold
    idle_run = 0  # consecutive complete zero-production idle intervals above warn
    idle_n = idle_consecutive_n if idle_consecutive_n is not None else consecutive_n
    for i, s in enumerate(scored):
        if not s.get("complete"):
            dev_run = 0
            idle_run = 0
            continue
        dp = s.get("deviation_pct")
        if dp is not None and dp > deviation_warn_pct:
            dev_run += 1
        else:
            dev_run = 0
        if dev_run >= consecutive_n:
            sev = "CRITICAL" if (dp is not None and dp > deviation_crit_pct) else "WARNING"
            flags.append({
                "idx": i, "rule_id": "L1_DEVIATION", "metric": "deviation", "severity": sev,
                "score": float(dp) if dp is not None else 0.0,
                "evidence": (
                    f"Energy {dp:.1f}% above expected baseline for the production "
                    f"achieved for {dev_run} consecutive interval(s)."
                ),
            })
        hb = s.get("hours_by_state") or {}
        total_h = sum(hb.values())
        idle_h = float(hb.get("idle", 0.0) + hb.get("holding", 0.0))
        share = (idle_h / total_h) if total_h > 0 else 0.0
        good_kg = s.get("good_production_kg") or 0.0
        if share > idle_share_threshold and good_kg <= 0:
            idle_run += 1
        else:
            idle_run = 0
        if idle_run >= idle_n:
            flags.append({
                "idx": i, "rule_id": "L1_IDLE_WASTE", "metric": "idle_energy", "severity": "WARNING",
                "score": float(share),
                "evidence": (
                    f"Idle/holding share {share * 100:.0f}% with zero good production for "
                    f"{idle_run} consecutive interval(s): energy spent with no useful output."
                ),
            })
        pmax = s.get("power_max_kw")
        if pmax is not None and rated_power_kw > 0 and pmax > rated_power_kw * rated_power_multiple:
            flags.append({
                "idx": i, "rule_id": "L1_POWER", "metric": "power", "severity": "WARNING",
                "score": float(pmax / rated_power_kw),
                "evidence": (
                    f"Peak power {pmax:.1f} kW above rated {rated_power_kw:.1f} kW "
                    f"x {rated_power_multiple}."
                ),
            })
        pf = s.get("pf_mean")
        if pf is not None and pf < pf_min_threshold:
            flags.append({
                "idx": i, "rule_id": "L1_POWER_FACTOR", "metric": "pf", "severity": "WARNING",
                "score": float(pf),
                "evidence": f"Mean power factor {pf:.2f} below threshold {pf_min_threshold}.",
            })
    return flags


def l2_flags(scored: list[dict], mad_threshold: float, mad_window: int,
             min_deviation_pct: float) -> list[dict]:
    """Robust-z flags on residuals of complete intervals with non-null expected.

    A flag additionally requires deviation_pct > min_deviation_pct
    (practical significance; pass DEVIATION_WARN_PCT from config).
    Only positive (excess-energy) jumps flag; negative residuals never do.
    """
    idx, resid = [], []
    for i, s in enumerate(scored):
        if s.get("complete") and s.get("actual_kwh") is not None and s.get("expected_kwh") is not None:
            idx.append(i)
            resid.append(float(s["actual_kwh"]) - float(s["expected_kwh"]))
    zs = mad_zscores(resid, mad_window)
    flags = []
    for i, z in zip(idx, zs, strict=True):
        dev_pct = scored[i].get("deviation_pct")
        if z > mad_threshold and dev_pct is not None and dev_pct > min_deviation_pct:
            s = scored[i]
            flags.append({
                "idx": i, "rule_id": "L2_MAD_RESIDUAL", "metric": "deviation",
                "severity": "CRITICAL" if z > mad_threshold * 1.5 else "WARNING",
                "score": float(z),
                "evidence": (
                    f"Robust z-score {z:+.1f} on residual (actual - expected) "
                    f"vs trailing {mad_window}-interval window; energy above expected "
                    f"baseline for the production achieved"
                    + (f" ({dev_pct:+.1f}%)." if dev_pct is not None else ".")
                ),
            })
    return flags


def merge_runs(flags: list[dict]) -> list[list[dict]]:
    """Group flags with equal rule_id over consecutive interval indexes."""
    groups: list[list[dict]] = []
    for f in sorted(flags, key=lambda f: (f["rule_id"], f["idx"])):
        if groups and groups[-1][-1]["rule_id"] == f["rule_id"] and f["idx"] == groups[-1][-1]["idx"] + 1:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def build_events(
    machine_id: str,
    scored: list[dict],
    interval_starts: list,
    interval_ends: list,
    flags: list[dict],
    fit_id: str | None = None,
) -> list[dict]:
    """Merge consecutive flags per rule into one event dict each.

    scored[i]: {metric..., expected_kwh, actual_kwh, deviation_kwh, deviation_pct}.
    Severity of a merged event is the max (CRITICAL > WARNING).
    dedup_key = machine|rule|window_start|window_end (idempotent re-detect).
    """
    _ = fit_id  # reserved: baseline FK if schema gains it; stored via dedup_key today
    events = []
    for run in merge_runs(flags):
        rule = run[0]["rule_id"]
        i0, i1 = run[0]["idx"], run[-1]["idx"]
        sev = "CRITICAL" if any(f["severity"] == "CRITICAL" for f in run) else "WARNING"
        score = max(abs(f["score"]) for f in run)
        parts = [scored[i] for i in range(i0, i1 + 1)]
        exp = sum(p["expected_kwh"] for p in parts if p.get("expected_kwh") is not None)
        act = sum(p["actual_kwh"] for p in parts if p.get("actual_kwh") is not None)
        dev = act - exp if parts and all(p.get("expected_kwh") is not None and p.get("actual_kwh") is not None for p in parts) else None
        dev_pct = (sum(p["deviation_pct"] for p in parts if p.get("deviation_pct") is not None) / len(parts)) if parts else None
        ws = interval_starts[i0]
        we = interval_ends[i1]
        ws_s = ws.isoformat() if hasattr(ws, "isoformat") else str(ws)
        we_s = we.isoformat() if hasattr(we, "isoformat") else str(we)
        events.append({
            "machine_id": machine_id,
            "window_start": ws,
            "window_end": we,
            "metric": run[0]["metric"],
            "rule_id": rule,
            "level": "L1_rule" if rule.startswith("L1_") else "L2_statistical",
            "score": float(score),
            "severity": sev,
            "expected_kwh": float(exp) if parts else None,
            "actual_kwh": float(act) if parts else None,
            "deviation_kwh": float(dev) if dev is not None else None,
            "deviation_pct": float(dev_pct) if dev_pct is not None else None,
            "evidence": f"{rule}: " + " ".join(f["evidence"] for f in run[:2])
                        + (f" (+{len(run) - 2} more interval(s))" if len(run) > 2 else ""),
            "status": "OPEN",
            "source": "DERIVED",
            "dedup_key": f"{machine_id}|{rule}|{ws_s}|{we_s}",
        })
    return events
