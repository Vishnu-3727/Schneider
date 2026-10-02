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

  /* Single bold dark look: no theme param. ?theme= is ignored. */

  /* Last plant rows/total from the plant loader (summary.machines). The
   * theme-C Plant hero reads this instead of scraping tile text, so 3D
   * floor labels ("3 meters", "CTs", "ok") can never leak into the kW sum. */
  var PLANT_KW = { total: null, count: 0 };

  /* Hero tiles (all screens): one hero tile per screen that has no
   * single existing hero element (plant, detect, health, act). Every value is
   * scraped from numbers the screen already rendered; missing → em dash. */
  function cNum(text) {
    var m = String(text == null ? "" : text).replace(/,/g, "").match(/-?\d+(\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }
  function cDash() { return '<span class="num">\u2014</span>'; }
  function cHeroUpsert(screen, label, valueHtml, sub, prov) {
    var body = document.querySelector("#screen-" + screen + " .screen-body");
    if (!body) return;
    var el = body.querySelector(':scope > .c-hero[data-hero="' + screen + '"]');
    if (!el) {
      el = document.createElement("div");
      el.className = "c-hero";
      el.setAttribute("data-hero", screen);
      el.setAttribute("role", "status");
      body.insertBefore(el, body.firstChild);
    }
    el.setAttribute("data-prov", prov);
    el.innerHTML = '<span class="c-label">' + esc(label) + "</span>" +
      '<span class="c-num">' + valueHtml + "</span>" +
      (sub ? '<span class="c-sub">' + esc(sub) + "</span>" : "");
  }
  function refreshCHero(screen) {
    if (screen === "plant") {
      cHeroUpsert("plant", "Live plant load",
        PLANT_KW.count ? esc(fmt(PLANT_KW.total, 1)) + " kW" : cDash(),
        PLANT_KW.count ? PLANT_KW.count + " feeds live" : "no live readings", "measured");
    } else if (screen === "detect") {
      var devs = [];
      Array.prototype.forEach.call(document.querySelectorAll("#detect-alerts-list .alert-dev"), function (n) {
        var v = cNum(n.textContent);
        if (v != null) devs.push(v);
      });
      var mid = document.querySelector("#detect-alerts-list .alert-machine");
      var sumEl = document.getElementById("detect-sum");
      var sumHtml = sumEl ? sumEl.innerHTML : "";
      cHeroUpsert("detect", "Largest deviation",
        devs.length ? esc(fmt(Math.max.apply(null, devs), 1)) + "%" : cDash(),
        "", "measured");
      /* The lead sentence sits beside the hero number in the band instead of
       * under the chart: copy it into the hero and hide the original so it
       * is not shown twice. */
      var dHero = document.querySelector('#screen-detect .c-hero[data-hero="detect"]');
      if (dHero) {
        var dNum = dHero.querySelector(".c-num");
        dHero.innerHTML = '<span class="c-main"><span class="c-label">Largest deviation</span>' +
          (dNum ? dNum.outerHTML : "") + "</span>" +
          '<span class="c-side">' + (sumHtml || (mid ? esc(mid.textContent.trim()) + " · vs expected" : "vs expected")) + "</span>";
      }
      if (sumEl) sumEl.style.display = "none";
    } else if (screen === "health") {
      var scores = [];
      Array.prototype.forEach.call(document.querySelectorAll("#health-list .health-score"), function (n) {
        var v = cNum(n.textContent);
        if (v != null) scores.push(v);
      });
      cHeroUpsert("health", "Lowest health score",
        scores.length ? esc(fmt(Math.min.apply(null, scores), 1)) + " / 100" : cDash(),
        scores.length ? "lowest of " + scores.length + " machines" : "no scores", "neutral");
    } else if (screen === "act") {
      var steps = document.querySelectorAll("#act-stepper .step");
      var done = document.querySelectorAll("#act-stepper .step.done");
      if (!steps.length) {
        cHeroUpsert("act", "Current step", cDash(), "no recommendation yet", "neutral");
      } else {
        var last = done.length ? done[done.length - 1] : steps[0];
        var name = last ? last.childNodes[0].textContent.trim() : "";
        cHeroUpsert("act", "Current step",
          "Step " + done.length + " of " + steps.length, name, "neutral");
      }
    }
  }

  var SCREENS = ["plant", "detect", "heats", "twin", "bill", "health", "optimise", "brief", "act", "impact", "payback"];
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
      font: { family: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif", color: c.ink2, size: rem(0.875) },
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
      /* Charts animate in on first draw per visit (opacity on the chart
       * container; skipped under reduced-motion / ?static=1). */
      chartIntro(node);
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

  /* ---------- motion (transform/opacity only) ----------
   * Screen fades, hero count-ups and chart intros all run on transform /
   * opacity and are skipped under prefers-reduced-motion or ?static=1, in
   * which case the final values are already in the DOM. */
  var EASE_OUT = "cubic-bezier(0.2, 0.7, 0.2, 1)";
  function reducedMotion() {
    return STATIC ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function chartIntro(el) {
    if (reducedMotion() || !el || !el.animate) return;
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 280, easing: EASE_OUT });
  }
  /* Count one text node from 0 to each number it holds (~600 ms, ease-out),
   * preserving the exact final text (units, sign, decimals, separators). */
  function countUpNode(node) {
    var orig = node.nodeValue;
    if (!orig || !/\d/.test(orig)) return;
    var re = /[+\-−]?\d[\d,]*(?:\.\d+)?/g;
    var tokens = [], last = 0, m;
    while ((m = re.exec(orig)) !== null) {
      if (m.index > last) tokens.push({ t: orig.slice(last, m.index) });
      var tok = m[0], sign = "";
      if (tok[0] === "+" || tok[0] === "-" || tok[0] === "−") { sign = tok[0]; tok = tok.slice(1); }
      var target = parseFloat(tok.replace(/,/g, ""));
      if (!isFinite(target)) {
        tokens.push({ t: m[0] });
      } else {
        var dec = /\.\d+/.exec(tok);
        tokens.push({ n: true, sign: sign, target: target, nd: dec ? dec[0].length - 1 : 0 });
      }
      last = m.index + m[0].length;
    }
    if (last < orig.length) tokens.push({ t: orig.slice(last) });
    if (!tokens.some(function (x) { return x.n; })) return;
    function fr(n, nd) {
      return Number(n).toLocaleString("en-IN", { minimumFractionDigits: nd, maximumFractionDigits: nd });
    }
    var t0 = null;
    function step(t) {
      if (t0 == null) t0 = t;
      var k = Math.min(1, (t - t0) / 600);
      var e = 1 - Math.pow(1 - k, 3);
      node.nodeValue = tokens.map(function (x) {
        if (!x.n) return x.t;
        var v = x.target * e, s = fr(v, x.nd);
        if (x.sign === "+") return (v > 0 ? "+" : "") + s;
        if ((x.sign === "-" || x.sign === "−") && (v < 0 || (v === 0 && k > 0))) {
          return (x.sign === "−" ? "−" : "-") + s.replace(/^-/, "");
        }
        if (x.target < 0 && v < 0) return "−" + s.replace(/^-/, "");
        return s;
      }).join("");
      if (k < 1) requestAnimationFrame(step);
      else node.nodeValue = orig;
    }
    requestAnimationFrame(step);
  }
  /* Hero / KPI numbers count up once per screen visit. Only the big
   * hero/KPI figures; inline numbers and table cells never animate. */
  function animateHeroNumbers(root) {
    if (reducedMotion() || !root) return;
    var els = root.querySelectorAll(
      ".c-hero .c-num, .hero-num, .pb-months, .opt-hero .hero-delta, " +
      ".kpi, .ribbon-sum .num, .hero-kv .num");
    Array.prototype.forEach.call(els, function (el) {
      var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      var nodes = [], n;
      while ((n = walker.nextNode())) nodes.push(n);
      nodes.forEach(countUpNode);
    });
  }

  /* ================= 1. PLANT ================= */
  var plantSeq = 0;
  async function loadPlant() {
    /* A newer load (e.g. after a fault) supersedes one still awaiting. */
    var seq = ++plantSeq;
    var kpis = document.getElementById("plant-kpis");
    var tiles = document.getElementById("plant-tiles");
    var machines = await api("/machines");
    var summary = await api("/dashboard/summary", { hours: 24 });
    if (seq !== plantSeq) return;
    if ((machines && machines.error) || (summary && summary.error)) {
      kpis.innerHTML = '<div class="kpi-card">' + naHtml() + "</div>";
      tiles.innerHTML = '<div class="tile">' + naHtml() + "<p class='note'>" +
        esc((machines && machines.error) || (summary && summary.error) || "") + "</p></div>";
      setChips("chips-plant", ["data unavailable", "updated " + fmtT(nowIso())]);
      PLANT_KW = { total: null, count: 0 };
      return;
    }
    var rows = summary.machines || [];
    /* Plant hero source: sum of latest_power_kw over rows with a reading.
     * Never scraped from tile/floor-label text. */
    PLANT_KW = (function (rs) {
      var t = 0, n = 0;
      rs.forEach(function (m) {
        if (m.latest_power_kw != null && isFinite(m.latest_power_kw)) { t += m.latest_power_kw; n++; }
      });
      return { total: n ? t : null, count: n };
    })(rows);
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
    if (seq !== plantSeq) return;
    var anoms = ((extra[0] && extra[0].anomalies) || []).filter(function (e) { return e.status === "OPEN"; });
    var pend = ((extra[1] && extra[1].recommendations) || []).filter(function (r) { return r.status === "PENDING_REVIEW"; });
    var ver = ((extra[2] && extra[2].verification) || []).filter(function (v) { return v.outcome === "VERIFIED"; })[0];
    var hRows = (extra[3] && (extra[3].machine_health || extra[3].health || extra[3].results)) || (extra[3] instanceof Array ? extra[3] : []);
    var health = {};
    hRows.forEach(function (h) { health[h.machine_id] = h; });
    renderAttention(anoms, pend, ver);
    PLANT_ARGS = [rows, health, anoms, extra[4] || {}];
    renderPlantView();
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
    loadAir();
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
  /* ================= 6. OPTIMISE: drag-and-drop heat planner =================
   * Two lanes over the tariff bands: today's heats (fixed) and your plan,
   * which starts as the optimiser's answer. Drag a heat in 15-minute steps;
   * the day's cost is re-estimated with the furnace model (power per state
   * x tariff of each slot). Auto-plan sends your heat count and peak cap to
   * the real optimiser (POST /optimization/run) and reloads its answer. */
  var PLAN = null;
  function heatSlots(h) { return (h.heating_slots || 0) + (h.reheat_slots || 0) + (h.melting_slots || 0) + (h.holding_slots || 0); }
  /* ONE tariff matcher, mirroring services/optimization/evaluate.py rate_at:
   * end_h 0 (or missing) means 24; end_h <= start_h wraps past midnight. */
  function periodAt(periods, hh) {
    for (var i = 0; i < (periods || []).length; i++) {
      var p = periods[i], s = p.start_h, e = (p.end_h == null || p.end_h === 0) ? 24 : p.end_h;
      if (s == null) continue;
      if (s <= e) { if (hh >= s && hh < e) return p; }
      else if (hh >= s || hh < e) return p;
    }
    return null;
  }
  function planCost(heats, tp, rated, slotMin) {
    var kwh = 0, inr = 0, peakE = 0, F = FURNACE_MODEL.frac;
    var dear = null;
    (tp || []).forEach(function (p) { if (dear == null || p.rate > dear) dear = p.rate; });
    heats.forEach(function (h) {
      var seq = [];
      for (var i = 0; i < (h.heating_slots || 0) + (h.reheat_slots || 0); i++) seq.push(F.heating);
      for (i = 0; i < (h.melting_slots || 0); i++) seq.push(F.melting);
      for (i = 0; i < (h.holding_slots || 0); i++) seq.push(F.holding);
      seq.forEach(function (fr, k) {
        var hh = (((h.start_slot + k) * slotMin) / 60) % 24, e = rated * fr * slotMin / 60;
        var per = periodAt(tp, hh), rate = per ? per.rate : 0;
        kwh += e; inr += e * rate; if (per && dear != null && per.rate === dear) peakE += e;
      });
    });
    return { kwh: kwh, inr: inr, eveningPct: kwh ? peakE / kwh * 100 : 0 };
  }
  function renderPlanner(run, tp, rated, mid) {
    var box = document.getElementById("opt-chart");
    var cur = run.current_schedule || run.current || {}, rec = run.recommended_schedule || run.recommended || {};
    var slotMin = rec.slot_min || 15, nSlots = rec.n_slots || 96;
    if (!rec.heats || !rec.heats.length) { box.innerHTML = naHtml("no recommended schedule in this run"); return; }
    PLAN = rec.heats.map(function (h) { return Object.assign({}, h); });
    var today = planCost(cur.heats || [], tp, rated, slotMin);
    var maxRate = Math.max.apply(null, tp.map(function (t) { return t.rate; }).concat([1]));
    var pct = function (slot) { return (slot / nSlots * 100) + "%"; };
    function blocks(heats, lane) {
      return heats.map(function (h, i) {
        var hs = (h.heating_slots || 0) + (h.reheat_slots || 0), ml = h.melting_slots || 0, hd = h.holding_slots || 0, L = heatSlots(h);
        return '<div class="pl-block' + (lane === "plan" ? " drag" : "") + '" data-i="' + i + '" style="left:' + pct(h.start_slot) + ";width:" + pct(L) + '"' +
          (lane === "plan" ? ' tabindex="0" role="slider" aria-label="Heat ' + (i + 1) + ' start" aria-valuenow="' + h.start_slot + '"' : "") + ">" +
          '<i class="s-heating" style="flex:' + hs + '"></i><i class="s-melting" style="flex:' + ml + '"></i><i class="s-holding" style="flex:' + hd + '"></i></div>';
      }).join("");
    }
    box.innerHTML =
      '<div class="pl-top"><div class="pl-live" id="pl-live"></div>' +
      '<div class="pl-ctl"><label>Heats <input type="number" id="pl-n" min="1" max="14" value="' + PLAN.length + '"></label>' +
      '<label>Peak cap <input type="range" id="pl-cap" min="0" max="' + Math.round(rated * 1.3) + '" step="5" value="0"><output id="pl-capv">none</output></label>' +
      '<button type="button" class="btn sm" id="pl-auto">Auto-plan with the optimiser</button>' +
      '<button type="button" class="btn sm ghost" id="pl-reset">Reset</button></div></div>' +
      '<div class="pl-board"><div class="pl-bands">' + tp.map(function (t) {
        return '<span style="left:' + ((t.start_h / 24) * 100) + "%;width:" + ((((t.end_h || 24) - t.start_h) / 24) * 100) + "%;opacity:" + (0.25 + 0.75 * t.rate / maxRate).toFixed(2) + '"><b>₹' + fmt(t.rate, 1) + "</b></span>";
      }).join("") + "</div>" +
      '<div class="pl-lane"><span class="pl-name">Today</span><div class="pl-track">' + blocks(cur.heats || [], "today") + "</div></div>" +
      '<div class="pl-lane"><span class="pl-name">Your plan</span><div class="pl-track" id="pl-track">' + blocks(PLAN, "plan") + "</div></div>" +
      '<div class="pl-axis">' + [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24].map(function (h) {
        return '<span style="left:' + (h / 24 * 100) + '%">' + String(h).padStart(2, "0") + ":00</span>"; }).join("") + "</div></div>" +
      '<p class="note" id="pl-msg">Drag a heat in your plan (or focus it and use ← →). Figures here are the furnace model’s estimate; the optimiser’s own numbers are above. ' + badge("PROJECTED", "projected") + "</p>";
    var track = document.getElementById("pl-track");
    function live() {
      var p = planCost(PLAN, tp, rated, slotMin), d = p.inr - today.inr;
      document.getElementById("pl-live").innerHTML =
        '<span><b class="num">₹' + esc(fmt(p.inr, 0)) + "</b> your plan</span><span><b class=\"num\">₹" + esc(fmt(today.inr, 0)) + "</b> today</span>" +
        '<span class="' + (d <= 0 ? "good" : "bad") + '"><b class="num">' + esc(signed(d, 0)) + "</b> ₹ a day</span>" +
        "<span>share in the dearest tariff hours <b class=\"num\">" + esc(fmt(today.eveningPct, 0)) + " % → " + esc(fmt(p.eveningPct, 0)) + " %</b></span>";
    }
    function fits(i, s) {
      var L = heatSlots(PLAN[i]);
      if (s < 0 || s + L > nSlots) return false;
      return PLAN.every(function (o, j) { return j === i || s + L <= o.start_slot || s >= o.start_slot + heatSlots(o); });
    }
    function move(el, i, s) {
      PLAN[i].start_slot = s; el.style.left = pct(s); el.setAttribute("aria-valuenow", s); live();
    }
    track.querySelectorAll(".pl-block.drag").forEach(function (el) {
      var i = Number(el.getAttribute("data-i"));
      el.addEventListener("pointerdown", function (e) {
        el.setPointerCapture(e.pointerId); el.classList.add("held");
        var x0 = e.clientX, s0 = PLAN[i].start_slot;
        var scale = track.getBoundingClientRect().width / nSlots;
        function mv(ev) { var s = s0 + Math.round((ev.clientX - x0) / scale); if (s !== PLAN[i].start_slot && fits(i, s)) move(el, i, s); }
        function up() { el.classList.remove("held"); el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); }
        el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up);
      });
      el.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        e.preventDefault(); e.stopPropagation();
        if (fits(i, PLAN[i].start_slot + d)) move(el, i, PLAN[i].start_slot + d);
      });
    });
    var cap = document.getElementById("pl-cap"), capv = document.getElementById("pl-capv");
    cap.addEventListener("input", function () { capv.textContent = Number(cap.value) ? cap.value + " kW" : "none"; });
    document.getElementById("pl-reset").addEventListener("click", function () { renderPlanner(run, tp, rated, mid); });
    document.getElementById("pl-auto").addEventListener("click", async function (e) {
      var btn = e.target; btn.disabled = true;
      var msg = document.getElementById("pl-msg");
      msg.textContent = "Asking the optimiser…";
      var body = { machine_id: mid, start: (run.constraints || {}).horizon_start || run.horizon_start, end: (run.constraints || {}).horizon_end || run.horizon_end,
        constraints: { required_heats: Number(document.getElementById("pl-n").value), time_limit_s: 5 } };
      if (Number(cap.value)) body.constraints.peak_cap_kw = Number(cap.value);
      var r = await fetch("/optimization/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      var out = r.ok ? await r.json() : null;
      btn.disabled = false;
      if (!out) { msg.textContent = "The optimiser returned HTTP " + r.status + "."; return; }
      if (out.status !== "OPTIMAL" && out.status !== "FEASIBLE") {
        msg.innerHTML = '<b class="hot">' + esc(out.status || "no plan") + ":</b> " + txt(out.explanation || "");
        return;
      }
      loadOptimise();
    });
    live();
  }

  /* ================= 4. TWIN: a heat you can run =================
   * The same furnace model the simulator uses (apps/simulator/machine_models.py):
   * power per state as a share of rated power, melt rate 500 kg/h, reheat
   * rebound 0.15 min per cold minute. Rated power comes from /machines, the
   * tariff from the API. Change the inputs, press Run heat, and compare the
   * result with yesterday's measured heats. */
  var FURNACE_MODEL = { frac: { heating: 0.85, melting: 0.95, holding: 0.45, idle: 0.08 },
    heatMin: 20, meltKgH: 500, rebound: 0.15, yieldGood: 0.98, meltC: 1550 };
  var TW = { charge: 375, start: 8, hold: 25, gap: 40, hot: true, tap: 1550 };
  var twinCtx = null;
  function twinPlan(rated, periods) {
    var M = FURNACE_MODEL, P = rated;
    var coldMin = TW.hot ? 0 : TW.gap;
    var phases = [
      ["heating", M.heatMin + M.rebound * coldMin, M.frac.heating],
      ["melting", TW.charge / M.meltKgH * 60, M.frac.melting],
      ["holding", TW.hold, M.frac.holding],
      [TW.hot ? "holding" : "idle", TW.gap, TW.hot ? M.frac.holding : M.frac.idle]
    ];
    var t = TW.start * 60, kwh = 0, inr = 0, rows = [];
    phases.forEach(function (ph, i) {
      var e = 0, c = 0;
      for (var m = 0; m < ph[1]; m++) {
        var de = P * ph[2] / 60, hh = ((t + m) / 60) % 24;
        var per = periodAt(periods, hh), rate = per ? per.rate : null;
        e += de; c += de * (rate || 0);
      }
      t += ph[1];
      rows.push({ state: ph[0], gap: i === 3, min: ph[1], kwh: e, inr: c });
      kwh += e; inr += c;
    });
    var t_out = TW.charge / 1000;
    var superKwh = Math.max(0, TW.tap - M.meltC) * KWH_PER_T_PER_C * t_out;
    kwh += superKwh;
    return { rows: rows, kwh: kwh, inr: inr, superKwh: superKwh, sec: kwh / t_out, good: TW.charge * M.yieldGood,
      minutes: rows.reduce(function (s, r) { return s + r.min; }, 0) };
  }
  function tempColor(c) {
    /* dull red at 700 C to yellow-white at 1650 C (approximate glow colour) */
    var x = Math.max(0, Math.min(1, (c - 700) / 950));
    return new THREE.Color().setHSL(0.02 + 0.12 * x, 1, 0.25 + 0.45 * x);
  }
  function buildTwin3d(el) {
    if (!window.THREE) { el.innerHTML = naHtml("3D library missing"); return null; }
    var w = el.clientWidth, h = el.clientHeight;
    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    el.innerHTML = ""; el.appendChild(renderer.domElement);
    var scene = new THREE.Scene();
    var cam = new THREE.PerspectiveCamera(35, w / h, 0.1, 100);
    cam.position.set(4.2, 3.4, 5.2);
    var controls = new THREE.OrbitControls(cam, renderer.domElement);
    controls.target.set(0, 0.9, 0); controls.enableDamping = true; controls.minDistance = 4; controls.maxDistance = 12;
    scene.add(new THREE.HemisphereLight(0xf2f3ef, 0x3a4150, 0.9));
    var sun = new THREE.DirectionalLight(0xffffff, 0.7); sun.position.set(4, 8, 5); scene.add(sun);
    var steel = new THREE.MeshStandardMaterial({ color: 0x4b5563, metalness: 0.6, roughness: 0.45 });
    /* platform and tilt frame (dark control-room palette) */
    var base = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.3, 3.2), new THREE.MeshStandardMaterial({ color: 0x232b38, roughness: 0.9 }));
    base.position.y = 0.15; scene.add(base);
    [-1.25, 1.25].forEach(function (x) {
      var post = new THREE.Mesh(new THREE.BoxGeometry(0.18, 1.6, 0.35), steel); post.position.set(x, 1.0, 0); scene.add(post);
    });
    /* refractory crucible: open cylinder, lined */
    var shell = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1.6, 48, 1, true),
      new THREE.MeshStandardMaterial({ color: 0x6b7280, metalness: 0.3, roughness: 0.6, side: THREE.DoubleSide }));
    shell.position.y = 1.2; scene.add(shell);
    var lining = new THREE.Mesh(new THREE.CylinderGeometry(0.78, 0.7, 1.55, 48, 1, true),
      new THREE.MeshStandardMaterial({ color: 0x39404d, roughness: 1, side: THREE.BackSide }));
    lining.position.y = 1.22; scene.add(lining);
    var floor = new THREE.Mesh(new THREE.CircleGeometry(0.7, 48), new THREE.MeshStandardMaterial({ color: 0x2b3342 }));
    floor.rotation.x = -Math.PI / 2; floor.position.y = 0.45; scene.add(floor);
    var rim = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.12, 12, 64), steel); rim.rotation.x = Math.PI / 2; rim.position.y = 2.0; scene.add(rim);
    /* copper induction coil: helix around the shell */
    var pts = [];
    for (var i = 0; i <= 400; i++) { var a = i / 400 * Math.PI * 2 * 7; pts.push(new THREE.Vector3(Math.cos(a) * 1.07, 0.5 + i / 400 * 1.3, Math.sin(a) * 1.07)); }
    var coilMat = new THREE.MeshStandardMaterial({ color: 0xb87333, metalness: 0.85, roughness: 0.3, emissive: 0x000000 });
    var coil = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 800, 0.05, 8, false), coilMat); scene.add(coil);
    /* molten metal: a disc whose height is the melt level and colour its temperature */
    var meltMat = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0x000000, roughness: 0.35 });
    var melt = new THREE.Mesh(new THREE.CylinderGeometry(0.74, 0.7, 1, 48), meltMat);
    scene.add(melt);
    var glow = new THREE.PointLight(0xff7a1a, 0, 6); glow.position.set(0, 2.3, 0); scene.add(glow);
    function setState(level, tempC, power) {
      var hgt = Math.max(0.02, 1.4 * level);
      melt.scale.y = hgt; melt.position.y = 0.46 + hgt / 2;
      var col = tempC > 700 ? tempColor(tempC) : new THREE.Color(0x3b3b3b);
      meltMat.color.copy(col); meltMat.emissive.copy(col).multiplyScalar(tempC > 700 ? 0.9 : 0);
      glow.intensity = tempC > 700 ? 1.2 * level * (tempC / 1600) : 0;
      coilMat.emissive.setRGB(0.55 * power, 0.18 * power, 0.02 * power);
    }
    var raf = null;
    function loop() { controls.update(); renderer.render(scene, cam); raf = requestAnimationFrame(loop); }
    loop();
    return { setState: setState, renderer: renderer, stop: function () { cancelAnimationFrame(raf); } };
  }
  async function loadTwin() {
    var ms = await api("/machines");
    var f = (ms && !ms.error ? ms : []).filter(function (m) { return m.id === "furnace-01"; })[0] || {};
    var rated = f.rated_power_kw || null;
    var periods = await tariffPeriods();
    var hs = await heatStats();
    var box = document.getElementById("twin-3d");
    if (!twinCtx) twinCtx = buildTwin3d(box);
    if (!rated) { document.getElementById("twin-out").innerHTML = naHtml("furnace rated power not returned"); return; }
    var fields = [
      ["charge", "Charge", "kg", 300, 450, 5], ["start", "Start at", "h", 0, 23.5, 0.5],
      ["hold", "Held after melting", "min", 5, 60, 1], ["gap", "Gap before the next heat", "min", 0, 90, 5],
      ["tap", "Tap temperature", "°C", 1500, 1620, 5]
    ];
    var ctl = document.getElementById("twin-controls");
    ctl.innerHTML = fields.map(function (f2) {
      return '<label class="pb-field"><span class="pb-name">' + esc(f2[1]) + '</span><output id="twv-' + f2[0] + '"></output>' +
        '<input type="range" min="' + f2[3] + '" max="' + f2[4] + '" step="' + f2[5] + '" value="' + TW[f2[0]] + '" data-k="' + f2[0] + '"></label>';
    }).join("") +
      '<label class="tw-toggle"><input type="checkbox" id="tw-hot"' + (TW.hot ? " checked" : "") + '> Keep the furnace hot in the gap</label>' +
      '<button type="button" class="btn" id="tw-run">Run heat</button>';
    function show() {
      fields.forEach(function (f2) {
        var v = TW[f2[0]];
        document.getElementById("twv-" + f2[0]).textContent = f2[0] === "start"
          ? String(Math.floor(v)).padStart(2, "0") + ":" + (v % 1 ? "30" : "00") : fmt(v, 0) + " " + f2[2];
      });
      var r = twinPlan(rated, periods);
      /* Yesterday's heats are measured heating-to-holding, without the gap,
       * so rank this heat the same way and show the gap on its own. */
      var gapKwh = r.rows[3].kwh, secHeat = (r.kwh - gapKwh) / (TW.charge / 1000);
      var rank = hs ? hs.heats.filter(function (h) { return h.sec != null && h.sec < secHeat; }).length : null;
      document.getElementById("twin-out").innerHTML =
        '<div class="tw-kpis">' +
        '<div><span class="num tw-big">' + esc(fmt(r.sec, 0)) + '</span><span class="unit">kWh per tonne</span></div>' +
        '<div><span class="num">' + esc(fmt(r.kwh, 0)) + '</span><span class="unit">kWh this heat</span></div>' +
        '<div><span class="num">₹' + esc(fmt(r.inr + r.superKwh * (avgRate(periods) || 0), 0)) + '</span><span class="unit">at the tariff of those hours</span></div>' +
        '<div><span class="num">' + esc(fmt(r.kwh * 0.71, 0)) + '</span><span class="unit">kg CO₂ (0.71 factor)</span></div></div>' +
        '<div class="tw-bar">' + r.rows.map(function (x) {
          return '<span class="seg s-' + x.state + '" style="flex-grow:' + x.kwh.toFixed(2) + '" title="' + esc(x.state) + '"></span>';
        }).join("") + (r.superKwh ? '<span class="seg s-over" style="flex-grow:' + r.superKwh.toFixed(2) + '"></span>' : "") + "</div>" +
        '<p class="tw-legend">' + r.rows.map(function (x) {
          return esc(x.gap ? (TW.hot ? "gap kept hot" : "gap switched off") : x.state) + " " + esc(fmt(x.min, 0)) + " min · " + esc(fmt(x.kwh, 0)) + " kWh";
        }).join("  |  ") + (r.superKwh ? "  |  extra superheat " + esc(fmt(r.superKwh, 1)) + " kWh" : "") + "</p>" +
        (hs ? '<p class="tw-compare">Yesterday’s ' + hs.heats.length + " measured heats ran " + esc(fmt(hs.best, 0)) + "–" + esc(fmt(hs.worst, 0)) +
          " kWh/t. This heat on its own is <b>" + esc(fmt(secHeat, 0)) + " kWh/t</b>, rank <b>" + (rank + 1) + " of " + (hs.heats.length + 1) + "</b>" + (rank === 0 ? ", better than all of them" : "") + ". The gap adds " + esc(fmt(gapKwh, 0)) + " kWh" + (TW.hot ? " because the furnace is kept hot." : " while switched off.") + "</p>" : "") +
        '<p class="note">Model: the simulator’s furnace (rated ' + rated + " kW, melt rate 500 kg/h, power per state), " +
        "superheat 0.33 kWh/t per °C above 1550 °C. " + badge("MODEL") + " " + badge("illustrative tariff") + "</p>";
      if (twinCtx && !twinCtx.running) twinCtx.setState(1, TW.hot ? 1480 : 900, TW.hot ? 0.45 : 0.08);
    }
    ctl.querySelectorAll("input[type=range]").forEach(function (inp) {
      inp.addEventListener("input", function () { TW[inp.getAttribute("data-k")] = Number(inp.value); show(); });
    });
    document.getElementById("tw-hot").addEventListener("change", function (e) { TW.hot = e.target.checked; show(); });
    document.getElementById("tw-run").addEventListener("click", function () {
      if (!twinCtx) return;
      /* play the heat in ~8 s: heating (charge heats), melting (level rises), holding, gap */
      var r = twinPlan(rated, periods), t0 = performance.now(), dur = 8000, total = r.minutes;
      var bounds = [], acc = 0;
      r.rows.forEach(function (x) { bounds.push([acc, acc + x.min, x]); acc += x.min; });
      var label = document.getElementById("twin-phase");
      twinCtx.running = true;
      (function step(now) {
        var m = Math.min(1, (now - t0) / dur) * total;
        var cur = bounds.filter(function (b) { return m >= b[0] && m <= b[1]; })[0] || bounds[bounds.length - 1];
        var st = cur[2].state, k = (m - cur[0]) / Math.max(cur[1] - cur[0], 1e-6);
        var level = st === "heating" ? 0.15 : st === "melting" ? 0.15 + 0.85 * k : cur[2].gap && !TW.hot ? 0.15 : 1;
        var temp = st === "heating" ? 600 + 600 * k : st === "melting" ? 1200 + (TW.tap - 1200) * k : cur[2].gap && !TW.hot ? 1480 - 700 * k : TW.tap - 50 * k;
        var pw = FURNACE_MODEL.frac[st] || 0.08;
        twinCtx.setState(level, temp, pw);
        var clock = TW.start * 60 + m;
        label.textContent = (cur[2].gap ? (TW.hot ? "gap, kept hot" : "gap, switched off") : st) + " · " +
          String(Math.floor(clock / 60) % 24).padStart(2, "0") + ":" + String(Math.floor(clock % 60)).padStart(2, "0") +
          " · " + fmt(rated * pw, 0) + " kW";
        if (m < total) requestAnimationFrame(step); else { twinCtx.running = false; label.textContent += " · done"; }
      })(t0);
    });
    show();
    setChips("chips-twin", ["MODEL", "rated " + rated + " kW", "illustrative tariff", "updated " + fmtT(nowIso())]);
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
      setChips("chips-optimise", ["updated " + fmtT(nowIso())]);
      return;
    }
    document.getElementById("opt-title").textContent = mid + " — drag the heats, or let the optimiser plan (" + (run.status || "?") + ")";
    var tp = ((run.metrics || {}).tariff_periods) || [];
    var mrow = machines.filter(function (m) { return m.id === mid; })[0] || {};
    if (mrow.rated_power_kw) renderPlanner(run, tp, mrow.rated_power_kw, mid);
    else chart.innerHTML = naHtml("rated power not returned for " + mid);
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
      /* ADEETIE: BEE ADEETIE operational guidelines, PIB 15 Jul 2025 —
       * foundry is a notified sector; interest subvention is released only
       * after post-implementation M&V shows >= 10 % energy saving. */
      (function () {
        var sp = v.saving_pct, line;
        if (sp == null || !isFinite(sp)) {
          line = "ADEETIE releases its interest subvention only after M&amp;V shows at least 10 % saving. No verified saving figure to check yet.";
        } else if (sp >= 10) {
          line = "ADEETIE releases its interest subvention only after M&amp;V shows at least 10 % saving. This change: " + esc(fmt(sp, 1)) + " % — meets the 10 % M&amp;V threshold.";
        } else {
          line = "ADEETIE releases its interest subvention only after M&amp;V shows at least 10 % saving. This change: " + esc(fmt(sp, 1)) + " % — not yet; about " + esc(fmt(10 - sp, 1)) + " % more, verified, reaches it.";
        }
        var left = hero.querySelector(".hero-left");
        if (left) left.innerHTML += '<p class="note">' + line + " " + badge("scheme rule") + "</p>";
      })();

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
    var per = periodAt(periods, h);
    return per ? per.rate : null;
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
    if (!PB) PB = { hw: 60000, sub: 1500, rate: avgRate ? Math.round(avgRate * 100) / 100 : 7.5, days: 300, kwhDay: Math.round(kwhDay), furnaces: 1, share: 30, years: 3, loan: 2500000, bank: 10, size: 0 };
    var fields = [
      ["hw", "Hardware + install per site", "₹", 10000, 300000, 5000, "example input: meter, converter, gateway, fitting. Replace with a real quote."],
      ["sub", "JouleMitra subscription", "₹ / month", 0, 10000, 250, "example input"],
      ["rate", "Average tariff", "₹ / kWh", 4, 14, 0.25, avgRate ? "default = the site tariff averaged over 24 h (illustrative)" : "example input"],
      ["kwhDay", "Furnace energy per day", "kWh", 200, 10000, 50, "default = this furnace's expected use: " + fmt(v.counterfactual_kwh, 0) + " kWh over " + v.n_post + " h"],
      ["days", "Operating days per year", "days", 150, 365, 5, "example input"],
      ["furnaces", "Furnaces per site", "", 1, 6, 1, "example input"],
      ["share", "Pay-from-savings: share to JouleMitra", "%", 0, 60, 5, "example input: the SME pays nothing upfront, only a share of verified savings"],
      ["years", "Pay-from-savings: contract length", "years", 1, 5, 1, "example input"],
      ["loan", "ADEETIE loan amount", "₹", 1000000, 15000000, 100000, "example input: a furnace retrofit loan; the JouleMitra kit alone is below the ₹10 lakh minimum"],
      ["bank", "Bank lending rate", "%", 8, 14, 0.25, "example input"],
      ["size", "Enterprise size for ADEETIE", "", 0, 1, 1, "example input: micro/small gets 5 % subvention, medium gets 3 %"]
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
        if (f[0] === "size") {
          document.getElementById("pbv-size").textContent = PB.size ? "medium (3 %)" : "micro/small (5 %)";
        }
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
        (function () {
          /* Pay-from-savings: only verified savings are shared, so the SME
           * never pays for a saving that did not happen. */
          var toJm = inrYr * PB.share / 100, keep = inrYr - toJm;
          var rec = toJm > 0 ? PB.hw / (toJm / 12) : null;
          return '<p class="pb-line pb-esco"><b>Pay from savings, no upfront cost:</b> the SME keeps <b class="num">₹ ' + fmt(keep, 0) +
            "</b> a year from day one; JouleMitra receives " + PB.share + " % of verified savings, recovers the kit in <b class=\"num\">" +
            (rec != null ? fmt(rec, 1) + " months" : "—") + "</b> and <b class=\"num\">₹ " + fmt(toJm * PB.years, 0) + "</b> over " + PB.years + " years.</p>";
        })() +
        (function () {
          /* ADEETIE finance: BEE ADEETIE operational guidelines, PIB 15 Jul
           * 2025 — 5 % subvention for micro/small, 3 % for medium, on up to
           * 75 % of loans Rs 10 lakh to Rs 15 crore, net borrowing rate floor 2 %. */
          var sub = PB.size ? 3 : 5;
          var rateA = Math.min(sub, PB.bank - 2);
          if (!(rateA > 0)) rateA = 0;
          var savedA = PB.loan * 0.75 * rateA / 100;
          var line = "ADEETIE: <b>₹ " + esc(fmt(savedA, 0)) + "</b> less interest in year one (" + sub +
            " % on 75 % of the loan, simple, first year). Paid only if M&amp;V shows \u2265 10 % — verified so far: " +
            esc(fmt(v.saving_pct, 1)) + " %" + (v.saving_pct < 10 ? " — not yet eligible." : ".");
          return '<p class="pb-line"><b>Finance the retrofit with ADEETIE.</b><br>' + line + " " + badge("PROJECTED", "projected") + "</p>";
        })() +
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
    if (e.key === "Escape") { closeTrail(); closeFaults(); }
    var el = document.activeElement;
    if (e.key === "Enter" && el && el.getAttribute && el.getAttribute("data-trail")) openTrail(el.getAttribute("data-trail"));
  });

  /* ================= shared: last 24 h of rows ================= */
  async function day24(mid) {
    var tel = await api("/telemetry", { machine_id: mid, limit: 400 });
    if (!tel || tel.error || tel.length < 2) return [];
    var rows = tel.slice().sort(function (a, b) { return new Date(a.ts) - new Date(b.ts); });
    var t0 = new Date(rows[rows.length - 1].ts).getTime() - 24 * 3600 * 1000;
    rows = rows.filter(function (r) { return new Date(r.ts).getTime() >= t0; });
    /* energy of each slice = meter counter difference to the previous reading */
    for (var i = 0; i < rows.length; i++) {
      var d = i ? rows[i].energy_kwh - rows[i - 1].energy_kwh : null;
      rows[i].dkwh = d != null && d >= 0 ? d : null;
      rows[i].dh = i ? (new Date(rows[i].ts) - new Date(rows[i - 1].ts)) / 3600000 : null;
    }
    return rows.slice(1);
  }
  async function tariffPeriods() {
    var run = await api("/optimization/schedule", { machine_id: "furnace-01" });
    return (run && run.metrics && run.metrics.tariff_periods) || [];
  }
  function avgRate(periods) {
    return periods.length ? periods.reduce(function (a, p) { return a + p.rate * ((p.end_h || 24) - p.start_h); }, 0) / 24 : null;
  }

  /* ================= 3. HEATS =================
   * A heat = one heating -> melting -> holding run on the furnace's
   * state sequence. Its energy is the meter counter over those slices; its
   * output is the hourly production record shared out by the heat's
   * melting minutes in that hour (DERIVED). */
  /* Superheat estimate: liquid iron ~0.82 kJ/kg.K = 0.228 kWh/t per degC,
   * at ~70 % furnace efficiency ~0.33 kWh/t per degC of overshoot. It agrees
   * with BEE's ~20 kWh/t for ~60 degC of uncontrolled overshoot. */
  var KWH_PER_T_PER_C = 0.33;
  var HEAT_TARGET = 1550;
  var PUB_BANDS = { best: [550, 625], typical: [625, 900] };
  async function heatStats() {
    var tel = await day24("furnace-01");
    var prod = await api("/production", { machine_id: "furnace-01", limit: 48 });
    var periods = await tariffPeriods();
    if (!tel.length) return null;
    var heats = [], cur = null;
    tel.forEach(function (r) {
      var st = r.machine_state;
      if (st === "heating" && (!cur || cur.phase !== "heating")) {
        cur = { start: r.ts, end: r.ts, kwh: 0, inr: 0, melt: [], hold: 0, peak: -Infinity, phase: "heating", slices: 0 };
        heats.push(cur);
      }
      if (!cur) return;
      if (st === "idle") { cur.phase = "done"; return; }
      if (cur.phase === "done") return;
      if (st === "holding" && cur.phase === "heating") return;
      cur.phase = st;
      cur.end = r.ts; cur.slices++;
      if (r.dkwh != null) { cur.kwh += r.dkwh; var rt = rateAt(periods, r.ts); if (rt != null) cur.inr += r.dkwh * rt; }
      if (st === "melting") cur.melt.push(r.ts);
      if (st === "holding") cur.hold += r.dh * 60;
      if (r.temperature_c != null && st !== "heating") cur.peak = Math.max(cur.peak, r.temperature_c);
    });
    heats = heats.filter(function (h) { return h.melt.length && h.phase === "done"; });
    /* share hourly production by melting minutes */
    var recs = (prod && !prod.error && (prod.production || prod.records || prod)) || [];
    recs = recs instanceof Array ? recs : [];
    heats.forEach(function (h) { h.kg = 0; h.good = 0; });
    recs.forEach(function (p) {
      var a = new Date(p.window_start).getTime(), b = new Date(p.window_end).getTime();
      var inHour = heats.map(function (h) { return h.melt.filter(function (t) { var x = new Date(t).getTime(); return x > a && x <= b; }).length; });
      var tot = inHour.reduce(function (s, n) { return s + n; }, 0);
      if (!tot) return;
      heats.forEach(function (h, i) { h.kg += p.qty_total_kg * inHour[i] / tot; h.good += p.qty_good_kg * inHour[i] / tot; });
    });
    heats.forEach(function (h) {
      h.t = h.kg / 1000;
      h.sec = h.t > 0 ? h.kwh / h.t : null;
      h.over = h.peak > HEAT_TARGET ? h.peak - HEAT_TARGET : 0;
      h.overKwh = h.over * KWH_PER_T_PER_C * h.t;
      h.period = (periods.filter(function (p) { var x = rateAt([p], h.melt[Math.floor(h.melt.length / 2)]); return x != null; })[0] || {}).period;
    });
    var secs = heats.map(function (h) { return h.sec; }).filter(function (x) { return x != null; }).sort(function (a, b) { return a - b; });
    var med = secs.length ? secs[Math.floor(secs.length / 2)] : null;
    var best = secs.length ? secs[0] : null, worst = secs.length ? secs[secs.length - 1] : null;
    var gapKwh = heats.reduce(function (s, h) { return s + (h.sec != null ? Math.max(0, h.sec - best) * h.t : 0); }, 0);
    var overKwh = heats.reduce(function (s, h) { return s + h.overKwh; }, 0);
    var ar = avgRate(periods);
    return { heats: heats, med: med, best: best, worst: worst, gapKwh: gapKwh, overKwh: overKwh, ar: ar };
  }
  async function loadHeats() {
    var tbl = document.getElementById("heats-table");
    var S = await heatStats();
    if (!S) { tbl.innerHTML = "<tr><td>" + naHtml("no furnace telemetry") + "</td></tr>"; return; }
    var heats = S.heats, med = S.med, best = S.best, worst = S.worst, gapKwh = S.gapKwh, overKwh = S.overKwh, ar = S.ar;

    /* benchmark scale: published ranges vs this furnace's heats */
    var lo = 400, hi = 1000, pos = function (v) { return ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo) * 100).toFixed(2) + "%"; };
    document.getElementById("heats-bench").innerHTML =
      '<h2>Where these heats sit against published ranges</h2><div class="bench-scale">' +
      '<span class="band best" style="left:' + pos(PUB_BANDS.best[0]) + ";width:calc(" + pos(PUB_BANDS.best[1]) + " - " + pos(PUB_BANDS.best[0]) + ')">best in class</span>' +
      '<span class="band typ" style="left:' + pos(PUB_BANDS.typical[0]) + ";width:calc(" + pos(PUB_BANDS.typical[1]) + " - " + pos(PUB_BANDS.typical[0]) + ')">typical Indian foundry</span>' +
      heats.filter(function (h) { return h.sec != null; }).map(function (h) { return '<i class="dot" style="left:' + pos(h.sec) + '"></i>'; }).join("") +
      (med != null ? (function () {
        /* Clamp the label inside the strip so it never slides off the left
         * edge or over the panel title when the median is near the axis start. */
        var raw = (Math.min(Math.max(med, lo), hi) - lo) / (hi - lo) * 100;
        var cl = Math.min(96, Math.max(4, raw)).toFixed(2) + "%";
        return '<b class="med" style="left:' + cl + '">median ' + esc(fmt(med, 0)) + "</b>";
      })() : "") +
      "</div>" + '<div class="bench-axis">' + [400, 500, 600, 700, 800, 900, 1000].map(function (v) {
        return '<span style="left:' + pos(v) + '">' + v + "</span>"; }).join("") + '<span class="u">kWh per tonne</span></div>' +
      '<p class="note trace" data-trail="bench" tabindex="0">Ranges: BEE/SAMEEEKSHA foundry cluster studies and industry benchmarks. Each dot is one heat.</p>';
    TRAILS.bench = { title: "Benchmark ranges", steps: [
      ["Best in class", "550–625 kWh per tonne of molten metal (modern IGBT furnaces, good practice)"],
      ["Typical", "625–900 kWh per tonne in Indian foundry clusters"],
      ["Physics floor", "about 500–560 kWh per tonne just to melt and superheat iron"],
      ["This furnace", heats.length + " heats; median " + fmt(med, 0) + " kWh/t (heat energy ÷ heat output)"]
    ], source: "BEE/SAMEEEKSHA DPR (Batala-Jalandhar-Ludhiana cluster), CarbonMinus 2025 · heats from SIMULATED data" };

    document.getElementById("heats-sum").innerHTML =
      '<div class="kpi-card"><div class="kpi">' + esc(String(heats.length)) + '<span class="unit">heats</span></div><div class="kpi-label">in the last 24 h ' + badge("MEASURED", "accent") + "</div></div>" +
      '<div class="kpi-card"><div class="kpi">' + esc(fmt(best, 0)) + " → " + esc(fmt(worst, 0)) + '<span class="unit">kWh/t</span></div><div class="kpi-label">best to worst heat ' + badge("DERIVED") + "</div></div>" +
      '<div class="kpi-card"><div class="kpi hot-num">' + esc(fmt(gapKwh, 0)) + '<span class="unit">kWh</span></div><div class="kpi-label">if every heat ran like the best one' + (ar ? " ≈ ₹" + esc(fmt(gapKwh * ar, 0)) + " a day" : "") + "</div></div>" +
      '<div class="kpi-card"><div class="kpi">' + esc(fmt(overKwh, 1)) + '<span class="unit">kWh</span></div><div class="kpi-label">spent above a ' + HEAT_TARGET + " °C target " + badge("ESTIMATE") + "</div></div>";

    var worstH = heats.reduce(function (w, h) { return h.sec != null && (!w || h.sec > w.sec) ? h : w; }, null);
    tbl.innerHTML = "<thead><tr><th>Heat</th><th>Started</th><th>Tariff</th><th class='r'>Energy</th><th class='r'>Output</th><th class='r'>kWh/t</th><th class='r'>Held after melt</th><th class='r'>Peak °C</th><th class='r'>Cost</th></tr></thead><tbody>" +
      heats.map(function (h, i) {
        TRAILS["heat" + i] = { title: "Heat " + (i + 1), steps: [
          ["Span", fmtRange(h.start, h.end) + ", " + h.slices + " meter readings"],
          ["Energy", fmt(h.kwh, 1) + " kWh = sum of meter-counter differences over heating, melting and holding"],
          ["Output", fmt(h.kg, 0) + " kg = hourly production shared by this heat's melting minutes"],
          ["Energy per tonne", fmt(h.kwh, 1) + " ÷ " + fmt(h.t, 3) + " t = " + fmt(h.sec, 0) + " kWh/t"],
          ["Temperature", "peak " + fmt(h.peak, 0) + " °C; above " + HEAT_TARGET + " °C by " + fmt(h.over, 0) + " °C ≈ " + fmt(h.overKwh, 2) + " kWh (0.33 kWh/t per °C estimate)"],
          ["Cost", "each slice priced at its tariff period: ₹" + fmt(h.inr, 0)]
        ], source: "GET /telemetry, GET /production, tariff from GET /optimization/schedule · SIMULATED data" };
        var bad = h === worstH;
        return '<tr class="' + (bad ? "worst" : "") + '"><td><span class="trace" data-trail="heat' + i + '" tabindex="0">' + (i + 1) + "</span></td><td>" + esc(fmtT(h.start)) +
          "</td><td>" + esc((h.period || "—").replace(/_/g, " ")) + '</td><td class="r num">' + esc(fmt(h.kwh, 0)) + ' kWh</td><td class="r num">' + esc(fmt(h.kg, 0)) +
          ' kg</td><td class="r num strong">' + esc(fmt(h.sec, 0)) + '</td><td class="r num' + (h.hold > 40 ? " hot" : "") + '">' + esc(fmt(h.hold, 0)) + ' min</td><td class="r num' + (h.over > 15 ? " hot" : "") + '">' +
          esc(fmt(h.peak, 0)) + '</td><td class="r num">₹' + esc(fmt(h.inr, 0)) + "</td></tr>";
      }).join("") + "</tbody>";
    setChips("chips-heats", ["SIMULATED data", "furnace-01", "illustrative tariff", "updated " + fmtT(nowIso())]);
  }

  /* ================= 4. BILL ================= */
  async function loadBill() {
    var periods = await tariffPeriods();
    loadRibbon("furnace-01", periods);
    var mids = ["furnace-01", "compressor-01", "pump-01"];
    var days = await Promise.all(mids.map(day24));
    var ar = avgRate(periods);
    /* kVAh per slice from kWh and kvar x hours; billing on kVAh charges the difference */
    var kwh = 0, kvah = 0, byTs = {}, low = [];
    days.forEach(function (rows, i) {
      var m = { mid: mids[i], kw: 0, kvar: 0, n: 0 };
      rows.forEach(function (r) {
        if (r.dkwh == null || r.reactive_power_kvar == null) return;
        var q = r.reactive_power_kvar * r.dh;
        kwh += r.dkwh; kvah += Math.sqrt(r.dkwh * r.dkwh + q * q);
        var k = px(r.ts).slice(0, 15) + (Number(px(r.ts)[15]) < 5 ? "0" : "5");
        byTs[k] = (byTs[k] || 0) + Math.sqrt(r.power_kw * r.power_kw + r.reactive_power_kvar * r.reactive_power_kvar);
        if (r.power_factor != null && r.power_factor < 0.9) { m.kw += r.power_kw; m.kvar += r.reactive_power_kvar; m.n++; }
      });
      if (m.n) low.push(m);
    });
    var pf = kvah ? kwh / kvah : null;
    /* capacitor needed to lift the low-PF periods to 0.95: Q = P(tan phi1 - tan phi2) */
    var capHtml = low.map(function (m) {
      var p = m.kw / m.n, q = m.kvar / m.n, need = Math.max(0, q - p * Math.tan(Math.acos(0.95)));
      return "<li><b>" + esc(m.mid) + "</b>: PF " + esc(fmt(p / Math.sqrt(p * p + q * q), 2)) + " in low-PF periods; about <b class='num'>" + esc(fmt(need, 0)) + " kVAr</b> of capacitors lifts it to 0.95</li>";
    }).join("");
    /* maximum demand: highest 30-minute average of total kVA */
    var keys = Object.keys(byTs).sort(), md = null, mdAt = null;
    for (var i = 5; i < keys.length; i++) {
      var avg = keys.slice(i - 5, i + 1).reduce(function (s, k) { return s + byTs[k]; }, 0) / 6;
      if (md == null || avg > md) { md = avg; mdAt = keys[i]; }
    }
    document.getElementById("bill-pf").innerHTML =
      '<div class="kpi"><span class="num">' + esc(fmt(pf, 2)) + '</span><span class="unit">average power factor</span></div>' +
      '<p>Metered <b class="num">' + esc(fmt(kwh, 0)) + " kWh</b> is <b class='num'>" + esc(fmt(kvah, 0)) + " kVAh</b>. Where the utility bills kVAh, that gap costs about <b class='num hot'>₹" +
      esc(fmt((kvah - kwh) * (ar || 0), 0)) + "</b> a day " + badge("illustrative tariff") + "</p>" +
      (capHtml ? '<ul class="bill-list">' + capHtml + "</ul>" : "") +
      "<p>Peak demand: <b class='num'>" + esc(fmt(md, 0)) + " kVA</b> (30-minute average) ending " + esc(mdAt ? mdAt.slice(11) : "—") +
      '. <span class="note">The tariff data has no demand charge, so no rupee figure is shown for it.</span></p>';

    /* scrap: electricity that went into rejected castings */
    var prod = await api("/production", { machine_id: "furnace-01", limit: 24 });
    var recs = (prod && !prod.error && (prod.production || prod.records || prod)) || [];
    recs = recs instanceof Array ? recs : [];
    var tot = recs.reduce(function (s, p) { return s + (p.qty_total_kg || 0); }, 0);
    var rej = recs.reduce(function (s, p) { return s + (p.qty_rejected_kg || 0); }, 0);
    var good = recs.reduce(function (s, p) { return s + (p.qty_good_kg || 0); }, 0);
    var fkwh = days[0].reduce(function (s, r) { return s + (r.dkwh || 0); }, 0);
    var share = tot ? rej / tot : null;
    document.getElementById("bill-reject").innerHTML = share == null ? naHtml("no production records") :
      '<div class="kpi"><span class="num">' + esc(fmt(share * 100, 1)) + ' %</span><span class="unit">of output rejected</span></div>' +
      "<p><b class='num'>" + esc(fmt(fkwh * share, 0)) + " kWh</b> (₹" + esc(fmt(fkwh * share * (ar || 0), 0)) +
      ") of today's furnace electricity went into castings that were scrapped.</p>" +
      "<p>At the ~10 % rejection BEE reports for foundry clusters, the same furnace would lose <b class='num'>" + esc(fmt(fkwh * 0.10, 0)) +
      " kWh</b> a day. Every point of rejection cut is energy saved per good tonne.</p>" +
      '<p class="note">' + badge("MEASURED energy", "accent") + " " + badge("SIMULATED output") + "</p>";

    /* carbon per tonne of good castings (electricity, Scope 2) */
    var efs = await api("/emission-factors");
    var f = ((efs && efs.emission_factors) || []).slice(-1)[0];
    var pkwh = days.reduce(function (s, rows) { return s + rows.reduce(function (a, r) { return a + (r.dkwh || 0); }, 0); }, 0);
    var tGood = good / 1000;
    var tco2 = f ? pkwh * f.value_kg_per_kwh / 1000 : null;
    var per = tco2 != null && tGood ? tco2 / tGood : null;
    /* CBAM data sheet: EU CBAM Regulation 2023/956 Annex II; definitive period
     * from 1 Jan 2026. Iron/steel castings are CBAM goods (no SME exemption);
     * for iron and steel only DIRECT emissions are priced — electricity
     * (indirect) emissions are reported, not priced. Without measured
     * installation data the EU default value is used, usually higher. */
    document.getElementById("bill-carbon").innerHTML = per == null ? naHtml("emission factor or output missing") :
      '<div class="kpi"><span class="num">' + esc(fmt(per, 2)) + '</span><span class="unit">t CO₂ per tonne of good castings</span></div>' +
      "<p>" + esc(fmt(pkwh, 0)) + " kWh for " + esc(fmt(tGood, 2)) + " t good output, grid factor " + esc(fmt(f.value_kg_per_kwh, 2)) + " " + esc(f.unit) + " (" + esc(f.version) +
      ", provisional).</p>" +
      '<div class="cbam-sheet">' +
      "<p>Indirect (electricity), measured: <b class=\"num\">" + esc(fmt(per, 2)) + "</b> t CO₂/t — reported in the CBAM communication; not priced for castings.</p>" +
      '<p class="note">Direct = your fuel and process records. EU default = the value for your CN code. Only direct emissions are priced for castings. JouleMitra measures the electricity part only.</p>' +
      '<div class="cbam-row">' +
      '<label class="cbam-field"><span>Direct, t CO₂/t</span><input type="number" id="cbam-direct" min="0" step="0.01"></label>' +
      '<label class="cbam-field"><span>EU default, t CO₂/t</span><input type="number" id="cbam-default" min="0" step="0.01"></label>' +
      '<label class="cbam-field"><span>CBAM price, €/t</span><input type="number" id="cbam-price" min="0" step="1" placeholder="e.g. 75"></label>' +
      "</div>" +
      '<p class="note" id="cbam-result" aria-live="polite"></p>' +
      "</div>" +
      '<button type="button" class="btn" id="carbon-csv">Download carbon statement (CSV)</button>';
    (function cbamWire() {
      function cbamResult() {
        var box = document.getElementById("cbam-result");
        if (!box) return;
        var dEl = document.getElementById("cbam-direct"), gEl = document.getElementById("cbam-default"), pEl = document.getElementById("cbam-price");
        if (!dEl || !gEl || !pEl) return;
        var d = parseFloat(dEl.value), dflt = parseFloat(gEl.value), price = parseFloat(pEl.value);
        if (isFinite(d) && isFinite(dflt) && isFinite(price)) {
          var y = (dflt - d) * price;
          box.innerHTML = "Using your measured direct emissions instead of the default: <b>\u20AC" + esc(fmt(Math.abs(y), 2)) + "</b> " +
            (y >= 0 ? "less" : "more") + " per tonne shipped ((default \u2212 direct) \u00D7 price). " + badge("ASSUMPTION");
        } else {
          box.textContent = "Fill the three boxes to see what measured data is worth per tonne exported.";
        }
      }
      var ids = ["cbam-direct", "cbam-default", "cbam-price"], i, el;
      for (i = 0; i < ids.length; i++) {
        el = document.getElementById(ids[i]);
        if (el) el.addEventListener("input", cbamResult);
      }
      cbamResult();
    })();
    var csvBtn = document.getElementById("carbon-csv");
    if (csvBtn) csvBtn.addEventListener("click", function () {
      var lines = [
        ["field", "value"], ["period_end", nowIso()], ["scope", "Scope 2 electricity only"],
        ["machines", mids.join(" ")], ["electricity_kwh", pkwh.toFixed(1)], ["good_output_t", tGood.toFixed(3)],
        ["grid_factor", f.value_kg_per_kwh], ["grid_factor_unit", f.unit], ["grid_factor_version", f.version],
        ["grid_factor_source_class", f.source_class], ["tco2", tco2.toFixed(3)], ["tco2_per_t_good", per.toFixed(3)],
        ["indirect_tco2_per_t_castings", per.toFixed(3)],
        ["data_source", "SIMULATED"], ["note", "provisional factor; not for external accounting until confirmed"]
      ];
      var blob = new Blob([lines.map(function (l) { return l.join(","); }).join("\n")], { type: "text/csv" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "joulemitra-carbon-statement.csv"; a.click();
      URL.revokeObjectURL(a.href);
    });
    setChips("chips-bill", ["SIMULATED data", "illustrative tariff", "updated " + fmtT(nowIso())]);
  }

  /* compressor energy while the furnace was idle or holding (Detect) */
  async function airStats() {
    var f = await day24("furnace-01"), c = await day24("compressor-01");
    var fState = {};
    f.forEach(function (r) { fState[px(r.ts).slice(0, 16)] = r.machine_state; });
    var kwh = 0, h = 0;
    c.forEach(function (r) {
      var s = fState[px(r.ts).slice(0, 16)];
      if ((s === "idle" || s === "holding") && r.dkwh != null) { kwh += r.dkwh; h += r.dh; }
    });
    return { kwh: kwh, h: h };
  }
  async function loadAir() {
    var el = document.getElementById("detect-air");
    var a = await airStats(), kwh = a.kwh, h = a.h;
    el.innerHTML = h ? "<h3>Compressed air with the furnace stopped</h3><p>The compressor ran <b class='num'>" + esc(fmt(h, 1)) +
      " h</b> and used <b class='num hot'>" + esc(fmt(kwh, 0)) + " kWh</b> while the furnace was idle or holding. " +
      "Check for leaks and tools left on: a single ¼-inch leak can cost lakhs a year.</p>" : "";
  }

  /* ================= 7. MORNING BRIEF =================
   * Yesterday's three biggest actions, ranked by rupees, as the message a
   * supervisor would get on the phone. Every number comes from the same
   * calculations as the Detect, Heats, Bill and Optimise screens. Replying
   * "approve" records the decision through the normal recommendation API.
   * Sending (WhatsApp Business / SMS) is not connected: this is a preview.
   * Tamil and Hindi wording: machine-drafted, to be checked by a native
   * speaker before any real use. */
  var BRIEF_TXT = {
    en: {
      hello: "Good morning. Yesterday the plant used {kwh} kWh, about ₹{inr}. Top actions for today:",
      air: "Compressor ran {h} h while the furnace was stopped: {kwh} kWh (≈₹{inr}). Check for air leaks and switch it off between heats.",
      hold: "Furnace was kept hot with no pour for {h} h: {kwh} kWh (≈₹{inr}). Switch it off in long idle gaps.",
      heats: "Heat {n} used {sec} kWh/t; the best heat used {best}. Running every heat like the best saves about ₹{inr} a day.",
      sched: "Start heats at the planned times to miss the evening rate: about ₹{inr} a day (projected).",
      pf: "Power factor is {pf}. If the bill is in kVAh this costs about ₹{inr} a day. Ask your electrician about capacitors.",
      reply: "Reply 1, 2 or 3 to approve an action. Nothing changes on the machines without you.",
      approved: "Approved", approve: "Approve",
      title: "Morning brief", sub: "The three biggest money actions from yesterday, as the supervisor reads them on the phone.",
      whyH: "How the three were picked",
      whyNote: "Every candidate from the other screens, ranked by rupees. Approving records a real decision, the same as on the Act screen.",
      preview: "Preview. Sending needs a WhatsApp Business or SMS account, which this demo does not connect. Tamil and Hindi wording to be checked by a native speaker.",
      noRec: "no open recommendation to approve", details: "details", to: "plant supervisor"
    },
    ta: {
      hello: "காலை வணக்கம். நேற்று ஆலை {kwh} kWh மின்சாரம் பயன்படுத்தியது, சுமார் ₹{inr}. இன்று செய்ய வேண்டியவை:",
      air: "உலை நின்றிருந்தபோது கம்ப்ரஸர் {h} மணி நேரம் ஓடியது: {kwh} kWh (≈₹{inr}). காற்று கசிவைச் சரிபார்த்து, ஹீட்களுக்கு இடையில் அணைக்கவும்.",
      hold: "ஊற்றாமல் உலை {h} மணி நேரம் சூடாக வைக்கப்பட்டது: {kwh} kWh (≈₹{inr}). நீண்ட இடைவேளைகளில் அணைக்கவும்.",
      heats: "ஹீட் {n} டன்னுக்கு {sec} kWh எடுத்தது; சிறந்த ஹீட் {best}. எல்லா ஹீட்டும் சிறந்தது போல் ஓடினால் நாளுக்கு சுமார் ₹{inr} மிச்சம்.",
      sched: "மாலை உச்ச கட்டணத்தைத் தவிர்க்க திட்டமிட்ட நேரத்தில் ஹீட்களைத் தொடங்கவும்: நாளுக்கு சுமார் ₹{inr} (கணிப்பு).",
      pf: "பவர் ஃபேக்டர் {pf}. பில் kVAh-இல் இருந்தால் இதனால் நாளுக்கு சுமார் ₹{inr} செலவாகும். கேபாசிட்டர் பற்றி மின் பணியாளரிடம் கேளுங்கள்.",
      reply: "ஒரு செயலை ஒப்புக்கொள்ள 1, 2 அல்லது 3 என பதில் அனுப்பவும். உங்கள் அனுமதி இல்லாமல் இயந்திரங்களில் எதுவும் மாறாது.",
      approved: "ஒப்புதல் அளிக்கப்பட்டது", approve: "ஒப்புதல்",
      title: "காலை அறிக்கை", sub: "நேற்றைய மிகப்பெரிய மூன்று செலவுச் செயல்கள், மேற்பார்வையாளர் தொலைபேசியில் படிப்பது போல.",
      whyH: "இந்த மூன்றும் எப்படித் தேர்ந்தெடுக்கப்பட்டன",
      whyNote: "மற்ற திரைகளில் உள்ள ஒவ்வொரு செயலும் ரூபாய் அடிப்படையில் வரிசைப்படுத்தப்பட்டுள்ளது. ஒப்புதல் அளித்தால் அது உண்மையான முடிவாகப் பதிவாகும், செயல் திரையில் உள்ளது போலவே.",
      preview: "முன்னோட்டம். அனுப்ப WhatsApp Business அல்லது SMS கணக்கு தேவை; இந்த டெமோவில் அது இணைக்கப்படவில்லை. தமிழ், இந்தி வாசகங்களைத் தாய்மொழியாளர் சரிபார்க்க வேண்டும்.",
      noRec: "ஒப்புதல் அளிக்கத் திறந்த பரிந்துரை இல்லை", details: "விவரம்", to: "ஆலை மேற்பார்வையாளர்"
    },
    hi: {
      hello: "सुप्रभात। कल प्लांट में {kwh} kWh बिजली लगी, लगभग ₹{inr}। आज के ज़रूरी काम:",
      air: "फ़र्नेस बंद रहने पर कंप्रेसर {h} घंटे चला: {kwh} kWh (≈₹{inr})। हवा का रिसाव जाँचें और हीट के बीच इसे बंद करें।",
      hold: "बिना ढलाई के फ़र्नेस {h} घंटे गर्म रखी गई: {kwh} kWh (≈₹{inr})। लंबे खाली समय में इसे बंद करें।",
      heats: "हीट {n} में प्रति टन {sec} kWh लगे, सबसे अच्छी हीट में {best}। हर हीट सबसे अच्छी जैसी चले तो रोज़ लगभग ₹{inr} बचेंगे।",
      sched: "शाम की महँगी दर से बचने के लिए तय समय पर हीट शुरू करें: रोज़ लगभग ₹{inr} (अनुमान)।",
      pf: "पावर फ़ैक्टर {pf} है। अगर बिल kVAh में है तो इससे रोज़ लगभग ₹{inr} ज़्यादा लगते हैं। कैपेसिटर के बारे में इलेक्ट्रीशियन से पूछें।",
      reply: "किसी काम को मंज़ूरी देने के लिए 1, 2 या 3 भेजें। आपकी मंज़ूरी के बिना मशीनों पर कुछ नहीं बदलता।",
      approved: "मंज़ूर", approve: "मंज़ूर करें",
      title: "सुबह की रिपोर्ट", sub: "कल के सबसे बड़े तीन पैसे वाले काम, जैसे सुपरवाइज़र उन्हें फ़ोन पर पढ़ता है।",
      whyH: "ये तीन कैसे चुने गए",
      whyNote: "बाकी स्क्रीनों के हर काम को रुपयों के हिसाब से क्रम में रखा गया है। मंज़ूरी देने पर असली फ़ैसला दर्ज होता है, बिल्कुल Act स्क्रीन की तरह।",
      preview: "पूर्वावलोकन। भेजने के लिए WhatsApp Business या SMS खाता चाहिए, जो इस डेमो में जुड़ा नहीं है। तमिल और हिंदी शब्दों की जाँच मूल भाषी से करवाएँ।",
      noRec: "मंज़ूरी के लिए कोई खुली सिफ़ारिश नहीं", details: "विवरण", to: "प्लांट सुपरवाइज़र"
    }
  };
  var briefLang = "en", briefCache = null;
  function fill(tpl, v) { return tpl.replace(/\{(\w+)\}/g, function (_, k) { return v[k] != null ? v[k] : ""; }); }
  async function briefActions() {
    var periods = await tariffPeriods(), ar = avgRate(periods) || 0;
    var res = await Promise.all([airStats(), heatStats(), day24("furnace-01"), day24("compressor-01"), day24("pump-01"),
      api("/optimization/schedule", { machine_id: "furnace-01" }), api("/recommendations")]);
    var air = res[0], hs = res[1], days = [res[2], res[3], res[4]], run = res[5];
    var pend = ((res[6] && res[6].recommendations) || []).filter(function (r) { return r.status === "PENDING_REVIEW"; });
    var pendFor = function (mid, rule) { return pend.filter(function (r) { return r.machine_id === mid && (!rule || r.rule_id === rule); })[0] || null; };
    var acts = [];
    if (air.h) acts.push({ k: "air", inr: air.kwh * ar, v: { h: fmt(air.h, 1), kwh: fmt(air.kwh, 0), inr: fmt(air.kwh * ar, 0) }, rec: pendFor("compressor-01"), screen: "detect" });
    var hold = days[0].filter(function (r) { return r.machine_state === "holding" && r.dkwh != null; });
    var hKwh = hold.reduce(function (s, r) { return s + r.dkwh; }, 0), hInr = hold.reduce(function (s, r) { return s + r.dkwh * (rateAt(periods, r.ts) || ar); }, 0);
    if (hKwh) acts.push({ k: "hold", inr: hInr, v: { h: fmt(hold.reduce(function (s, r) { return s + r.dh; }, 0), 1), kwh: fmt(hKwh, 0), inr: fmt(hInr, 0) }, rec: pendFor("furnace-01", "R-IDLE"), screen: "bill" });
    if (hs && hs.gapKwh) {
      var worst = hs.heats.reduce(function (w, h) { return h.sec != null && (!w || h.sec > w.sec) ? h : w; }, null);
      acts.push({ k: "heats", inr: hs.gapKwh * ar, v: { n: hs.heats.indexOf(worst) + 1, sec: fmt(worst.sec, 0), best: fmt(hs.best, 0), inr: fmt(hs.gapKwh * ar, 0) }, rec: null, screen: "heats" });
    }
    var m = (run && run.metrics) || {}, cur = valOf((m.current || {}).cost_inr), recC = valOf((m.recommended || {}).cost_inr);
    if (cur != null && recC != null && cur > recC) acts.push({ k: "sched", inr: cur - recC, v: { inr: fmt(cur - recC, 0) }, rec: pendFor("furnace-01", "R-RESCHEDULE"), screen: "optimise", projected: true });
    var kwh = 0, kvah = 0;
    days.forEach(function (rows) { rows.forEach(function (r) {
      if (r.dkwh == null || r.reactive_power_kvar == null) return;
      var q = r.reactive_power_kvar * r.dh; kwh += r.dkwh; kvah += Math.sqrt(r.dkwh * r.dkwh + q * q);
    }); });
    if (kvah > kwh) acts.push({ k: "pf", inr: (kvah - kwh) * ar, v: { pf: fmt(kwh / kvah, 2), inr: fmt((kvah - kwh) * ar, 0) }, rec: null, screen: "bill" });
    acts.sort(function (a, b) { return b.inr - a.inr; });
    return { acts: acts, top: acts.slice(0, 3), kwh: kwh, inr: days.reduce(function (s, rows) { return s + rows.reduce(function (a, r) { return a + (r.dkwh || 0) * (rateAt(periods, r.ts) || ar); }, 0); }, 0) };
  }
  function renderBrief() {
    var b = briefCache, T = BRIEF_TXT[briefLang];
    [["brief-h1", "title"], ["brief-sub", "sub"], ["brief-why-h", "whyH"], ["brief-why-note", "whyNote"], ["brief-preview", "preview"]].forEach(function (p) {
      var el = document.getElementById(p[0]);
      el.textContent = T[p[1]];
      el.setAttribute("lang", briefLang);
    });
    document.querySelectorAll(".lang button").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-lang") === briefLang)); });
    document.getElementById("brief-msg").innerHTML = '<p class="msg-meta">JouleMitra → ' + esc(T.to) + ' · 07:00</p>' +
      '<p lang="' + briefLang + '">' + esc(fill(T.hello, { kwh: fmt(b.kwh, 0), inr: fmt(b.inr, 0) })) + "</p><ol lang=\"" + briefLang + "\">" +
      b.top.map(function (a) { return "<li>" + esc(fill(T[a.k], a.v)) + "</li>"; }).join("") + "</ol>" +
      '<p class="msg-reply" lang="' + briefLang + '">' + esc(T.reply) + "</p>";
    document.getElementById("brief-why").innerHTML = '<ol class="rank">' + b.acts.map(function (a, i) {
      var inTop = i < 3;
      return '<li class="' + (inTop ? "top" : "") + '"><span class="rank-inr num">₹' + esc(fmt(a.inr, 0)) + "</span>" +
        '<span class="rank-what" lang="' + briefLang + '">' + esc(fill(T[a.k], a.v).split(/[.।]\s|:\s/)[0]) + ' <a href="#' + a.screen + '">' + esc(T.details) + "</a>" +
        (a.projected ? " " + badge("PROJECTED", "projected") : "") + "</span>" +
        (inTop && a.rec ? '<button type="button" class="btn sm" data-approve="' + esc(a.rec.id) + '">' + esc(T.approve) + " " + (i + 1) + "</button>"
          : inTop ? '<span class="note">' + esc(T.noRec) + "</span>" : "") + "</li>";
    }).join("") + "</ol>";
    document.querySelectorAll("[data-approve]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        var r = await fetch("/recommendations/" + encodeURIComponent(btn.getAttribute("data-approve")) + "/acknowledge", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: "APPROVED", note: "approved from the morning brief" }) });
        btn.outerHTML = r.ok ? '<span class="badge verified">' + esc(T.approved) + " · " + esc(fmtT(nowIso())) + "</span>"
          : '<span class="badge warn">not recorded (HTTP ' + r.status + ")</span>";
      });
    });
  }
  async function loadBrief() {
    var ql = new URLSearchParams(window.location.search).get("lang");
    if (ql && BRIEF_TXT[ql]) briefLang = ql;
    briefCache = await briefActions();
    document.querySelectorAll(".lang button").forEach(function (x) {
      x.onclick = function () { briefLang = x.getAttribute("data-lang"); renderBrief(); };
    });
    renderBrief();
    setChips("chips-brief", ["preview, not sent", "SIMULATED data", "illustrative tariff", "updated " + fmtT(nowIso())]);
  }

  /* ================= 1. PLANT: 3D floor =================
   * The same three machines, meter panel, gateway and server as the wiring
   * view, as an orbitable scene. Cable glow and the speed of the pulses on
   * each cable follow that machine's live kW; a machine with an open alert
   * turns orange. Click a machine for its numbers. */
  var PLANT_VIEW = new URLSearchParams(window.location.search).get("view") === "3d" ? "3d" : "wiring";
  var PLANT_ARGS = null, floorCtx = null;
  function renderPlantView() {
    if (!PLANT_ARGS) return;
    document.querySelectorAll(".view-toggle button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-view") === PLANT_VIEW)); });
    if (floorCtx) { floorCtx.stop(); floorCtx = null; }
    if (PLANT_VIEW === "3d") renderPlant3d.apply(null, PLANT_ARGS);
    else renderPlantDiagram.apply(null, PLANT_ARGS);
  }
  document.querySelectorAll(".view-toggle button").forEach(function (b) {
    b.addEventListener("click", function () { PLANT_VIEW = b.getAttribute("data-view"); renderPlantView(); });
  });
  function renderPlant3d(rows, health, anoms, comp) {
    var box = document.getElementById("plant-tiles");
    if (!window.THREE) { box.innerHTML = naHtml("3D library missing"); return; }
    box.innerHTML = '<div class="floor" id="floor"></div><div class="floor-labels" id="floor-labels"></div><div class="floor-card" id="floor-card" hidden></div>';
    var el = document.getElementById("floor"), w = el.clientWidth, h = el.clientHeight;
    /* Never fail as a silent white box: say why the 3D view is missing. */
    function fail(why) {
      box.innerHTML = '<p class="floor-fail">The 3D view could not start: ' + esc(why) +
        '. Reload the page (Ctrl+F5); the Wiring view shows the same plant.</p>';
    }
    if (!w || !h) { fail("its area has no size yet"); return; }
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch (err) { fail("WebGL is unavailable in this browser (" + (err && err.message || err) + ")"); return; }
    var stopped = false;  // our own teardown also fires webglcontextlost; ignore that one
    renderer.domElement.addEventListener("webglcontextlost", function (ev) {
      ev.preventDefault();
      if (stopped) return;
      if (floorCtx) { floorCtx.stop(); floorCtx = null; }
      fail("the browser took back its graphics context");
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.setSize(w, h); el.appendChild(renderer.domElement);
    var scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(32, w / h, 0.1, 200);
    cam.position.set(9, 10, 14);
    var controls = new THREE.OrbitControls(cam, renderer.domElement);
    controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.46;
    scene.add(new THREE.HemisphereLight(0xf5f5f0, 0x4a5160, 0.95));
    var sun = new THREE.DirectionalLight(0xffffff, 0.6); sun.position.set(6, 12, 8); scene.add(sun);
    /* dark control-room floor and grid so the lit machines read */
    var floorMesh = new THREE.Mesh(new THREE.PlaneGeometry(22, 12), new THREE.MeshStandardMaterial({ color: 0x161d29, roughness: 1 }));
    floorMesh.rotation.x = -Math.PI / 2; floorMesh.position.y = 0; scene.add(floorMesh);
    var grid = new THREE.GridHelper(22, 22, 0x334052, 0x232c3d); grid.scale.z = 12 / 22; grid.position.y = 0.01; scene.add(grid);
    var mat = function (c, o) { return new THREE.MeshStandardMaterial(Object.assign({ color: c, roughness: 0.55, metalness: 0.3 }, o || {})); };
    var alertM = {}; anoms.forEach(function (a) { alertM[a.machine_id] = true; });
    var byId = {}; rows.forEach(function (m) { byId[m.machine_id] = m; });
    var picks = [], labels = [], cables = [];
    function group(x, z) { var g = new THREE.Group(); g.position.set(x, 0, z); scene.add(g); return g; }
    /* furnace */
    var fz = group(-6, 1);
    var fBody = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 1.8, 40), mat(0x5b6470)); fBody.position.y = 0.9; fz.add(fBody);
    var fMelt = new THREE.Mesh(new THREE.CircleGeometry(0.85, 40), mat(0xff8a2a, { emissive: 0xff6a10, emissiveIntensity: 0.9, metalness: 0 }));
    fMelt.rotation.x = -Math.PI / 2; fMelt.position.y = 1.81; fz.add(fMelt);
    for (var i = 0; i < 6; i++) { var ring = new THREE.Mesh(new THREE.TorusGeometry(1.16, 0.06, 8, 40), mat(0xb87333, { metalness: 0.85 })); ring.rotation.x = Math.PI / 2; ring.position.y = 0.3 + i * 0.26; fz.add(ring); }
    /* compressor: receiver tank + skid */
    var cz = group(0, 2.2);
    var skid = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.9, 1.3), mat(0x2f6f8f)); skid.position.set(0, 0.45, 0); cz.add(skid);
    var tank = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 2, 24), mat(0x9aa3ad)); tank.position.set(1.7, 1, 0); cz.add(tank);
    /* pump + motor */
    var pz = group(5.5, 1.5);
    var motor = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 1.1, 24), mat(0x3b4b8a)); motor.rotation.z = Math.PI / 2; motor.position.set(-0.4, 0.5, 0); pz.add(motor);
    var volute = new THREE.Mesh(new THREE.SphereGeometry(0.45, 20, 16), mat(0x7a828c)); volute.position.set(0.55, 0.5, 0); pz.add(volute);
    /* meter panel, gateway, server */
    var panel = group(-1, -3.8), pnl = new THREE.Mesh(new THREE.BoxGeometry(2.6, 2, 0.5), mat(0x2a3340)); pnl.position.y = 1; panel.add(pnl);
    var gw = group(3.2, -3.8), gwm = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.5, 0.5), mat(0x2f5bd3)); gwm.position.y = 1.2; gw.add(gwm);
    var srv = group(6.2, -3.8), srvm = new THREE.Mesh(new THREE.BoxGeometry(1, 2.2, 0.9), mat(0x1b2430)); srvm.position.y = 1.1; srv.add(srvm);
    var parts = [["furnace-01", fz, fBody], ["compressor-01", cz, skid], ["pump-01", pz, motor]];
    /* Centre the camera on the machines' bounding box, not the scene origin. */
    var mbox = new THREE.Box3();
    [fz, cz, pz].forEach(function (g) { mbox.expandByObject(g); });
    var mctr = mbox.getCenter(new THREE.Vector3());
    controls.target.set(mctr.x, 0.5, mctr.z);
    parts.forEach(function (p) {
      var m = byId[p[0]] || {};
      if (alertM[p[0]]) p[2].material = mat(0xe8541c);
      p[2].userData.mid = p[0]; picks.push(p[2]);
      labels.push({ obj: p[1], y: 2.4, html: "<b>" + esc(m.machine_name || p[0]) + "</b><span>" + (m.latest_power_kw != null ? esc(fmt(m.latest_power_kw, 1)) + " kW" : "no reading") + "</span>", hot: alertM[p[0]] });
      /* cable from the meter panel to the machine, lifted off the floor */
      var a = new THREE.Vector3(-1, 0.15, -3.5), b = new THREE.Vector3(p[1].position.x, 0.15, p[1].position.z - 0.9);
      var mid = a.clone().add(b).multiplyScalar(0.5); mid.y = 0.15;
      var curve = new THREE.CatmullRomCurve3([a, new THREE.Vector3(a.x, 0.15, mid.z), new THREE.Vector3(b.x, 0.15, mid.z), b]);
      var kw = m.latest_power_kw || 0, maxKw = Math.max.apply(null, rows.map(function (r) { return r.latest_power_kw || 0; }).concat([1]));
      var cab = new THREE.Mesh(new THREE.TubeGeometry(curve, 60, 0.05 + 0.1 * kw / maxKw, 8, false),
        mat(alertM[p[0]] ? 0xe8541c : 0xb9c2d4, { emissive: alertM[p[0]] ? 0xe8541c : 0x000000, emissiveIntensity: 0.4 }));
      scene.add(cab);
      var dots = [];
      for (var k = 0; k < 4; k++) { var d = new THREE.Mesh(new THREE.SphereGeometry(0.09, 10, 8), mat(0xfff1c2, { emissive: 0xffc861, emissiveIntensity: 1 })); scene.add(d); dots.push(d); }
      cables.push({ curve: curve, dots: dots, speed: 0.02 + 0.25 * kw / maxKw });
    });
    labels.push({ obj: panel, y: 2.5, html: "<b>Meter panel</b><span>3 meters, CTs</span>" });
    labels.push({ obj: gw, y: 2, html: "<b>Edge gateway</b><span>buffers if the link drops</span>" });
    labels.push({ obj: srv, y: 2.8, html: "<b>JouleMitra server</b><span>API " + esc(comp.api || "—") + " · database " + esc(comp.database || "—") + "</span>" });
    /* Ethernet: panel -> gateway -> server */
    [[[-1, 1.6, -3.8], [3.2, 1.2, -3.8]], [[3.2, 1.2, -3.8], [6.2, 1.2, -3.8]]].forEach(function (s) {
      var c = new THREE.LineCurve3(new THREE.Vector3().fromArray(s[0]), new THREE.Vector3().fromArray(s[1]));
      scene.add(new THREE.Mesh(new THREE.TubeGeometry(c, 8, 0.04, 6, false), mat(0x2f5bd3)));
    });
    var lab = document.getElementById("floor-labels");
    lab.innerHTML = labels.map(function (l, i) { return '<div class="flabel' + (l.hot ? " hot" : "") + '" id="fl' + i + '">' + l.html + "</div>"; }).join("");
    var card = document.getElementById("floor-card"), ray = new THREE.Raycaster(), v = new THREE.Vector2();
    renderer.domElement.addEventListener("click", function (e) {
      var r = renderer.domElement.getBoundingClientRect();
      v.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(v, cam);
      var hit = ray.intersectObjects(picks)[0];
      if (!hit) { card.hidden = true; return; }
      var m = byId[hit.object.userData.mid] || {}, hh = health[hit.object.userData.mid] || {};
      card.hidden = false;
      card.innerHTML = "<b>" + esc(m.machine_name || hit.object.userData.mid) + "</b>" +
        "<dl><dt>Now</dt><dd>" + esc(fmt(m.latest_power_kw, 1)) + " kW · " + esc(m.latest_state || "—") + "</dd>" +
        "<dt>Energy today</dt><dd>" + esc(fmt(m.energy_kwh, 0)) + " kWh</dd>" +
        "<dt>Health</dt><dd>" + (hh.health_score != null ? esc(fmt(hh.health_score, 0)) + " / 100" : "—") + "</dd>" +
        "<dt>Open alerts</dt><dd>" + esc(String(m.open_alerts || 0)) + "</dd></dl>" +
        '<a href="#' + (m.open_alerts ? "detect" : "health") + '">' + (m.open_alerts ? "See the alert" : "See its health") + "</a>";
    });
    var raf, t0 = performance.now(), tmp = new THREE.Vector3();
    function loop(now) {
      /* rAF's timestamp can be earlier than t0, and JS % keeps the sign, so
       * a negative curve position crashed getPoint and killed this loop. */
      var t = Math.max(0, (now - t0) / 1000);
      cables.forEach(function (c) { c.dots.forEach(function (d, k) {
        var u = ((t * c.speed) + k / c.dots.length) % 1;
        d.position.copy(c.curve.getPoint(u < 0 ? u + 1 : u));
      }); });
      controls.update(); renderer.render(scene, cam);
      labels.forEach(function (l, i) {
        tmp.copy(l.obj.position); tmp.y = l.y; tmp.project(cam);
        var n = document.getElementById("fl" + i);
        if (n) { n.style.left = ((tmp.x + 1) / 2 * w) + "px"; n.style.top = ((1 - tmp.y) / 2 * h) + "px"; }
      });
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    /* Release the WebGL context too: dispose() alone keeps it alive, and
     * browsers cap live contexts (~16), so repeated reloads went blank. */
    floorCtx = { stop: function () {
      stopped = true;
      cancelAnimationFrame(raf); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    } };
  }

  /* ================= fault injection (demo mode) ================= */
  var FAULT_WHERE = { air_leak: "detect", furnace_holding: "heats", furnace_wear: "health", restore: "plant" };
  function openFaults() { closeTrail(); document.getElementById("faults").classList.add("open"); }
  function closeFaults() { document.getElementById("faults").classList.remove("open"); }
  document.getElementById("fault-open").addEventListener("click", openFaults);
  document.getElementById("fault-close").addEventListener("click", closeFaults);
  document.querySelectorAll("[data-fault]").forEach(function (b) {
    b.addEventListener("click", async function () {
      var fault = b.getAttribute("data-fault"), log = document.getElementById("fault-log");
      document.querySelectorAll("[data-fault]").forEach(function (x) { x.disabled = true; });
      log.innerHTML = "<p>" + esc(b.textContent) + ": rewriting the last 4 hours and running detection…</p>";
      var r = await fetch("/demo/inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fault: fault, hours: 4 }) });
      document.querySelectorAll("[data-fault]").forEach(function (x) { x.disabled = false; });
      if (r.status === 404) { log.innerHTML = "<p class='hot'>Demo mode is off. Start the backend with DEMO_MODE=true to use this.</p>"; return; }
      if (!r.ok) { log.innerHTML = "<p class='hot'>Failed: HTTP " + r.status + "</p>"; return; }
      var out = await r.json(), where = FAULT_WHERE[fault];
      log.innerHTML = "<p><b>Done.</b> " + esc(fmtRange(out.window_start, out.window_end)) + " rewritten as " + esc(out.scenario) + ".</p>" +
        (out.events.length ? "<ul>" + out.events.map(function (e) {
          return "<li><b>" + esc(e.machine_id) + "</b>: " + esc(ruleName(e.rule_id)) + (e.deviation_pct != null ? " (" + esc(signed(e.deviation_pct, 1)) + " %)" : "") + "</li>";
        }).join("") + "</ul>" : "<p>No energy alert in this window" + (fault === "furnace_wear" ? "; wear shows up in machine health." : ".") + "</p>") +
        '<p><a href="#' + where + '">See it on ' + esc(where) + "</a> · <a href=\"#plant\">plant</a> · <a href=\"#brief\">brief</a></p>";
      show();
    });
  });

  /* ================= judge tour =================
   * A guided walk through the loop: eight captioned stops. Step 2 opens the
   * fault panel so the judge picks the air-leak fault themselves. */
  var TOUR = [
    ["plant", "A small foundry: compressor, induction furnace, cooling pump. Every number here is live from the simulator."],
    ["plant", "Break something. Pick \u2018Air leak on the compressor\u2019 \u2014 it rewrites 4 hours of simulated data."],
    ["detect", "Detected: energy above what the work needed, while output stayed the same."],
    ["health", "Health and energy together: is it wear, or process waste?"],
    ["optimise", "Plan tomorrow: same output, heats moved to cheaper tariff hours."],
    ["act", "A person approves every step, from suggestion to proof."],
    ["impact", "Proven: measured against what would have happened anyway, with an error band."],
    ["payback", "What it pays back, and how a government scheme can finance it."]
  ];
  var tourIdx = -1, tourTimer = null;
  function tourBar() {
    var bar = document.getElementById("tour-bar");
    if (bar) return bar;
    bar = document.createElement("div");
    bar.id = "tour-bar";
    bar.innerHTML = '<span class="tour-step" id="tour-step"></span>' +
      '<span class="tour-caption" id="tour-caption" aria-live="polite"></span>' +
      '<span class="tour-btns"><button type="button" class="btn sm" id="tour-prev">Prev</button>' +
      '<button type="button" class="btn sm" id="tour-next">Next</button>' +
      '<button type="button" class="btn sm ghost" id="tour-close">Close</button></span>';
    document.getElementById("stage").appendChild(bar);
    document.getElementById("tour-prev").addEventListener("click", function () { tourGo(tourIdx - 1); });
    document.getElementById("tour-next").addEventListener("click", function () { tourGo(tourIdx + 1); });
    document.getElementById("tour-close").addEventListener("click", endTour);
    return bar;
  }
  function tourArm() {
    if (tourTimer) { clearTimeout(tourTimer); tourTimer = null; }
    if (tourIdx === 1) return; /* step 2 waits for Next */
    if (tourIdx >= 0 && tourIdx < TOUR.length - 1) {
      tourTimer = setTimeout(function () { tourGo(tourIdx + 1); }, 20000);
    }
  }
  function tourGo(i) {
    if (i < 0) i = 0;
    if (i >= TOUR.length) { endTour(); return; }
    tourIdx = i;
    var bar = tourBar();
    bar.style.display = "";
    document.getElementById("stage").classList.add("touring");
    document.getElementById("tour-step").textContent = "step " + (i + 1) + " / " + TOUR.length;
    document.getElementById("tour-caption").textContent = TOUR[i][1];
    if (i === 1) openFaults();
    if (window.location.hash !== "#" + TOUR[i][0]) window.location.hash = "#" + TOUR[i][0];
    else show();
    tourArm();
  }
  function startTour() { tourGo(0); }
  function endTour() {
    tourIdx = -1;
    if (tourTimer) { clearTimeout(tourTimer); tourTimer = null; }
    var bar = document.getElementById("tour-bar");
    if (bar) bar.style.display = "none";
    document.getElementById("stage").classList.remove("touring");
    closeFaults();
  }
  document.getElementById("tour-start").addEventListener("click", startTour);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && tourIdx >= 0) endTour();
  });

  /* ?selftest=1: tariff wrap self-check (console only, no UI change). */
  (function selftest() {
    if (!new URLSearchParams(window.location.search).has("selftest")) return;
    function eq(got, want, msg) { if (got !== want) throw new Error("selftest: " + msg + " (got " + got + ", want " + want + ")"); }
    var wrap = [{ start_h: 22, end_h: 6, rate: 5 }, { start_h: 6, end_h: 22, rate: 8 }];
    eq(periodAt(wrap, 2).rate, 5, "hour 2 -> 5");
    eq(periodAt(wrap, 23).rate, 5, "hour 23 -> 5");
    eq(periodAt(wrap, 10).rate, 8, "hour 10 -> 8");
    var seed = [{ start_h: 0, end_h: 6, rate: 6 }, { start_h: 6, end_h: 18, rate: 7.5 },
      { start_h: 18, end_h: 22, rate: 10.5 }, { start_h: 22, end_h: 0, rate: 6 }];
    eq(periodAt(seed, 23.5).rate, 6, "hour 23.5 -> off-peak 6");
    console.log("selftest ok");
  })();

  /* ?selftest=floor: rebuild the 3D floor 25 times in one page (past the
   * ~16 live-WebGL-context cap) and check it still renders. */
  /* ?selftest=fault: show the 3D floor, press the real "Air leak" button,
   * then report what the floor panel holds after the reload that follows. */
  (function faultSelftest() {
    if (new URLSearchParams(window.location.search).get("selftest") !== "fault") return;
    var tries = 0;
    (function wait() {
      if (!PLANT_ARGS) { if (++tries < 100) setTimeout(wait, 100); return; }
      PLANT_VIEW = "3d"; renderPlantView();
      document.querySelector('[data-fault="air_leak"]').click();
      var n = 0;
      (function poll() {
        var log = document.getElementById("fault-log").textContent;
        if (!/Done|Failed|off/.test(log) && ++n < 120) { setTimeout(poll, 500); return; }
        setTimeout(function () {
          var box = document.getElementById("plant-tiles");
          console.log("faulttest: log=" + log.slice(0, 80) + " | canvas=" + !!box.querySelector("canvas") +
            " | fail=" + (box.querySelector(".floor-fail") ? box.textContent.slice(0, 120) : "none") +
            " | size=" + box.clientWidth + "x" + box.clientHeight + " | view=" + PLANT_VIEW);
          closeFaults();
        }, 4000);
      })();
    })();
  })();

  (function floorSelftest() {
    if (new URLSearchParams(window.location.search).get("selftest") !== "floor") return;
    var tries = 0;
    (function wait() {
      if (!PLANT_ARGS) { if (++tries < 100) setTimeout(wait, 100); return; }
      PLANT_VIEW = "3d";
      for (var i = 0; i < 25; i++) renderPlantView();
      setTimeout(function () {
        var ok = document.querySelector("#floor canvas") && !document.querySelector(".floor-fail");
        console.log(ok ? "floortest ok" : "floortest FAILED: " + (document.getElementById("plant-tiles").textContent || "no canvas"));
      }, 1500);
    })();
  })();

  /* ---------- router ---------- */
  var loaders = { plant: loadPlant, detect: loadDetect, health: loadHealth, optimise: loadOptimise, act: loadAct, impact: loadImpact, payback: loadPayback, heats: loadHeats, bill: loadBill, brief: loadBrief, twin: loadTwin };
  function current() {
    var h = (window.location.hash || "#plant").replace("#", "").split("?")[0];
    return SCREENS.indexOf(h) >= 0 ? h : "plant";
  }
  function show() {
    var s = current();
    var prev = show._cur || null;
    var sIdx = SCREENS.indexOf(s), pIdx = prev ? SCREENS.indexOf(prev) : -1;
    SCREENS.forEach(function (k) {
      var scr = document.getElementById("screen-" + k);
      if (!scr) return;
      scr.classList.toggle("active", k === s);
      if (k !== s) scr.classList.remove("leaving");
    });
    /* Outgoing screen fades out in place while the incoming fades in and
     * slides 16 px -> 0 in the direction of travel (next = from right,
     * previous = from left). Transform/opacity only, no layout animation. */
    if (prev && prev !== s && !reducedMotion()) {
      var dir = sIdx >= pIdx ? 1 : -1;
      var oldEl = document.getElementById("screen-" + prev);
      var newEl = document.getElementById("screen-" + s);
      if (oldEl && oldEl.animate) {
        oldEl.classList.add("leaving");
        var fade = oldEl.animate([{ opacity: 1 }, { opacity: 0 }],
          { duration: 200, easing: EASE_OUT });
        (function (leaver, anim) {
          function done() { leaver.classList.remove("leaving"); }
          if (anim && anim.finished) anim.finished.then(done, done);
          else setTimeout(done, 220);
        })(oldEl, fade);
      }
      if (newEl && newEl.animate) {
        newEl.animate(
          [{ opacity: 0, transform: "translateX(" + dir * 16 + "px)" },
           { opacity: 1, transform: "translateX(0px)" }],
          { duration: 260, easing: EASE_OUT });
      }
    }
    show._cur = s;
    document.querySelectorAll(".nav-step").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-screen") === s);
    });
    closeTrail();
    /* ?trail=<key> opens a number's trail once the screen has loaded
     * (used to capture the provenance panel for the deck). */
    Promise.resolve(loaders[s]()).then(function () {
      refreshCHero(s);
      animateHeroNumbers(document.getElementById("screen-" + s));
      var t = new URLSearchParams(window.location.search).get("trail");
      if (t) openTrail(t);
    });
  }
  window.addEventListener("hashchange", show);

  /* The stage is a fixed 16:9 canvas; scale it to fit the window so the
   * browser shows exactly what the PPT slide shows. Narrow windows and
   * portrait tablets use the flow layout instead (same query as
   * console.css), so the stage is unscaled there. */
  var FLOW_Q = "(max-width: 1100px), (orientation: portrait)";
  function fit() {
    var st = document.getElementById("stage");
    if (window.matchMedia && window.matchMedia(FLOW_Q).matches) {
      document.documentElement.style.setProperty("--scale", "1");
      return;
    }
    var s = Math.min(window.innerWidth / st.offsetWidth, window.innerHeight / st.offsetHeight);
    document.documentElement.style.setProperty("--scale", String(s));
  }
  window.addEventListener("resize", fit);
  if (window.matchMedia && window.matchMedia(FLOW_Q).addEventListener) {
    window.matchMedia(FLOW_Q).addEventListener("change", fit);
  }
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
  if (new URLSearchParams(window.location.search).has("tour")) startTour();
})();
