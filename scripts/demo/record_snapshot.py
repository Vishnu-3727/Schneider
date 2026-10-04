"""Record a static snapshot of every GET request the console makes.

Reads live data from the backend (default http://localhost:8000) and writes
site/snapshot.json, keyed exactly the way console.js snapshot mode looks
requests up: path + '?' + params sorted by name, EXCLUDING params named
`start` and `end`. No params -> key is just the path.

Usage:
    .venv\\Scripts\\python scripts\\demo\\record_snapshot.py [--out site/snapshot.json]
                          [--base http://localhost:8000]

Stdlib only (urllib, json). Fails loudly on any non-200.
"""

import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
CONSOLE_JS = REPO / "apps" / "console" / "console.js"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def days_ago_iso(d):
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=d)


def key_of(path, params):
    if not params:
        return path
    ks = sorted(k for k in params if k not in ("start", "end"))
    if not ks:
        return path
    return path + "?" + "&".join(
        urllib.parse.quote(k, safe="") + "=" + urllib.parse.quote(str(params[k]), safe="")
        for k in ks
    )


def get(base, path, params=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r), url
    except urllib.error.HTTPError as e:
        sys.exit("record_snapshot: FAIL %s -> HTTP %s" % (url, e.code))
    except urllib.error.URLError as e:
        sys.exit("record_snapshot: FAIL %s -> %s" % (url, e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/snapshot.json")
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    snap = {}

    def record(path, params=None):
        data, url = get(base, path, params)
        k = key_of(path, params)
        snap[k] = data
        print("recorded %s  (%s)" % (k, url))

    # GET /machines first: per-machine keys below need the ids.
    machines, _ = get(base, "/machines")
    snap[key_of("/machines", None)] = machines
    print("recorded /machines")
    ids = []
    for m in machines if isinstance(machines, list) else []:
        mid = m.get("id") or m.get("machine_id")
        if mid:
            ids.append(mid)

    h24 = {
        "start": (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=24)).isoformat(),
        "end": now_iso(),
    }
    w7 = {"start": days_ago_iso(7).isoformat(), "end": now_iso()}

    record("/dashboard/summary", {"hours": 24})
    record("/energy/anomalies")
    record("/recommendations")
    record("/verification")
    record("/machine-health")
    record("/health/components")
    # Key has no params; called with a 7-day window like loadHealth does.
    record("/insights", dict(w7))
    record("/emission-factors")
    record("/interventions")
    for mid in ids:
        # loadDetect builds its /energy/summary window around the anomaly
        # events; start/end are excluded from the key, so the last 24 h
        # stand in for the call.
        record("/energy/summary", {"machine_id": mid, "start": h24["start"], "end": h24["end"]})
        # loadOptimise tries each machine in turn and skips machines with no
        # run (HTTP 404 "No optimization run for ..."): record the ones that
        # exist so snapshot mode skips the rest exactly like live mode does.
        try:
            record("/optimization/schedule", {"machine_id": mid})
        except SystemExit as e:
            if "HTTP 404" in str(e):
                print("note: no optimization run for %s, no key recorded "
                      "(live console skips it too)" % mid)
            else:
                raise
        record("/telemetry", {"machine_id": mid, "limit": 400})
    if not any(k.startswith("/optimization/schedule") for k in snap):
        sys.exit("record_snapshot: FAIL no optimization run for any machine; "
                 "loadOptimise would show 'no optimisation run yet'")
    if "furnace-01" not in ids:
        print("record_snapshot: WARNING furnace-01 not in /machines; "
              "recording its production keys anyway")
    record("/production", {"machine_id": "furnace-01", "limit": 48})
    record("/production", {"machine_id": "furnace-01", "limit": 24})

    # Cross-check: every api() call in console.js must have a snapshot key.
    # A call matches when some recorded key has the same path and the same
    # set of non-start/end param names.
    src = CONSOLE_JS.read_text(encoding="utf-8")
    templates = {}
    for m in re.finditer(r"api\(\s*\"([^\"]+)\"\s*(?:,\s*\{([^}]*)\})?", src):
        path = m.group(1)
        names = set()
        if m.group(2):
            for pm in re.finditer(r"(\w+)\s*:", m.group(2)):
                if pm.group(1) not in ("start", "end"):
                    names.add(pm.group(1))
        templates.setdefault(path, set()).add(frozenset(names))
    recorded_shapes = {}
    for k in snap:
        if k == "_meta":
            continue
        p, _, q = k.partition("?")
        names = frozenset(
            urllib.parse.unquote(n) for n in
            (part.split("=")[0] for part in q.split("&")) if n
        ) if q else frozenset()
        recorded_shapes.setdefault(p, set()).add(names)
    missing = []
    for path, shapes in sorted(templates.items()):
        for shape in shapes:
            if shape not in recorded_shapes.get(path, set()):
                missing.append(path + ("?" + ",".join(sorted(shape)) if shape else ""))
    if missing:
        print("record_snapshot: api() calls WITHOUT a snapshot key:")
        for k in missing:
            print("  MISSING " + k)
        sys.exit("record_snapshot: FAIL %d api() call shape(s) missing from snapshot"
                 % len(missing))

    snap = {"_meta": {"recorded_at": now_iso()}, **snap}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    print("wrote %s with %d keys" % (out, len(snap) - 1))


if __name__ == "__main__":
    main()
