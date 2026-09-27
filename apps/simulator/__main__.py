"""CLI: python -m apps.simulator --scenario NORMAL --hours 24 --step-s 60 --seed 1 [--post | --csv out.csv]

Phase 2: --normal-days N generates N NORMAL days followed by a --hours
scenario window, e.g. --normal-days 7 --scenario IDLE_WASTE --hours 24 --post.
--magnitude sets the HIGH_LOAD power uplift fraction (default 0.25) or the
PRODUCTION_SURGE production uplift fraction (default 0.30)."""

from __future__ import annotations

import argparse
import sys

import httpx

from apps.backend.config import get_settings
from apps.simulator.factory_simulator import (
    DEFAULT_HIGH_LOAD_MAGNITUDE,
    DEFAULT_SURGE_MAGNITUDE,  # noqa: F401 (surfaced in --help)
    DEFAULT_MACHINES,
    MachineSpec,
    Scenario,
    SimulatedFactory,
)


def fetch_machine_specs(api_base: str) -> list[MachineSpec] | None:
    try:
        r = httpx.get(f"{api_base}/machines", timeout=10.0)
        if r.status_code != 200:
            return None
        return [
            MachineSpec(m["id"], m["machine_type"], float(m["rated_power_kw"])) for m in r.json()
        ]
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="JouleMitra Phase 1 factory simulator (SIMULATED data)")
    ap.add_argument("--scenario", default="NORMAL")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--step-s", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--post", action="store_true", help="POST packets to the API")
    ap.add_argument("--csv", default=None, help="Write telemetry CSV (production goes to *_production.csv)")
    ap.add_argument("--normal-days", type=float, default=0.0,
                    help="NORMAL history days prepended before the scenario window")
    ap.add_argument("--magnitude", type=float, default=None,
                    help=f"HIGH_LOAD power uplift (default {DEFAULT_HIGH_LOAD_MAGNITUDE}) "
                         f"or PRODUCTION_SURGE production uplift (default {DEFAULT_SURGE_MAGNITUDE})")
    ap.add_argument("--end", default=None,
                    help="Run end as ISO timestamp (default: now). Fixes windows for verify runs.")
    args = ap.parse_args(argv)

    try:
        scenario = Scenario(args.scenario)
    except ValueError:
        print(f"Unknown scenario '{args.scenario}'. Valid: {[s.value for s in Scenario]}",
              file=sys.stderr)
        return 2

    settings = get_settings()
    specs = DEFAULT_MACHINES
    if args.post:
        fetched = fetch_machine_specs(settings.API_BASE_URL)
        if fetched:
            specs = fetched
        else:
            print("API /machines unreachable, using default demo machine specs")

    from apps.simulator.factory_simulator import post_to_api, write_csv

    end = None
    if args.end:
        from datetime import datetime as _dt

        end = _dt.fromisoformat(args.end)
    normal_h = float(args.normal_days) * 24.0
    factory = SimulatedFactory(specs, scenario=scenario, hours=normal_h + args.hours,
                               step_s=args.step_s, seed=args.seed, tz=settings.TZ,
                               end=end,
                               scenario_start_h=normal_h, scenario_duration_h=args.hours,
                               magnitude=args.magnitude)
    telemetry, production = factory.run()
    print(f"scenario={scenario.value} seed={args.seed} telemetry={len(telemetry)} production={len(production)}")
    for mid, (ws, we) in factory.scenario_windows().items():
        print(f"ground-truth window {mid}: {ws} .. {we} (tests only, never stored)")

    if args.csv:
        tpath, ppath = write_csv(telemetry, production, args.csv)
        print(f"wrote {tpath} and {ppath}")
    if args.post:
        totals = post_to_api(telemetry, production, settings.API_BASE_URL)
        print(f"posted: {totals}")
    if not args.csv and not args.post:
        print("(dry run: packets generated but neither --csv nor --post given)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
