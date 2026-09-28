/* JouleMitra Impact Console — one page, six screens, live API only.
 * Every number is fetched from the same-origin backend. Missing or failed
 * fields render an explicit small "not available" state; nothing is invented.
 * Display rules: times in Asia/Kolkata ("27 Sep, 17:30"); big-value slots
 * show a number or an em dash (never raw enums); long decimals in API text
 * are rounded to 2 decimals for display. */
(function () {
  "use strict";

  var STATIC = new URLSearchParams(window.location.search).has("static");
  if (STATIC) document.documentElement.classList.add("static");

  var SCREENS = ["plant", "detect", "health", "optimise", "act", "impact", "payback"];
  var STALE_MS = 15 * 60 * 1000;
  var TZ = "Asia/Kolkata";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ---------- small helpers ---------- */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return null;
    return Number(v).toLocaleString("en-IN", {
      minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d
    });
  }
  /* G6: round runs of 3+ decimals inside API free text to 2 decimals. */
  function roundLong(s) {
    return String(s == null ? "" : s).replace(/\d+\.\d{3,}/g, function (m) {
      var n = Number(m);
      if (!isFinite(n)) return m;
      return String(Number(n.toFixed(2)));
    });
  }
  /* API free text, safe for display: rounded + escaped. */
  function txt(s) { return esc(roundLong(s)); }
  /* G5: "not available" is always small and muted. */
  function naHtml(suffix) {
    return '<span class="na">not available' + (suffix ? " " + esc(suffix) : "") + "</span>";
  }
  /* G4: big-value slots show a number or an em dash, never a raw enum. */
  function dashBig() { return '<span class="num">\u2014</span>'; }
  function numOrNa(v, d, unit) {
    var f = fmt(v, d);
    if (f == null) return naHtml();
    return '<span class="num">' + esc(f) + "</span>" + (unit ? " " + esc(unit) : "");
  }
  function badge(text, cls) {
    if (text == null || text === "") return "";
    return '<span class="badge' + (cls ? " " + cls : "") + '">' + esc(text) + "</span>";
  }
  function nowIso() { return new Date().toISOString(); }
  function daysAgoIso(d) { return new Date(Date.now() - d * 24 * 3600 * 1000).toISOString(); }
  /* G3: Asia/Kolkata times, never raw ISO. */
  var _dtf = null;
  function kolkataParts(iso) {
    try {
      if (!_dtf) {
        _dtf = new Intl.DateTimeFormat("en-GB", {
          timeZone: TZ, day: "2-digit", month: "numeric",
          hour: "2-digit", minute: "2-digit", hour12: false
        });
      }
      var parts = _dtf.formatToParts(new Date(iso));
      var p = {};
      parts.forEach(function (x) { p[x.type] = x.value; });
      if (!p.day || !p.month || !p.hour || !p.minute) return null;
      return { d: p.day, mon: MONTHS[Number(p.month) - 1] || "", hh: p.hour, mm: p.minute };
    } catch (e) { return null; }
  }
  function fmtT(iso) {
    if (iso == null || iso === "") return "";
    var p = kolkataParts(iso);
    if (!p) return "";
    return p.d + " " + p.mon + ", " + p.hh + ":" + p.mm;
  }
  /* Plotly ignores UTC offsets in date strings, so mixing "+05:30" and
   * "+00:00" values shifts one series by 5.5 h. Every time handed to
   * Plotly goes through px(): Kolkata wall-clock, no offset. */
  var _pxf = null;
  function px(iso) {
    if (!_pxf) {
      _pxf = new Intl.DateTimeFormat("sv-SE", {
        timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
      });
    }
    return _pxf.format(typeof iso === "number" ? new Date(iso) : new Date(iso));
  }
  function fmtRange(a, b) {
    var pa = kolkataParts(a), pb = kolkataParts(b);
    if (!pa || !pb) return fmtT(a) || fmtT(b);
    if (pa.d === pb.d && pa.mon === pb.mon) {
      return pa.d + " " + pa.mon + " " + pa.hh + ":" + pa.mm +
        " \u2013 " + pb.hh + ":" + pb.mm;
    }
    return pa.d + " " + pa.mon + " " + pa.hh + ":" + pa.mm +
      " \u2013 " + pb.d + " " + pb.mon + " " + pb.hh + ":" + pb.mm;
  }
  /* Friendly one-line reason for a non-OK SEC status (G4: big slot keeps number/emdash). */
  function secReason(status) {
    switch (status) {
      case "NO_PRODUCTION": return "no production today";
      case "MISSING_PRODUCTION": return "production data missing";
      case "INCOMPLETE_DATA": return "incomplete data";
      case "NOT_APPLICABLE": return "not applicable to this machine";
      default: return status ? String(status).toLowerCase().replace(/_/g, " ") : "no SEC value";
    }
  }
  /* Plain names for rule codes; the code stays visible, small, for audit. */
  var RULES = {
    L1_DEVIATION: "Using more energy than expected",
    L1_IDLE_WASTE: "Energy spent with no output",
    L1_POWER: "Power above the rated limit",
    L1_POWER_FACTOR: "Poor power factor",
    L2_MAD_RESIDUAL: "Sudden unusual energy jump",
    "R-IDLE": "Cut idle and holding time",
    "R-INSPECT": "Inspect the machine",
    "R-PROCESS": "Tighten the process",
    "R-RESCHEDULE": "Move work to cheaper hours",
    "R-SEQUENCE": "Re-order the heats",
    "R-NOPLAN": "No production plan found",
    "R-PRIORITISE": "Look at this machine first"
  };
  function ruleName(id) { return RULES[id] || id || "event"; }
  /* Health reasons come from the API in engineer's terms; say them plainly. */
  function healthReason(r) {
    if (!r) return "";
    if (/POST \/|no fitted reference/i.test(r)) return "Not enough history to score yet.";
    var m = /max \|z\| ([\d.]+) \(([\w]+)\) within NORMAL/i.exec(r);
    if (m) {
      return "All sensors inside their normal range. Largest drift: " +
        m[2].replace(/_(a|c|mm_s|kw|v)$/i, "").replace(/_/g, " ") + " at " + Number(m[1]).toFixed(1) + " standard deviations.";
    }
    return roundLong(r);
  }
  function firstSentence(s) {
    var t = String(s || "");
    var i = t.indexOf(". ");
    return i > 0 ? t.slice(0, i + 1) : t;
  }
  function setChips(id, parts) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = parts.map(function (p) { return '<span class="chip">' + esc(p) + "</span>"; }).join("");
  }
  async function api(path, params) {
    var url = path;
    if (params) {
      var q = Object.keys(params).map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
      }).join("&");
      if (q) url += "?" + q;
    }
    try {
      var r = await fetch(url, { headers: { Accept: "application/json" } });
      if (!r.ok) return { error: "HTTP " + r.status + " on " + path };
      return await r.json();
    } catch (e) {
      return { error: "unreachable " + path + ": " + (e && e.message || e) };
    }
  }

  /* ---------- plotly theme (colours resolved from CSS tokens) ---------- */
  var _colors = null;
  function colors() {
    if (_colors) return _colors;
    function cssVar(name) {
      var el = document.createElement("div");
      el.style.color = "var(" + name + ")";
      el.style.display = "none";
      document.body.appendChild(el);
      var c = getComputedStyle(el).color;
      el.remove();
      return c || "#fff";
    }
    _colors = {
      accent: cssVar("--color-accent"),
      verified: cssVar("--color-verified"),
      warn: cssVar("--color-warn"),
      ink: cssVar("--color-ink"),
      ink2: cssVar("--color-ink-2"),
      ink3: cssVar("--color-ink-3"),
      rule: cssVar("--color-rule"),
      paper: cssVar("--color-paper")
    };
    return _colors;
  }
  /* Chart text scales with the root size like the rest of the page. */
  function rem(n) {
    return Math.round(n * parseFloat(getComputedStyle(document.documentElement).fontSize));
  }
  function baseLayout(extra) {
    var c = colors();
    var base = {
      /* G1: charts fill their panel — no fixed height, autosize only. */
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Archivo, 'Segoe UI', system-ui, sans-serif", color: c.ink2, size: rem(0.875) },
      margin: { l: rem(3.5), r: rem(1), t: rem(0.75), b: rem(2.75) },
      xaxis: { gridcolor: c.rule, zerolinecolor: c.rule, tickfont: { color: c.ink2 } },
      yaxis: { gridcolor: c.rule, zerolinecolor: c.rule, tickfont: { color: c.ink2 } },
      showlegend: true,
      legend: { font: { color: c.ink2 } }
    };
    if (extra) Object.keys(extra).forEach(function (k) { base[k] = extra[k]; });
    return base;
  }
  function plot(id, data, layout) {
    var el = document.getElementById(id);
    if (!el) return Promise.resolve();
    if (!window.Plotly) { el.innerHTML = naHtml("(chart library missing)"); return Promise.resolve(); }
    layout = layout || {};
    /* G1: never a fixed pixel height; the flex container owns the size. */
    delete layout.height;
    delete layout.width;
    layout.autosize = true;
    function draw() {
      var node = document.getElementById(id);
      if (!node || !window.Plotly) return;
      window.Plotly.newPlot(node, data, layout, {
        displayModeBar: false, responsive: true, staticPlot: STATIC
      });
      /* G1: re-fit after layout so the chart owns the full panel height. */
      try {
        if (window.Plotly.Plots && window.Plotly.Plots.resize) window.Plotly.Plots.resize(node);
      } catch (e) { /* ignore */ }
    }
    /* G2: wait for webfonts so numerals never render in a fallback face. */
    if (document.fonts && document.fonts.ready) return document.fonts.ready.then(draw, draw);
    draw();
    return Promise.resolve();
  }
  function valOf(x) {
    if (x == null) return null;
    if (typeof x === "object" && "value" in x) return x["value"];
    return (typeof x === "number") ? x : null;
  }
  function signed(v, d) {
    if (v == null || !isFinite(v)) return null;
    var s = Number(v).toLocaleString("en-IN", {
      minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d
    });
    /* Use a true minus sign for negative deltas. */
    if (Number(v) < 0) s = "\u2212" + s.replace(/^-/, "");
    else if (Number(v) > 0) s = "+" + s;
    return s;
  }

  /* ================= 1. PLANT ================= */
  async function loadPlant() {
    var kpis = document.getElementById("plant-kpis");
    var tiles = document.getElementById("plant-tiles");
    var machines = await api("/machines");
    var summary = await api("/dashboard/summary", { hours: 24 });
    if ((machines && machines.error) || (summary && summary.error)) {
      kpis.innerHTML = '<div class="kpi-card">' + naHtml() + "</div>";
      tiles.innerHTML = '<div class="tile">' + naHtml() + "<p class='note'>" +
        esc((machines && machines.error) || (summary && summary.error) || "") + "</p></div>";
      setChips("chips-plant", ["data unavailable", "updated " + fmtT(nowIso())]);
      return;
    }
    var rows = summary.machines || [];
    var totE = rows.reduce(function (a, m) { return a + (m.energy_kwh || 0); }, 0);
    var totP = rows.reduce(function (a, m) { return a + (m.production_good_kg || 0); }, 0);
    var fleetSec = totP > 0 ? totE / totP * 1000 : null;
    var openAlerts = rows.reduce(function (a, m) { return a + (m.open_alerts || 0); }, 0);
    var src = (rows.map(function (m) { return m.source; }).filter(Boolean)[0]) || null;
    setChips("chips-plant", [
      src || "source not stated", rows.length + " machines", "updated " + fmtT(nowIso())
    ]);
    /* G4: SEC big slot is a number or an em dash; the reason stays small. */
    var secMachine = rows.filter(function (m) { return m.machine_type === "furnace"; })[0] || rows[0];
    var secStatus = secMachine && secMachine.sec_status;
    var secHtml = fleetSec != null
      ? numOrNa(fleetSec, 0, "kWh/t") + " " + badge("DERIVED")
      : dashBig() + '<div class="kpi-label">' + esc(secReason(secStatus)) + " " + badge("DERIVED") + "</div>";
    kpis.innerHTML =
      kpiCard("Energy today", numOrNa(totE, 1, "kWh"), src) +
      kpiCard("Production today", numOrNa(totP, 0, "kg"), src) +
      '<div class="kpi-card"><div class="kpi">' + secHtml + "</div>" +
      (fleetSec != null ? '<div class="kpi-label">Energy per tonne, whole plant</div>' : "") + "</div>" +
      kpiCard("Open alerts", '<span class="num">' + openAlerts + "</span>", null);
    var extra = await Promise.all([api("/energy/anomalies"), api("/recommendations"),
      api("/verification"), api("/machine-health"), api("/health/components")]);
    var anoms = ((extra[0] && extra[0].anomalies) || []).filter(function (e) { return e.status === "OPEN"; });
    var pend = ((extra[1] && extra[1].recommendations) || []).filter(function (r) { return r.status === "PENDING_REVIEW"; });
    var ver = ((extra[2] && extra[2].verification) || []).filter(function (v) { return v.outcome === "VERIFIED"; })[0];
    var hRows = (extra[3] && (extra[3].machine_health || extra[3].health || extra[3].results)) || (extra[3] instanceof Array ? extra[3] : []);
    var health = {};
    hRows.forEach(function (h) { health[h.machine_id] = h; });
    renderAttention(anoms, pend, ver);
    renderPlantDiagram(rows, health, anoms, extra[4] || {});
  }

  /* One-line drawing of the installation (docs/deployment/WIRING.md):
   * supply bus -> CT + meter per feeder -> machine, and the metering path
   * RS-485 daisy chain -> Modbus TCP converter -> edge gateway -> API.
   * Feeder width follows live kW; every figure comes from the API. */
  function svgEl(tag, attrs, text) {
    var s = "<" + tag;
    Object.keys(attrs).forEach(function (k) { s += " " + k + '="' + esc(attrs[k]) + '"'; });
    return s + ">" + (text != null ? esc(text) : "") + "</" + tag + ">";
  }
  function renderPlantDiagram(rows, health, anoms, comp) {
    var box = document.getElementById("plant-tiles");
    if (!rows.length) { box.innerHTML = naHtml("no machines returned"); return; }
    var W = 1520, busY = 44, meterY = 112, chainY = 176, boxY = 232, boxH = 196;
    var xs = rows.map(function (_, i) { return 150 + i * 330; });
    var maxKw = Math.max.apply(null, rows.map(function (m) { return m.latest_power_kw || 0; }).concat([1]));
    var alertM = {};
    anoms.forEach(function (e) { alertM[e.machine_id] = true; });
    var fresh = rows.every(function (m) { return m.latest_ts && Date.now() - new Date(m.latest_ts).getTime() < STALE_MS; });
    var s = [];
    /* supply bus */
    s.push(svgEl("text", { x: 20, y: 24, "class": "d-cap" }, "415 V three-phase plant supply"));
    s.push(svgEl("line", { x1: 20, y1: busY, x2: xs[xs.length - 1] + 150, y2: busY, "class": "d-bus" }));
    rows.forEach(function (m, i) {
      var x = xs[i], kw = m.latest_power_kw, hot = alertM[m.machine_id];
      var w = kw != null ? 2 + 12 * kw / maxKw : 2;
      var h = health[m.machine_id] || {};
      /* feeder: static line + a moving overlay whose speed follows kW */
      s.push(svgEl("line", { x1: x, y1: busY, x2: x, y2: boxY, "class": "d-feed" + (hot ? " hot" : ""), "stroke-width": w.toFixed(1) }));
      if (kw) {
        s.push(svgEl("line", { x1: x, y1: busY, x2: x, y2: boxY, "class": "d-flow", "stroke-width": Math.max(1, w / 3).toFixed(1),
          style: "animation-duration:" + (60 / Math.max(kw, 5)).toFixed(2) + "s" }));
      }
      s.push(svgEl("text", { x: x + 16, y: 88, "class": "d-kw" }, kw != null ? fmt(kw, 1) + " kW" : "no reading"));
      /* CT + meter on the feeder */
      s.push(svgEl("rect", { x: x - 34, y: meterY - 18, width: 68, height: 36, rx: 4, "class": "d-meter" }));
      s.push(svgEl("text", { x: x, y: meterY + 5, "class": "d-meter-t", "text-anchor": "middle" }, "meter"));
      s.push(svgEl("text", { x: x + 44, y: meterY + 4, "class": "d-note" }, "3 CTs"));
      s.push(svgEl("line", { x1: x, y1: meterY + 18, x2: x + 0.01, y2: chainY, "class": "d-sig" }));
      /* machine box */
      var bx = x - 140;
      s.push(svgEl("rect", { x: bx, y: boxY, width: 280, height: boxH, rx: 6, "class": "d-box" + (hot ? " hot" : "") }));
      s.push(svgEl("text", { x: bx + 18, y: boxY + 32, "class": "d-name" }, m.machine_name || m.machine_id));
      s.push(svgEl("text", { x: bx + 18, y: boxY + 52, "class": "d-note" }, (m.machine_type || "") + " · " + (m.latest_state || "state unknown")));
      var stats = [
        ["Energy today", m.energy_kwh != null ? fmt(m.energy_kwh, 0) + " kWh" : "—"],
        ["Per tonne", m.sec_kwh_per_t != null ? fmt(m.sec_kwh_per_t, 0) + " kWh/t" : "\u2014"],
        ["Health", h.health_score != null ? fmt(h.health_score, 0) + " / 100" : "—"],
        ["Open alerts", String(m.open_alerts || 0)]
      ];
      stats.forEach(function (st, k) {
        var sx = bx + 18 + (k % 2) * 132, sy = boxY + 88 + Math.floor(k / 2) * 54;
        s.push(svgEl("text", { x: sx, y: sy, "class": "d-note" }, st[0]));
        s.push(svgEl("text", { x: sx, y: sy + 24, "class": "d-val" + (k === 3 && m.open_alerts ? " hot" : "") }, st[1]));
      });
    });
    /* metering path: RS-485 daisy chain to the converter, then Ethernet */
    var px = 1085;
    s.push(svgEl("line", { x1: xs[0], y1: chainY, x2: px, y2: chainY, "class": "d-sig" }));
    s.push(svgEl("text", { x: xs[0] + 8, y: chainY - 8, "class": "d-note" }, "RS-485 daisy chain, Modbus RTU"));
    var nodes = [
      ["RS-485 → Modbus TCP converter", "DIN-rail, isolated", null],
      ["Edge gateway", "Raspberry Pi or industrial PC · buffers to disk if the link drops", null],
      ["JouleMitra server", "API " + (comp.api || "—") + " · database " + (comp.database || "—"), comp.database === "up"],
    ];
    nodes.forEach(function (n, i) {
      var ny = 140 + i * 96;
      s.push(svgEl("rect", { x: px, y: ny, width: 415, height: 64, rx: 6, "class": "d-node" + (n[2] ? " up" : "") }));
      s.push(svgEl("text", { x: px + 18, y: ny + 27, "class": "d-name" }, n[0]));
      s.push(svgEl("text", { x: px + 18, y: ny + 48, "class": "d-note" }, n[1]));
      if (i) s.push(svgEl("line", { x1: px + 40, y1: ny - 32, x2: px + 40, y2: ny, "class": "d-eth" }));
    });
    s.push(svgEl("text", { x: px + 52, y: 222, "class": "d-note" }, "Ethernet, Modbus TCP"));
    s.push(svgEl("text", { x: px + 52, y: 318, "class": "d-note" }, "HTTP, store-and-forward"));
    s.push(svgEl("text", { x: px, y: 424, "class": "d-note" },
      "Demo: the simulator posts to this same API. Data is SIMULATED" + (fresh ? ", fresh." : ".")));
    box.innerHTML = '<svg class="diagram" viewBox="0 0 ' + W + ' 440" role="img" aria-label="Plant one-line diagram with live power per machine">' +
      s.join("") + "</svg>";
  }
  /* One line per thing a plant manager should act on, each linked to the
   * screen that explains it. Built only from API rows. */
  function renderAttention(anoms, pend, ver) {
    var el = document.getElementById("plant-attn");
    var byM = {};
    anoms.forEach(function (e) {
      var cur = byM[e.machine_id];
      if (!cur || (e.deviation_pct || 0) > (cur.deviation_pct || 0)) byM[e.machine_id] = e;
    });
    var items = Object.keys(byM).map(function (mid) {
      var e = byM[mid];
      return '<li class="warn"><a href="#detect"><strong>' + esc(mid) + "</strong> — " + esc(ruleName(e.rule_id).toLowerCase()) +
        (e.deviation_pct != null ? ' <span class="num">(' + esc(signed(e.deviation_pct, 1)) + " %)</span>" : "") +
        " since " + esc(fmtT(e.window_start)) + "</a></li>";
    });
    if (pend.length) {
      items.push('<li><a href="#act"><strong>' + pend.length + " recommendation" + (pend.length > 1 ? "s" : "") +
        "</strong> waiting for an operator decision</a></li>");
    }
    if (ver) {
      var saved = ver.verified_saving_kwh != null ? ver.verified_saving_kwh : ver.saving_kwh;
      items.push('<li class="ok"><a href="#impact"><strong>Verified</strong> — ' + esc(fmt(saved, 0)) +
        " kWh saved (" + esc(fmt(ver.saving_pct, 1)) + " % less energy per tonne) after the last change</a></li>");
    }
    el.innerHTML = items.length ? items.join("") : '<li class="ok">Nothing needs attention right now.</li>';
  }
  function kpiCard(label, bodyHtml, src) {
    return '<div class="kpi-card"><div class="kpi">' + bodyHtml + "</div>" +
      '<div class="kpi-label">' + esc(label) + (src ? " " + badge(src) : "") + "</div></div>";
  }
  /* ================= 2. DETECT ================= */
  async function loadDetect() {
    var list = document.getElementById("detect-alerts-list");
    var anomalies = await api("/energy/anomalies");
    if (!anomalies || anomalies.error || !(anomalies.anomalies || []).length) {
      document.getElementById("detect-title").textContent = "Actual vs expected";
      document.getElementById("detect-chart").innerHTML = naHtml();
      list.innerHTML = "<p class='note'>" + naHtml() + " " + esc((anomalies && anomalies.error) || "no anomaly events in range") + "</p>";
      setChips("chips-detect", ["updated " + fmtT(nowIso())]);
      return;
    }
    var evs = anomalies.anomalies;
    var byM = {};
    evs.forEach(function (e) { (byM[e.machine_id] = byM[e.machine_id] || []).push(e); });
    var mid = Object.keys(byM).sort(function (a, b) { return byM[b].length - byM[a].length; })[0];
    var mine = byM[mid].slice().sort(function (a, b) { return new Date(a.window_start) - new Date(b.window_start); });
    var t0 = new Date(mine[0].window_start).getTime() - 6 * 3600 * 1000;
    var t1 = Math.max.apply(null, mine.map(function (e) { return new Date(e.window_end).getTime(); })) + 6 * 3600 * 1000;
    if (t1 - t0 > 96 * 3600 * 1000) { t1 = t0 + 96 * 3600 * 1000; }
    var start = new Date(t0).toISOString(), end = new Date(t1).toISOString();
    var sum = await api("/energy/summary", { start: start, end: end, machine_id: mid });
    var ivs = (sum && !sum.error && sum.intervals) || [];
    document.getElementById("detect-title").textContent = mid + " — actual vs expected (kWh per hour)";
    var c = colors();
    if (!ivs.length) {
      document.getElementById("detect-chart").innerHTML = naHtml();
    } else {
      var xs = ivs.map(function (r) { return px(r.window_start); });
      var lay = baseLayout({
        shapes: mine.map(function (e) {
          return { type: "rect", xref: "x", yref: "paper", x0: px(e.window_start), x1: px(e.window_end), y0: 0, y1: 1, fillcolor: c.accent, opacity: 0.14, line: { width: 0 } };
        }),
        yaxis: { title: "kWh", gridcolor: c.rule }
      });
      var withData = [];
      ivs.forEach(function (r, i) { if (r.actual_kwh != null) withData.push(i); });
      if (withData.length) {
        var pad = 2 * 3600 * 1000;
        var lo = new Date(ivs[withData[0]].window_start).getTime() - pad;
        var hi = new Date(ivs[withData[withData.length - 1]].window_start).getTime() + pad;
        lay.xaxis = lay.xaxis || {};
        lay.xaxis.range = [px(lo), px(hi)];
      }
      plot("detect-chart", [
        { x: xs, y: ivs.map(function (r) { return r.actual_kwh; }), type: "scatter", mode: "lines+markers", name: "actual", line: { color: c.accent, width: 3 } },
        { x: xs, y: ivs.map(function (r) { return r.expected_kwh; }), type: "scatter", mode: "lines", name: "expected", line: { color: c.ink3, width: 2, dash: "dash" } }
      ], lay);
    }
    /* Extra energy inside the flagged windows: sum of (actual - expected)
     * over those hours, straight from the scored intervals. */
    var extraKwh = 0, expKwh = 0, hrs = 0;
    ivs.forEach(function (r) {
      var t = new Date(r.window_start).getTime();
      var inside = mine.some(function (e) { return t >= new Date(e.window_start).getTime() && t < new Date(e.window_end).getTime(); });
      if (inside && r.actual_kwh != null && r.expected_kwh != null) { extraKwh += r.actual_kwh - r.expected_kwh; expKwh += r.expected_kwh; hrs++; }
    });
    document.getElementById("detect-sum").innerHTML = hrs
      ? "In the " + hrs + " flagged hours " + esc(mid) + ' used <span class="num hot">' + esc(fmt(extraKwh, 0)) +
        " kWh</span> more than expected for the work it did (" + esc(signed(expKwh ? extraKwh / expKwh * 100 : null, 0)) + " %). " + badge("DERIVED")
      : "";
    var src = (mine.map(function (e) { return e.source; }).filter(Boolean)[0]) || null;
    setChips("chips-detect", [src || "source not stated", mid, "updated " + fmtT(nowIso())]);
    /* G3 times as ranges; G6-rounded evidence; deviation % as a large mono number. */
    /* Alerts: the charted machine's events first, then the latest others;
     * every card names its machine so none is read against the wrong chart. */
    var all = evs.slice().sort(function (a, b) {
      return (b.machine_id === mid) - (a.machine_id === mid) || new Date(b.window_start) - new Date(a.window_start);
    });
    all.slice(0, 4).forEach(function (e, i) {
      TRAILS["alert" + i] = { title: ruleName(e.rule_id) + " on " + e.machine_id, steps: [
        ["Readings", "hourly energy for " + e.machine_id + " from the meter counter, " + fmtRange(e.window_start, e.window_end)],
        ["Expected", "the machine's own baseline: energy it normally uses for the production achieved"],
        ["Rule", (e.rule_id || "") + (e.metric ? " on " + e.metric : "") + (e.level ? ", level " + e.level : "")],
        ["Result", (e.deviation_pct != null ? signed(e.deviation_pct, 1) + " % against expected" : "deviation not returned") + (e.severity ? ", " + e.severity : "")],
        ["Evidence", typeof e.evidence === "string" ? e.evidence : JSON.stringify(e.evidence || "")]
      ], source: "GET /energy/anomalies (event " + String(e.id || "").slice(0, 8) + ") · SIMULATED data" };
    });
    list.innerHTML = all.slice(0, 4).map(function (e, i) {
      var dev = e.deviation_pct != null
        ? '<div class="alert-dev trace" data-trail="alert' + i + '" tabindex="0">' + esc(fmt(e.deviation_pct, 1)) + '%</div>' +
          '<div class="kpi-label">deviation vs expected</div>'
        : '<div class="kpi-label">' + naHtml("deviation") + "</div>";
      return '<div class="alert-card"><div class="row"><strong>' + esc(ruleName(e.rule_id)) + "</strong>" +
        '<span class="rule-code">' + esc(e.rule_id || "") + "</span>" +
        badge(e.severity, e.severity === "CRITICAL" ? "warn" : "accent") + " " + badge(e.status) +
        '<span class="alert-machine">' + esc(e.machine_id || "") + "</span></div>" +
        dev +
        "<p>" + esc(fmtRange(e.window_start, e.window_end)) + "</p>" +
        (e.evidence ? "<p>" + txt(typeof e.evidence === "string" ? e.evidence : JSON.stringify(e.evidence)) + "</p>" : "") + "</div>";
    }).join("");
  }

  /* ================= 3. HEALTH ================= */
  function friendlyHealthStatus(status) {
    if (!status || status === "OK") return "";
    return String(status).toLowerCase().replace(/_/g, " ");
  }
  async function loadHealth() {
    var hlist = document.getElementById("health-list");
    var ilist = document.getElementById("insights-list");
    var health = await api("/machine-health");
    var rows = (health && !health.error && health.health) || [];
    if (!rows.length) {
      hlist.innerHTML = "<p class='note'>" + naHtml() + " " + esc((health && health.error) || "no health rows") + "</p>";
    } else {
      var latest = {};
      rows.forEach(function (r) { latest[r.machine_id] = r; });
      var src = (rows.map(function (r) { return r.source; }).filter(Boolean)[0]) || null;
      setChips("chips-health", [src || "source not stated", Object.keys(latest).length + " machines", "updated " + fmtT(nowIso())]);
      /* G4/G5: score is a number or an em dash; status reason stays small. */
      hlist.innerHTML = Object.keys(latest).sort().map(function (mid) {
        var r = latest[mid];
        var s = r.health_score;
        var w = (s != null) ? Math.max(0, Math.min(100, s)) : 0;
        var st = friendlyHealthStatus(r.status);
        return '<div class="health-row"><div style="min-width:9rem"><strong>' + esc(mid) + "</strong><br>" +
          badge(r.state, r.state === "CRITICAL" ? "warn" : r.state === "NORMAL" ? "" : "accent") +
          (st ? " " + badge(st) : "") + "</div>" +
          '<div class="health-bar"><span style="width:' + w + '%"></span></div>' +
          '<div class="health-score">' + (s != null ? esc(fmt(s, 1)) : '<span class="num">\u2014</span>') + "</div></div>" +
          (r.reason ? "<p class='note'>" + esc(healthReason(r.reason)) + "</p>" : "") +
          ((s == null && !r.reason) ? "<p class='note'>" + naHtml("score") + "</p>" : "");
      }).join("");
    }
    var ins = await api("/insights", { start: daysAgoIso(7), end: nowIso() });
    var items = (ins && !ins.error && ins.insights) || [];
    if (!items.length) {
      ilist.innerHTML = "<p class='note'>" + naHtml() + " " + esc((ins && ins.error) || "no insights in the last 7 days") + "</p>";
    } else {
      ilist.innerHTML = items.slice(0, 5).map(function (it) {
        var when = (it.window_start && it.window_end)
          ? "<p>" + esc(fmtRange(it.window_start, it.window_end)) + "</p>" : "";
        var CAT = { ENERGY_ONLY: "Energy problem, machine healthy", HEALTH_ONLY: "Machine wear, energy normal",
          COINCIDENT: "Energy and wear together", ENERGY_ONLY_HEALTH_UNAVAILABLE: "Energy problem, health unknown" };
        return '<div class="insight"><div>' + badge(CAT[it.category] || it.category, it.category === "COINCIDENT" ? "accent" : "") +
          " <strong>" + esc(it.machine_id || "") + "</strong></div>" + when +
          "<p>" + txt(it.text || "") + "</p>" +
          (it.next_step ? "<p>Next step: " + txt(it.next_step) + "</p>" : "") + "</div>";
      }).join("");
    }
  }

  /* ================= 4. OPTIMISE ================= */
  function schedBars(sched, label, c) {
    if (!sched || !sched.heats || !sched.heats.length) return [];
    var slotMin = sched.slot_min || 15;
    var phases = [
      ["heating_slots", "heating", c.accent],
      ["melting_slots", "melting", c.ink2],
      ["holding_slots", "holding", c.ink3]
    ];
    return phases.map(function (ph) {
      var x = [], base = [];
      sched.heats.forEach(function (h) {
        var t = h.start_slot || 0;
        var order = ["heating_slots", "melting_slots", "holding_slots"];
        order.forEach(function (k) {
          if (k === ph[0]) { x.push((h[k] || 0) * slotMin / 60); base.push(t * slotMin / 60); }
          if (order.indexOf(k) < order.indexOf(ph[0])) t += (h[k] || 0);
        });
      });
      return {
        /* One lane per schedule: every heat sits on the same row, so the
         * shift in time reads at a glance. */
        x: x, base: base, y: sched.heats.map(function () { return label === "current" ? "Today" : "Recommended"; }),
        type: "bar", orientation: "h", name: ph[1], legendgroup: ph[1], showlegend: label === "current",
        width: 0.6,
        marker: { color: ph[2], line: { color: c.paper, width: 1 } },
        hovertemplate: "%{y}: " + ph[1] + " %{x:.2f}h<extra></extra>"
      };
    });
  }
  async function loadOptimise() {
    var chart = document.getElementById("opt-chart");
    var strip = document.getElementById("opt-tariff");
    var explain = document.getElementById("opt-explain");
    Array.prototype.forEach.call(document.querySelectorAll(".opt-hero"), function (n) { n.remove(); });
    var machines = await api("/machines");
    var run = null, mid = null;
    for (var i = 0; machines && !machines.error && i < machines.length; i++) {
      var r = await api("/optimization/schedule", { machine_id: machines[i].id });
      if (r && !r.error) { run = r; mid = machines[i].id; break; }
    }
    if (!run) {
      chart.innerHTML = naHtml();
      strip.innerHTML = "";
      explain.innerHTML = naHtml((machines && machines.error) || "no optimisation run yet");
      loadRibbon("furnace-01", []);
      setChips("chips-optimise", ["updated " + fmtT(nowIso())]);
      return;
    }
    var c = colors();
    document.getElementById("opt-title").textContent = mid + " — current vs recommended (" + (run.status || "?") + ")";
    var traces = schedBars(run.current_schedule || run.current, "current", c)
      .concat(schedBars(run.recommended_schedule || run.recommended, "recommended", c));
    var tp = ((run.metrics || {}).tariff_periods) || [];
    loadRibbon(mid, tp);
    if (traces.length) {
      /* Tariff periods drawn behind the heats: darker = dearer. */
      var maxRate = Math.max.apply(null, tp.map(function (t) { return t.rate; }).concat([1]));
      var bands = tp.filter(function (t) { return t.start_h != null; }).map(function (t) {
        return { type: "rect", layer: "below", xref: "x", yref: "paper", x0: t.start_h, x1: t.end_h || 24, y0: 0, y1: 1,
          fillcolor: c.accent, opacity: 0.05 + 0.2 * (t.rate / maxRate), line: { width: 0 } };
      });
      var bandLabels = tp.filter(function (t) { return t.start_h != null; }).map(function (t) {
        return { x: (t.start_h + (t.end_h || 24)) / 2, y: 1.02, xref: "x", yref: "paper", showarrow: false,
          text: "₹" + fmt(t.rate, 1) + "/kWh", font: { color: c.ink2, size: rem(0.8) } };
      });
      var lay = baseLayout({
        shapes: bands, annotations: bandLabels,
        barmode: "overlay", bargap: 0.3,
        xaxis: { title: "hour of day", gridcolor: c.rule, range: [0, 24], dtick: 2 },
        yaxis: { autorange: "reversed", automargin: true, ticksuffix: "  ", tickfont: { color: c.ink, size: rem(1.25) } },
        legend: { orientation: "h", x: 0, y: -0.28, font: { color: c.ink2 } }
      });
      lay.margin = { l: rem(1), r: rem(1), t: rem(2.5), b: rem(3.5) };
      plot("opt-chart", traces, lay);
    } else { chart.innerHTML = naHtml(); }
    var illustrative = tp.length && tp.every(function (t) { return t.source_class === "ASSUMPTION"; });
    strip.innerHTML = tp.map(function (t) {
      return '<span class="chip">' + esc(t.period) + ' · <span class="num">' + esc(fmt(t.rate, 1)) + "</span> INR/kWh</span>";
    }).join("") + (illustrative ? badge("illustrative tariff", "accent") : badge("plant tariff"));
    var m = run.metrics || {};
    var cur = m.current || {}, rec = m.recommended || {};
    /* Cost delta is the headline KPI, computed from current vs recommended. */
    var curC = valOf(cur.cost_inr), recC = valOf(rec.cost_inr);
    var dC = (curC != null && recC != null) ? recC - curC : null;
    var pC = (dC != null && curC) ? dC / curC * 100 : null;
    var heroHtml = '<div class="opt-hero">' +
      (dC != null
        ? '<span class="hero-delta">' + esc(signed(dC, 0)) + ' INR per day</span>' +
          '<span class="num">(' + esc(signed(pC, 1)) + '%)</span>' +
          (dC < 0 ? '<span class="opt-year">≈ ₹' + esc(fmt(-dC * 365 / 100000, 1)) +
            " lakh a year if every day ran this way</span>" : "")
        : dashBig()) +
      " " + badge("PROJECTED", "projected") + "</div>";
    strip.insertAdjacentHTML("beforebegin", heroHtml);
    /* Say in one sentence what changes; the solver's own text stays in the API. */
    var dE = (valOf(cur.energy_kwh) != null && valOf(rec.energy_kwh) != null) ? valOf(rec.energy_kwh) - valOf(cur.energy_kwh) : null;
    var dP = (valOf(cur.peak_kw) != null && valOf(rec.peak_kw) != null) ? valOf(rec.peak_kw) - valOf(cur.peak_kw) : null;
    var same = dE != null && dP != null && Math.abs(dE) < 1 && Math.abs(dP) < 1;
    explain.textContent = run.comparable === false
      ? "Not comparable: " + roundLong(run.comparability_reason || "")
      : (same ? "Same heats, same energy, same peak: only the start times move, so melting falls in lower-price tariff hours."
              : "Same required output at a lower bill; energy changes by " + signed(dE, 0) + " kWh" + (Math.abs(dP) < 1 ? " and the peak stays the same." : " and the peak by " + signed(dP, 0) + " kW.")) +
        " A suggestion for the shift planner, not an automatic change.";
    setChips("chips-optimise", ["PROJECTED", mid, "updated " + fmtT(nowIso())]);
  }

  /* ================= 5. ACT ================= */
  var STEPS = ["PENDING_REVIEW", "APPROVED", "APPLIED", "MEASURED", "VERIFIED"];
  function progressOf(rec, iv, ver) {
    var order = { PENDING_REVIEW: 0, CONFLICT: 0, APPROVED: 1, APPLIED: 2, MEASURED: 3 };
    var idx = 0;
    if (rec && rec.status in order) idx = Math.max(idx, order[rec.status]);
    if (iv) idx = Math.max(idx, 2);
    if (ver || (rec && ["VERIFIED", "NOT_VERIFIED", "NOT_COMPARABLE", "INSUFFICIENT_DATA"].indexOf(rec.status) >= 0)) idx = 4;
    else if (rec && rec.status === "MEASURED") idx = Math.max(idx, 3);
    return idx;
  }
  function outcomeBadge(outcome) {
    if (!outcome) return "";
    var cls = outcome === "VERIFIED" ? "verified"
      : (outcome === "NOT_COMPARABLE" || outcome === "NOT_VERIFIED") ? "warn" : "accent";
    return badge(outcome, cls);
  }
  async function loadAct() {
    var stepper = document.getElementById("act-stepper");
    var recBox = document.getElementById("act-rec");
    var listBox = document.getElementById("act-list");
    var recs = await api("/recommendations");
    var ivs = await api("/interventions");
    var vrs = await api("/verification");
    var allRecs = (recs && !recs.error && recs.recommendations) || [];
    var allIvs = (ivs && !ivs.error && ivs.interventions) || [];
    var allVrs = (vrs && !vrs.error && vrs.verification) || [];
    if (!allRecs.length) {
      stepper.innerHTML = ""; recBox.innerHTML = naHtml();
      listBox.innerHTML = "<p class='note'>" + naHtml() + " " + esc((recs && recs.error) || "no recommendations yet") + "</p>";
      setChips("chips-act", ["updated " + fmtT(nowIso())]);
      return;
    }
    var ivByRec = {};
    allIvs.forEach(function (iv) { ivByRec[iv.recommendation_id] = iv; });
    var verByIv = {};
    allVrs.forEach(function (v) { verByIv[v.intervention_id] = v; });
    var lead = allRecs.slice().sort(function (a, b) {
      var ia = allIvs.filter(function (iv) { return iv.recommendation_id === a.id; })[0];
      var ib = allIvs.filter(function (iv) { return iv.recommendation_id === b.id; })[0];
      return progressOf(b, ib) - progressOf(a, ia);
    })[0];
    var liv = allIvs.filter(function (iv) { return iv.recommendation_id === lead.id; })[0] || null;
    var lver = (liv && verByIv[liv.id]) || null;
    var idx = progressOf(lead, liv, lver);
    var finalLabel = (lver && lver.outcome) || (lead.status in { VERIFIED: 1, NOT_VERIFIED: 1, NOT_COMPARABLE: 1, INSUFFICIENT_DATA: 1 } ? lead.status : "VERIFIED");
    /* Every step shows its time when the API has one, else an em dash. */
    var stepTimes = [
      lead.created_at || null,
      lead.decided_at || null,
      (liv && liv.applied_at) || null,
      (liv && (liv.measurement_end || liv.measurement_start)) || null,
      (lver && lver.created_at) || null
    ];
    var STEP_NAMES = ["Suggested by JouleMitra", "Approved by operator", "Change applied", "Result measured", "Saving verified"];
    stepper.innerHTML = STEPS.map(function (s, i) {
      var label = (i === 4 && idx === 4 && finalLabel !== "VERIFIED") ? finalLabel : STEP_NAMES[i];
      var cls = i <= idx ? "step done" : "step";
      var ts = stepTimes[i] ? fmtT(stepTimes[i]) : "\u2014";
      return '<div class="' + cls + '">' + esc(label) +
        '<span class="step-ts">' + esc(ts) + "</span></div>";
    }).join("");
    /* The slide shows the gist; the full evidence stays in the API. */
    var ev = lead.evidence || {};
    var kn = (ev && typeof ev === "object" && ev.key_numbers instanceof Array) ? ev.key_numbers : null;
    var pend = allRecs.filter(function (r) { return r.status === "PENDING_REVIEW" && r.id !== lead.id; });
    recBox.innerHTML =
      "<h3 style='margin:0'>" + esc(lead.title || "recommendation") + "</h3>" +
      "<p>" + badge(ruleName(lead.rule_id)) + " " + badge(lead.severity, "accent") + " " + badge("confidence " + String(lead.confidence || "—").toLowerCase()) + "</p>" +
      "<p><strong>What we saw:</strong> " + txt(firstSentence(lead.reason)) +
      (kn && kn.length ? " Key numbers: " + txt(kn.slice(0, 3).join(", ")) + "." : "") + "</p>" +
      "<p><strong>What to do:</strong> " + txt(firstSentence(lead.proposed_action).replace(/\s*—\s*hold for Phase \d+ check\.?/i, ".")) + "</p>" +
      "<p><strong>Safety:</strong> an operator must approve; nothing is switched automatically.</p>" +
      "<h3 style='margin:var(--space-5) 0 var(--space-2) 0'>Waiting for a decision (" + pend.length + ")</h3>" +
      (pend.length ? '<ul class="pend-list">' + pend.slice(0, 4).map(function (r) {
        return "<li><strong>" + esc(r.machine_id || "") + "</strong> — " + esc(ruleName(r.rule_id)) +
          " " + badge(r.severity, r.severity === "CRITICAL" ? "warn" : "accent") + "<br><span class='note'>" + txt(r.title || "") + "</span></li>";
      }).join("") + "</ul>" : "<p class='note'>No other recommendations are waiting.</p>");
    /* Right panel: verification card for this intervention + audit trail
     * of lifecycle moves (times from the recommendation / intervention /
     * verification rows — the API exposes no separate audit endpoint). */
    var verCard;
    if (lver) {
      var saved = lver.verified_saving_kwh != null ? lver.verified_saving_kwh : lver.saving_kwh;
      verCard = "<h3 style='margin:0 0 var(--space-2) 0'>Verification</h3>" +
        "<p>" + outcomeBadge(lver.outcome) + "</p>" +
        "<p><strong>Verified saving:</strong> " +
        (saved != null
          ? '<span class="num">' + esc(fmt(saved, 1)) + "</span> kWh" +
            (lver.uncertainty_kwh != null ? " ± <span class='num'>" + esc(fmt(lver.uncertainty_kwh, 1)) + "</span> kWh" : "")
          : naHtml("saving")) + "</p>" +
        (lver.explanation ? "<p class='note'>" + txt(lver.explanation) + "</p>" : "");
    } else {
      verCard = "<h3 style='margin:0 0 var(--space-2) 0'>Verification</h3>" +
        "<p class='note'>" + naHtml("no verification for this intervention yet") + "</p>";
    }
    var moves = [
      ["Pending review", lead.created_at],
      ["Approved", lead.decided_at],
      ["Applied", liv && liv.applied_at],
      ["Measured to", liv && liv.measurement_end],
      [(lver && lver.outcome) || "Verified", lver && lver.created_at]
    ].filter(function (mv, i) { return i <= 1 || liv; });
    var auditHtml = "<h3 style='margin:var(--space-4) 0 0 0'>Audit trail</h3>" +
      '<ul class="audit-list">' + moves.map(function (mv) {
        return "<li><strong>" + esc(mv[0]) + "</strong> · <span class='mono'>" +
          (mv[1] ? esc(fmtT(mv[1])) : "\u2014") + "</span></li>";
      }).join("") + "</ul>";
    listBox.innerHTML = verCard + auditHtml;
    setChips("chips-act", ["SIMULATED", lead.machine_id || "", "updated " + fmtT(nowIso())]);
  }

  /* ================= 6. IMPACT ================= */
  function verifyFactsTable(v) {
    function row(label, valHtml) {
      return "<tr><td>" + esc(label) + '</td><td class="num">' + valHtml + "</td></tr>";
    }
    return '<table class="verify-table"><tbody>' +
      row("Counterfactual", v.counterfactual_kwh != null ? esc(fmt(v.counterfactual_kwh, 1)) + " kWh" : naHtml()) +
      row("Actual", v.actual_kwh != null ? esc(fmt(v.actual_kwh, 1)) + " kWh" : naHtml()) +
      row("Production before → after",
        (v.production_before_kg_h != null || v.production_after_kg_h != null)
          ? (v.production_before_kg_h != null ? esc(fmt(v.production_before_kg_h, 1)) : "—") + " → " +
            (v.production_after_kg_h != null ? esc(fmt(v.production_after_kg_h, 1)) : "—") + " kg/h"
          : naHtml()) +
      "</tbody></table>";
  }
  function card(valueHtml, label, extra) {
    return '<div class="kpi-card"><div class="kpi">' + valueHtml + '</div><div class="kpi-label">' +
      label + (extra ? " " + extra : "") + "</div></div>";
  }
  function pct(frac) { return frac != null ? Math.round(frac * 100) + " %" : "—"; }
  async function loadImpact() {
    var hero = document.getElementById("impact-hero");
    var chart = document.getElementById("impact-chart");
    var cards = document.getElementById("impact-cards");
    var guard = document.getElementById("guardrail");
    var screen = document.getElementById("screen-impact");
    screen.classList.remove("refusal");
    var vrs = await api("/verification");
    var ivs = await api("/interventions");
    var rows = (vrs && !vrs.error && vrs.verification) || [];
    var ivById = {};
    ((ivs && !ivs.error && ivs.interventions) || []).forEach(function (iv) { ivById[iv.id] = iv; });
    var verified = rows.filter(function (v) { return v.outcome === "VERIFIED"; })[0] || null;
    var nc = rows.filter(function (v) { return v.outcome === "NOT_COMPARABLE"; })[0] || null;
    var c = colors();

    if (verified) {
      var v = verified, iv = ivById[v.intervention_id] || {};
      var saved = v.verified_saving_kwh != null ? v.verified_saving_kwh : v.saving_kwh;
      var conf = v.confidence != null ? Math.round(v.confidence * 100) + " %" : "stated confidence";
      /* SEC before/after, DERIVED from verified API figures: the counterfactual
       * is predicted for the output actually produced, so both kWh values share
       * one denominator (mean post-change kg/h x measured hours). */
      var tonnes = (v.production_after_kg_h != null && v.n_post) ? v.production_after_kg_h * v.n_post / 1000 : null;
      var secCf = tonnes ? v.counterfactual_kwh / tonnes : null;
      var secAct = tonnes ? v.actual_kwh / tonnes : null;
      var ratio = (saved != null && v.uncertainty_kwh) ? saved / v.uncertainty_kwh : null;

      var mdl0 = v.model || {};
      TRAILS.impact = { title: "How −" + fmt(v.saving_pct, 1) + " % was produced", steps: [
        ["Before the change", v.n_baseline + " hourly readings, " + fmtRange(iv.baseline_start, iv.baseline_end) + ", " + pct(v.baseline_complete_frac) + " complete"],
        ["Model of normal", (v.method || "regression on hourly production") + (mdl0.cv_rmse_pct != null ? "; error CV(RMSE) " + fmt(mdl0.cv_rmse_pct, 1) + " %, bias NMBE " + fmt(mdl0.nmbe_pct, 1) + " %" : "") + (mdl0.g14 ? ", ASHRAE Guideline 14 " + mdl0.g14 : "")],
        ["After the change", v.n_post + " hourly readings, " + fmtRange(iv.measurement_start, iv.measurement_end) + ", " + pct(v.post_complete_frac) + " complete"],
        ["Expected without the change", fmt(v.counterfactual_kwh, 1) + " kWh, predicted for the output actually made (" + fmt(v.production_after_kg_h, 1) + " kg/h)"],
        ["Measured", fmt(v.actual_kwh, 1) + " kWh"],
        ["Saving", fmt(saved, 1) + " kWh ± " + fmt(v.uncertainty_kwh, 1) + " at " + conf + "; larger than the error band, so VERIFIED"],
        ["Per tonne", tonnes ? "both totals ÷ " + fmt(tonnes, 2) + " t made = " + fmt(secCf, 0) + " → " + fmt(secAct, 0) + " kWh/t (−" + fmt(v.saving_pct, 1) + " %)" : "not available"]
      ], source: "GET /verification (row " + String(v.id).slice(0, 8) + "), GET /interventions · SIMULATED data" };
      hero.innerHTML =
        '<div class="hero-left"><span class="stamp">VERIFIED</span>' +
        '<div class="hero-num trace" data-trail="impact" tabindex="0">−' + esc(fmt(v.saving_pct, 1)) + '<span class="hero-unit">%</span></div>' +
        '<p class="hero-claim">less electricity per tonne of metal on ' + esc(iv.machine_id || "this machine") +
        ", at comparable output</p></div>" +
        '<div class="hero-right">' +
        '<div class="hero-kv"><span class="num">' + esc(fmt(saved, 1)) + ' kWh</span><span>saved in ' +
        esc(String(v.n_post || "—")) + " measured hours</span></div>" +
        '<div class="hero-kv"><span class="num">± ' + esc(fmt(v.uncertainty_kwh, 1)) + ' kWh</span><span>error band at ' +
        esc(conf) + (ratio ? " — the saving is " + esc(fmt(ratio, 1)) + "× larger" : "") + "</span></div></div>";

      var cost = v.cost_impact || {}, co2 = v.co2_impact || {};
      cards.innerHTML =
        card(secCf != null ? '<span class="num">' + esc(fmt(secCf, 0)) + " → " + esc(fmt(secAct, 0)) + '</span><span class="unit">kWh/t</span>' : dashBig(),
          "Specific energy (SEC), expected → actual", badge("DERIVED from VERIFIED", "verified")) +
        card(cost.value_inr != null ? '<span class="num">₹ ' + esc(fmt(cost.value_inr, 0)) + "</span>" : dashBig(),
          "cost saved in the measured period · illustrative tariff", badge(cost.source_class || "ASSUMPTION")) +
        card(co2.value_kg != null ? '<span class="num">' + esc(fmt(co2.value_kg, 0)) + '</span><span class="unit">kg CO₂</span>' : dashBig(),
          "avoided · CO₂ only, grid factor " + esc(String((co2.factor || {}).value || "—")), co2.provisional ? badge("provisional", "accent") : "") +
        card('<span class="num">' + esc(fmt(v.production_before_kg_h, 0)) + " → " + esc(fmt(v.production_after_kg_h, 0)) + '</span><span class="unit">kg/h</span>',
          "output before → after", v.comparable ? badge("COMPARABLE", "verified") : "");

      var mdl = v.model || {};
      guard.innerHTML = '<ol class="steps">' +
        "<li><strong>Learned the furnace's normal energy for each kg it makes</strong>" +
        "<span>" + esc(String(v.n_baseline || "—")) + " hours before the change (" + esc(fmtRange(iv.baseline_start, iv.baseline_end)) +
        "), " + esc(pct(v.baseline_complete_frac)) + " of data present" +
        (mdl.cv_rmse_pct != null ? " · model error " + esc(fmt(mdl.cv_rmse_pct, 1)) + " %" + (mdl.g14 ? ", ASHRAE Guideline 14: " + esc(mdl.g14.toLowerCase()) : "") : "") +
        "</span></li>" +
        "<li><strong>Predicted the next " + esc(String(v.n_post || "—")) + " hours without the change</strong>" +
        "<span>" + esc(fmt(v.counterfactual_kwh, 1)) + " kWh expected for the output actually produced</span></li>" +
        "<li><strong>Measured what really happened</strong>" +
        "<span>" + esc(fmt(v.actual_kwh, 1)) + " kWh. The gap is larger than the ±" + esc(fmt(v.uncertainty_kwh, 1)) +
        " kWh error band, so the saving is <b class='ok'>verified</b>.</span></li></ol>" +
        "<p class='guard-line'>If output or operating conditions shift too far, JouleMitra reports " +
        "<b>NOT COMPARABLE</b> and claims nothing.</p>";

      document.getElementById("impact-chart-title").textContent = "Energy in the measured period (kWh)";
      document.getElementById("impact-chart-note").style.display = "";
      chart.style.display = "";
      plot("impact-chart", [
        { y: ["Expected", "Actual"], x: [v.counterfactual_kwh, v.actual_kwh], type: "bar", orientation: "h",
          name: "energy", marker: { color: [c.ink3, c.accent] },
          text: [fmt(v.counterfactual_kwh, 0), fmt(v.actual_kwh, 0)], textposition: "inside", insidetextanchor: "middle",
          textfont: { color: c.paper, size: rem(1.25) },
          error_x: { type: "data", array: [v.uncertainty_kwh || 0, 0], visible: !!v.uncertainty_kwh, color: c.ink, thickness: 2, width: rem(0.5) } },
        { y: ["Actual"], x: [saved], base: [v.actual_kwh], type: "bar", orientation: "h", name: "saved",
          marker: { color: c.verified }, text: ["−" + fmt(saved, 0) + " saved"], textposition: "outside",
          textfont: { color: c.verified, size: rem(1.25) } }
      ], baseLayout({
        barmode: "overlay", showlegend: false, bargap: 0.35,
        margin: { l: rem(1), r: rem(1), t: rem(0.5), b: rem(2.5) },
        xaxis: { gridcolor: c.rule, zerolinecolor: c.rule, range: [0, v.counterfactual_kwh * 1.3] },
        yaxis: { autorange: "reversed", automargin: true, ticksuffix: "  ", tickfont: { color: c.ink, size: rem(1.125) } }
      }));
    } else if (nc) {
      /* The refusal is the hero: no saving figure anywhere on the slide. */
      screen.classList.add("refusal");
      var reasons = nc.comparability_reasons || [];
      var lead = reasons.filter(function (r) { return /production/i.test(r); })[0] || reasons[0] || "";
      hero.innerHTML = '<div class="hero-left"><span class="stamp warn">NOT COMPARABLE</span>' +
        '<div class="hero-title">No saving claimed.</div>' +
        (lead ? '<p class="hero-claim">' + txt(lead) + "</p>" : "") + "</div>";
      cards.innerHTML = "";
      guard.innerHTML = "<p class='lead'>" + txt(nc.explanation || "") + "</p>" +
        (reasons.length ? '<ul class="verify-list">' + reasons.map(function (r) { return "<li>" + txt(r) + "</li>"; }).join("") + "</ul>" : "") +
        "<p class='guard-line'>A saving is only reported when the period after the change is comparable to the period before it.</p>";
      document.getElementById("impact-story-title").textContent = "Why nothing is claimed";
      document.getElementById("impact-chart-title").textContent = "What was measured";
      document.getElementById("impact-chart-note").style.display = "none";
      chart.style.display = "";
      chart.innerHTML = verifyFactsTable(nc);
    } else {
      hero.innerHTML = '<div class="hero-left"><div class="hero-title">No verified saving yet.</div>' +
        "<p class='hero-claim'>" + (rows.length ? "Latest outcome: " + badge(rows[0].outcome, "accent") + " " + txt(rows[0].explanation || "") : naHtml("no verification has run")) + "</p></div>";
      cards.innerHTML = "";
      guard.innerHTML = "";
      chart.innerHTML = naHtml();
    }
    var any = verified || nc || rows[0];
    setChips("chips-impact", [
      verified ? "VERIFIED" : (nc ? "NOT_COMPARABLE" : "SIMULATED"),
      "SIMULATED data",
      "updated " + fmtT(nowIso())
    ].concat(any && ivById[any.intervention_id] ? [ivById[any.intervention_id].machine_id] : []));
  }

  /* ================= rupee ribbon (Optimise) =================
   * The furnace's last 24 h as one strip of state stretches. Energy per
   * stretch is the meter counter difference; each 5-minute slice is priced
   * at the tariff period it falls in (Asia/Kolkata hour of day). */
  function rateAt(periods, iso) {
    var h = Number(px(iso).slice(11, 13)) + Number(px(iso).slice(14, 16)) / 60;
    for (var i = 0; i < periods.length; i++) {
      var p = periods[i], end = p.end_h || 24;
      if (p.start_h != null && h >= p.start_h && h < end) return p.rate;
    }
    return null;
  }
  var STATE_TXT = { heating: "heating", melting: "melting", holding: "holding, no pour", idle: "idle" };
  async function loadRibbon(mid, periods) {
    var box = document.getElementById("ribbon"), axis = document.getElementById("ribbon-axis"), sum = document.getElementById("ribbon-sum");
    var tel = await api("/telemetry", { machine_id: mid, limit: 400 });
    if (!tel || tel.error || tel.length < 2) { box.innerHTML = naHtml("no telemetry"); axis.innerHTML = ""; sum.innerHTML = ""; return; }
    var rows = tel.slice().sort(function (a, b) { return new Date(a.ts) - new Date(b.ts); });
    var t1 = new Date(rows[rows.length - 1].ts).getTime(), t0 = t1 - 24 * 3600 * 1000;
    rows = rows.filter(function (r) { return new Date(r.ts).getTime() >= t0; });
    var runs = [], total = 0, priced = true;
    for (var i = 1; i < rows.length; i++) {
      var r = rows[i], dE = r.energy_kwh - rows[i - 1].energy_kwh;
      if (!(dE >= 0)) continue;
      var rate = rateAt(periods, r.ts);
      if (rate == null) priced = false;
      var inr = rate != null ? dE * rate : 0, st = r.machine_state || "unknown";
      var dt = new Date(r.ts) - new Date(rows[i - 1].ts);
      var last = runs[runs.length - 1];
      if (last && last.state === st) { last.kwh += dE; last.inr += inr; last.ms += dt; last.end = r.ts; }
      else runs.push({ state: st, kwh: dE, inr: inr, ms: dt, start: rows[i - 1].ts, end: r.ts });
      total += inr;
    }
    var span = runs.reduce(function (a, x) { return a + x.ms; }, 0) || 1;
    var waste = runs.filter(function (x) { return x.state === "holding" || x.state === "idle"; });
    var wInr = waste.reduce(function (a, x) { return a + x.inr; }, 0);
    var wKwh = waste.reduce(function (a, x) { return a + x.kwh; }, 0);
    box.innerHTML = runs.map(function (x) {
      var pct = x.ms / span * 100;
      return '<div class="seg s-' + esc(x.state) + '" style="flex-grow:' + pct.toFixed(3) + '" title="' +
        esc(STATE_TXT[x.state] || x.state) + " · " + esc(fmtRange(x.start, x.end)) + " · " + esc(fmt(x.kwh, 0)) + " kWh" +
        (priced ? " · ₹" + esc(fmt(x.inr, 0)) : "") + '">' +
        (pct > 3.2 && priced ? '<span>₹' + esc(fmt(x.inr, 0)) + "</span>" : "") + "</div>";
    }).join("");
    var ticks = [];
    for (var k = 0; k <= 4; k++) ticks.push('<span style="left:' + (k * 25) + '%">' + esc(fmtT(new Date(t0 + k * 6 * 3600 * 1000).toISOString())) + "</span>");
    axis.innerHTML = ticks.join("");
    TRAILS.ribbon = { title: "Where the rupees went", steps: [
      ["Meter readings", rows.length + " readings from " + mid + " in the last 24 h (" + fmtRange(rows[0].ts, rows[rows.length - 1].ts) + ")"],
      ["Energy per slice", "difference of the meter's cumulative kWh counter between readings"],
      ["Price per slice", priced ? "the tariff period the slice falls in: " + periods.map(function (p) { return p.period + " ₹" + fmt(p.rate, 1); }).join(", ") : "tariff time bands not available"],
      ["Stretches", runs.length + " runs of the same machine state"],
      ["No-output share", fmt(wKwh, 0) + " kWh in holding or idle = ₹" + fmt(wInr, 0)]
    ], source: "GET /telemetry, GET /optimization/schedule (tariff) · SIMULATED data · illustrative tariff" };
    sum.innerHTML = priced
      ? '<span class="num trace" data-trail="ribbon">₹' + esc(fmt(total, 0)) + "</span> spent in 24 h. " +
        '<span class="num hot">₹' + esc(fmt(wInr, 0)) + "</span> of it (" + esc(fmt(total ? wInr / total * 100 : 0, 0)) +
        " %) went to holding or idle, when the furnace was powered but not pouring. " + badge("MEASURED energy", "accent") + " " + badge("illustrative tariff")
      : naHtml("tariff time bands not returned, so stretches are shown without rupees");
  }

  /* ================= 7. SCALE (payback) =================
   * Only the saving percentage is measured (the verified result). Every
   * other input is the viewer's to change and is labelled as such. */
  var PB = null;
  async function loadPayback() {
    var vrs = await api("/verification");
    var v = ((vrs && vrs.verification) || []).filter(function (x) { return x.outcome === "VERIFIED"; })[0];
    var run = await api("/optimization/schedule", { machine_id: "furnace-01" });
    var tp = (run && run.metrics && run.metrics.tariff_periods) || [];
    var avgRate = tp.length ? tp.reduce(function (a, p) { return a + p.rate * ((p.end_h || 24) - p.start_h); }, 0) / 24 : null;
    var box = document.getElementById("pb-inputs");
    if (!v) { box.innerHTML = naHtml("no verified saving yet — run the demo first"); document.getElementById("pb-out").innerHTML = ""; return; }
    var kwhDay = v.counterfactual_kwh / v.n_post * 24;
    var factor = ((v.co2_impact || {}).factor || {}).value;
    if (!PB) PB = { hw: 60000, sub: 1500, rate: avgRate ? Math.round(avgRate * 100) / 100 : 7.5, days: 300, kwhDay: Math.round(kwhDay), furnaces: 1 };
    var fields = [
      ["hw", "Hardware + install per site", "₹", 10000, 300000, 5000, "example input: meter, converter, gateway, fitting. Replace with a real quote."],
      ["sub", "JouleMitra subscription", "₹ / month", 0, 10000, 250, "example input"],
      ["rate", "Average tariff", "₹ / kWh", 4, 14, 0.25, avgRate ? "default = the site tariff averaged over 24 h (illustrative)" : "example input"],
      ["kwhDay", "Furnace energy per day", "kWh", 200, 10000, 50, "default = this furnace's expected use: " + fmt(v.counterfactual_kwh, 0) + " kWh over " + v.n_post + " h"],
      ["days", "Operating days per year", "days", 150, 365, 5, "example input"],
      ["furnaces", "Furnaces per site", "", 1, 6, 1, "example input"]
    ];
    box.innerHTML = '<div class="pb-fixed"><span class="num">' + esc(fmt(v.saving_pct, 1)) + ' %</span> less energy per tonne ' +
      badge("VERIFIED", "verified") + '<p class="note">The only measured input. Everything below is yours to change.</p></div>' +
      fields.map(function (f) {
        return '<label class="pb-field"><span class="pb-name">' + esc(f[1]) + '</span><output id="pbv-' + f[0] + '"></output>' +
          '<input type="range" min="' + f[3] + '" max="' + f[4] + '" step="' + f[5] + '" value="' + PB[f[0]] + '" data-k="' + f[0] + '">' +
          '<span class="note">' + esc(f[6]) + "</span></label>";
      }).join("");
    function calc() {
      fields.forEach(function (f) {
        document.getElementById("pbv-" + f[0]).textContent =
          (f[2].indexOf("₹") === 0 ? "₹ " : "") + fmt(PB[f[0]], f[5] < 1 ? 2 : 0) + (f[2] && f[2].indexOf("₹") !== 0 ? " " + f[2] : f[2].replace("₹", ""));
      });
      var kwhYr = PB.kwhDay * PB.furnaces * PB.days * v.saving_pct / 100;
      var inrYr = kwhYr * PB.rate;
      var net = inrYr / 12 - PB.sub;
      var months = net > 0 ? PB.hw / net : null;
      var co2 = factor != null ? kwhYr * factor / 1000 : null;
      var scale = [1, 10, 100, 1000].map(function (n) {
        return "<tr><td>" + n.toLocaleString("en-IN") + " SME" + (n > 1 ? "s" : "") + '</td><td class="num">' + fmt(kwhYr * n / 1000, 0) +
          ' MWh</td><td class="num">₹ ' + fmt(inrYr * n / 1e7, 2) + ' Cr</td><td class="num">' + (co2 != null ? fmt(co2 * n, 0) + " t" : "—") + "</td></tr>";
      }).join("");
      var bar = months != null ? Math.min(months / 36 * 100, 100) : 100;
      document.getElementById("pb-out").innerHTML =
        '<div class="pb-hero"><span class="pb-months">' + (months != null ? fmt(months, 1) : "—") + '</span><span class="pb-unit">months to pay back</span></div>' +
        '<div class="pb-ruler"><div class="pb-fill" style="width:' + bar.toFixed(1) + '%"></div>' +
        [0, 6, 12, 18, 24, 30, 36].map(function (m) { return '<i style="left:' + (m / 36 * 100) + '%">' + m + "</i>"; }).join("") + "</div>" +
        (months == null ? '<p class="note">The monthly saving does not cover the subscription at these inputs.</p>' : "") +
        '<p class="pb-line">Per site each year: <b class="num">' + fmt(kwhYr, 0) + ' kWh</b> and <b class="num">₹ ' + fmt(inrYr, 0) +
        "</b> saved" + (co2 != null ? ", <b class=\"num\">" + fmt(co2, 1) + " t CO₂</b> avoided (provisional grid factor " + fmt(factor, 2) + ")" : "") + ".</p>" +
        '<table class="pb-scale"><thead><tr><th>Rolled out to</th><th>Energy saved / yr</th><th>Money saved / yr</th><th>CO₂ avoided / yr</th></tr></thead><tbody>' + scale + "</tbody></table>" +
        '<p class="note">Projection: assumes every site matches the verified ' + fmt(v.saving_pct, 1) + " % and the inputs on the left. " + badge("PROJECTED", "projected") + "</p>";
    }
    box.querySelectorAll("input").forEach(function (inp) {
      inp.addEventListener("input", function () { PB[inp.getAttribute("data-k")] = Number(inp.value); calc(); });
    });
    calc();
    setChips("chips-payback", ["VERIFIED saving", "example inputs", "updated " + fmtT(nowIso())]);
  }

  /* ================= number trail =================
   * Any element with data-trail="key" opens a side panel listing how that
   * number was produced, step by step, from the rows the screen fetched. */
  var TRAILS = {};
  function openTrail(key) {
    var t = TRAILS[key], d = document.getElementById("trail");
    if (!t) return;
    d.innerHTML = '<button class="trail-close" type="button" aria-label="Close">×</button><h2>' + esc(t.title) + "</h2>" +
      '<ol class="trail-steps">' + t.steps.map(function (s) { return "<li><b>" + esc(s[0]) + "</b><span>" + esc(roundLong(s[1])) + "</span></li>"; }).join("") + "</ol>" +
      '<p class="note">Source: ' + esc(t.source) + "</p>";
    d.classList.add("open");
    d.querySelector(".trail-close").addEventListener("click", closeTrail);
    d.querySelector(".trail-close").focus();
  }
  function closeTrail() { document.getElementById("trail").classList.remove("open"); }
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("[data-trail]");
    if (el) openTrail(el.getAttribute("data-trail"));
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeTrail();
    var el = document.activeElement;
    if (e.key === "Enter" && el && el.getAttribute && el.getAttribute("data-trail")) openTrail(el.getAttribute("data-trail"));
  });

  /* ---------- router ---------- */
  var loaders = { plant: loadPlant, detect: loadDetect, health: loadHealth, optimise: loadOptimise, act: loadAct, impact: loadImpact, payback: loadPayback };
  function current() {
    var h = (window.location.hash || "#plant").replace("#", "").split("?")[0];
    return SCREENS.indexOf(h) >= 0 ? h : "plant";
  }
  function show() {
    var s = current();
    SCREENS.forEach(function (k) {
      document.getElementById("screen-" + k).classList.toggle("active", k === s);
    });
    document.querySelectorAll(".nav-step").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-screen") === s);
    });
    closeTrail();
    /* ?trail=<key> opens a number's trail once the screen has loaded
     * (used to capture the provenance panel for the deck). */
    Promise.resolve(loaders[s]()).then(function () {
      var t = new URLSearchParams(window.location.search).get("trail");
      if (t) openTrail(t);
    });
  }
  window.addEventListener("hashchange", show);

  /* The stage is a fixed 16:9 canvas; scale it to fit the window so the
   * browser shows exactly what the PPT slide shows. */
  function fit() {
    var st = document.getElementById("stage");
    var s = Math.min(window.innerWidth / st.offsetWidth, window.innerHeight / st.offsetHeight);
    document.documentElement.style.setProperty("--scale", String(s));
  }
  window.addEventListener("resize", fit);
  fit();

  /* Arrow keys step through the loop like slides. */
  document.addEventListener("keydown", function (e) {
    if (e.target && e.target.tagName === "INPUT") return;
    var step = e.key === "ArrowRight" || e.key === "PageDown" ? 1 : e.key === "ArrowLeft" || e.key === "PageUp" ? -1 : 0;
    if (!step) return;
    var i = SCREENS.indexOf(current()) + step;
    if (i >= 0 && i < SCREENS.length) window.location.hash = "#" + SCREENS[i];
  });

  if (!window.location.hash) window.location.hash = "#plant";
  show();
})();
