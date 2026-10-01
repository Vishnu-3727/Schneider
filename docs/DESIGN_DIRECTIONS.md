# JouleMitra Console — Design Directions

Research doc for the 11-screen console restyle. Nothing here is built yet.
The user picks one direction (or mixes axes); implementation starts after the pick.

Source of truth read for this doc: `apps/console/tokens.css`,
`apps/console/console.css`, `apps/console/index.html`, and the Console
section of `README.md`. No code was changed to write this doc.

## Hard constraints every direction must keep

These apply to A, B, and C equally. Each direction section below shows how
it keeps them rather than re-litigating them.

1. **Provenance colour rule.** Molten (`--color-accent`) means measured
   energy and waste only. Blueprint (`--color-projected`) means the
   projected plan only. Green (`--color-verified`) means verified saving
   only. Nothing else gets a colour. Grey-on-paper carries everything else.
2. **Fixed 1600x900 stage, scaled to fit.** Type floor stays `0.8rem`
   (`--text-micro`); nothing sets smaller. Phones (`<=760px`) fall back to
   the flowing layout, no scaled stage.
3. **Tamil and Hindi must render.** `?lang=ta|hi` loads Noto Sans Tamil /
   Noto Sans Devanagari through `--font-body`. Display faces must not break
   Tamil/Devanagari shaping or line height.
4. **Every figure comes from the live API.** Mockups and screenshots use
   metric placeholders (e.g. `[plant kW]`, `[deviation %]`), never invented
   numbers. `?static=1` stills are rendered from real API responses.

Placeholders used in this doc (all confirmed against live endpoints, never
mocked with numbers): `[plant kW]`, `[state]`, `[attention count]`,
`[deviation %]`, `[worst heat kWh/t]`, `[charge t]`, `[hold min]`,
`[last-24h ₹]`, `[score /100]`, `[ΔkWh]`, `[Δ₹]`, `[verified kWh]`,
`[uncertainty band]`, `[months]`, `[₹/yr]`, `[top-INR rank]`,
`[step k of 5]`, `[simulated heat cost ₹]`, `[kWh + SEC]`,
`[24h summary]`, `[compressed-air note]`, `[open alerts]`,
`[projected Δ₹]`, `[₹ + CO2]`.

---

## 1. Baseline audit

Hallmark audit of the current console (light "plant energy ledger":
chalk paper, molten + blueprint + verified provenance, Archivo with width
axis). Findings as a table:

| Severity | Finding | Where | Fix |
|---|---|---|---|
| major | Raw size values bypass tokens: px font sizes in diagram classes | `console.css` ~L130-135: 13/15/17/20/22px (`.d-cap`, `.d-note`, `.d-name`, `.d-val`, `.d-kw`), plus ad-hoc rem sizes (1.05, 0.93, 0.9, 1.1, 1.6, 3, 7rem) and radii 2/3/4px scattered through screens | Lift into named `--text-*` / `--radius-*` tokens; diagram text uses the same scale as the rest |
| major | One-face system: `--font-display` / `--font-body` / `--font-numerals` / `--font-mono` all alias Archivo, so codes, timestamps, and rule IDs have no mono voice | `tokens.css` L22-26 | Add a real mono or condensed-numeral role (system mono stack or a narrow grotesk) for codes, timestamps, rule IDs; keep Archivo for prose and KPIs |
| minor | Topbar carries 11 nav steps + fault button + legend in one 0.93rem row | `console.css` L428-429, `index.html` L22-28 | Group into See / Decide / Prove phases with breathing room, or collapse to the direction's nav pattern; keep all 11 reachable by click and arrow keys |
| minor | Every screen uses the same head (h1 + sub left, chips right) then body rhythm | All 11 `.screen-head` blocks in `index.html` | Keep the head contract but vary the body lead per direction (zoom frame, hero number, bento tile) so screens stop reading as one template |
| minor | Radial-gradient background on `.twin-stage` is the only gradient; reads as decoration | `console.css` L290 | Either commit to a surface system (all sheets share it) or drop the gradient for flat paper |
| minor | Six `!important` overrides | `console.css` L113, 131, 134, 156, 259, 286 | Remove via specificity order (later rule or a scoped class) when tokens are lifted |
| minor | `.keys` hint is absolutely positioned at the stage bottom and can overlap content | `console.css` L68 | Dock it into the topbar or a footer strip, or hide below a height breakpoint |

Strengths to keep in every direction: provenance colour discipline
(measured / projected / verified only), tabular numerals on all figures,
visible focus rings, `prefers-reduced-motion` handling plus `?static=1`
stills, and the hairline-and-one-sheet surface model (regions framed by
hairlines, one raised sheet per screen for the key element).

---

## 2. Direction A — Blueprint spine

**Idea.** The Plant wiring diagram stops being screen 1 and becomes the
console itself: a light-paper blueprint grid with the furnace, bus, and
feeds drawn as a hub-and-spoke spine. Every other screen opens as a zoom
into one node of that diagram, with a mini-map breadcrumb showing where
you are ("Plant > Furnace > Heats"). Navigation feels like walking the
plant, not paging slides. Paper stays light and warm; thin blueprint-grid
hairlines replace the single decorative gradient; tags sit on the
connecting lines the way cable labels sit on a real single-line diagram.

**References.**

- Modern Treasury — https://moderntreasury.com — hub node with labelled
  tags on thin connecting lines over a quiet grid; warm off-white paper.
  Take: the node-and-tag composition and the restrained line weight, not
  their teal palette.
- Zudo — https://www.zudo.amsterdam — a dense isometric scene used as the
  page itself. Take: density and confidence (the diagram fills the frame),
  not the pastel cartoon style.

**Token changes.**

| Token | Current | Proposed A | Note |
|---|---|---|---|
| `--color-paper` | `oklch(96% 0.005 110)` | `oklch(97.5% 0.008 100)` warm sheet | Slightly lighter so grid hairlines read |
| `--color-sheet` | `oklch(99.4% 0.002 110)` | `oklch(99.6% 0.002 100)` | Zoom cards sit clean on the grid |
| `--color-ink` | `oklch(24% 0.025 255)` | `oklch(26% 0.03 260)` graphite-blue | Blueprint-ink titles |
| `--color-accent` (molten) | `oklch(64% 0.19 42)` | `oklch(60% 0.185 42)` | A touch deeper so hot feeds read on lighter paper |
| `--color-projected` | `oklch(52% 0.17 265)` | `oklch(54% 0.16 262)` | Wiring-blue lines + zoom links |
| `--color-verified` | `oklch(50% 0.11 160)` | unchanged | Provenance green untouched |
| Type | Archivo only | Archivo display + system mono for node tags / rule IDs (e.g. `ui-monospace, "Cascadia Mono", Menlo, monospace`) | Fixes the one-face audit finding |
| Spacing | `--space-*` 0.25-3rem | unchanged scale; add `--space-grid: 2rem` snap for diagram nodes | Diagram and cards share one rhythm |
| Radii | sheet/panel 0.375rem, pill 999px | sheet/panel `0.25rem`, node tags `0.25rem`, pill kept for lang + view toggles | More drafted, less soft |

**Per-screen changes (all 11).**

| Screen | Change in A |
|---|---|
| Plant | Becomes the spine: full-frame wiring diagram on blueprint grid, tags show `[kW]`, `[state]`, `[attention count]`; 3D floor kept behind the same view toggle |
| Detect | Zoom into the flagged feeder: mini-map "Plant > Compressor > Detect"; alert cards dock to their node; chart sheet unchanged otherwise |
| Heats | Zoom into furnace node: bench scale drawn as a tapped scale on the grid line; table sheet unchanged, worst-heat row keeps molten wash |
| Twin | Zoom into furnace controls: 3D stage framed as a drafted plate (corner ticks, plate label `[charge t]`, `[hold min]`); run button unchanged |
| Bill | Ribbon becomes a cable run across the spine: heating / melting / holding / idle segments keep current fills; three panels hang below as tagged branches |
| Health | Each machine's score sits on its node as a tag (`[score /100]`); insights list becomes branch annotations |
| Plan | Optimiser board drawn as tomorrow's wiring state: lanes keep layout, bands use blueprint dashes; tariff strip becomes line labels |
| Brief | Message card becomes a pinned work-order on the grid; lang buttons + Tamil/Hindi rendering unchanged; rank list stays as ordered tags |
| Act | Stepper redrawn as five nodes on one line with the live node hot; rec card + result panels dock under their nodes |
| Prove | Hero saving (`[verified kWh]`, `[uncertainty band]`) stamped on the verified branch; steps + chart panels unchanged |
| Scale | Sliders stay; payback hero (`[months]`, `[₹/yr]`) shown as the spine's end-node tag; scale table unchanged |

**How the provenance rule survives.** Only the three provenance hues ever
fill nodes or tags: molten fills hot feeds and waste tags, blueprint draws
projected wiring and tomorrow's lanes, green marks verified branches and
the Prove stamp. Grid, plates, and mini-map chrome stay graphite and grey.

**Risks.** Contrast: lighter paper plus thin grid lines can shimmer on a
projector — grid must stay at or below 1px hairline at low chroma.
Tamil/Hindi: node tags must fall back to `--font-body` (Noto coverage) and
never use the mono face for Tamil/Devanagari strings. 16:9 stage: the
full-frame diagram must keep the head + mini-map clear of the
`--space-10` gutters at 1600x900. Projector: warm paper washes out under
strong lights; test at full brightness before judging day.

**Effort: M.** Mostly `console.css` (topbar -> spine nav, `.diagram`,
`.twin-stage` gradient -> grid, stepper -> nodes) plus small `index.html`
nav/breadcrumb structure and one or two new tokens in `tokens.css`.
`console.js` zoom wiring is the only logic work.

## 2. Direction B — Dark control room

**Idea.** A dark paper (~L 18-22%) for projector halls: the console reads
as a control-room HMI where grey-on-dark carries all normal state and
colour appears only for measured waste, projected plans, and verified
savings. Condensed numerals, flat surfaces, no glow, no gradients. From
first principles this follows control-room HMI convention (grey means
normal, colour means state — cf. ISA-101 style practice): the calmest
screen in a dark hall wins the judges' attention, and every lit pixel
means something.

**References.**

- Novu — https://novu.co — near-black paper `#0a0a0f`, single cool accent,
  mono tokens inside headings. Take: discipline of one accent + mono detail.
- Fullstory — https://fullstory.com — deep teal-indigo dark with one green
  accent `#06d49c`. Take: how a single green can carry "good" on dark.
- Mage — https://mage.ai — dark product UI framed under the headline.
  Take: headline-first dark composition.
- Avoid in all three: their gradients and glows. This direction ships flat.

**Token changes.**

| Token | Current | Proposed B | Note |
|---|---|---|---|
| `--color-paper` | `oklch(96% 0.005 110)` | `oklch(20% 0.012 260)` dark slate | Projector-hall paper |
| `--color-sheet` | `oklch(99.4% 0.002 110)` | `oklch(25% 0.014 260)` raised sheet | One step above paper, flat |
| `--color-surround` | `oklch(86% 0.006 120)` | `oklch(14% 0.01 260)` letterbox | Stage floats on near-black |
| `--color-ink` | `oklch(24% 0.025 255)` | `oklch(92% 0.01 260)` primary text | Grey-on-dark body |
| `--color-ink-2/3` | `oklch(45%/50% ...)` | `oklch(72% 0.012 260)` / `oklch(62% 0.012 260)` | Secondary/quiet — to verify: target >= 4.5:1 on sheet (verify with a contrast checker) |
| `--color-accent` (molten) | `oklch(64% 0.19 42)` | `oklch(74% 0.17 48)` | Lifted for dark contrast; soft wash `oklch(32% 0.06 45)` |
| `--color-projected` | `oklch(52% 0.17 265)` | `oklch(76% 0.13 265)` | Lightened blueprint; soft `oklch(30% 0.05 265)` |
| `--color-verified` | `oklch(50% 0.11 160)` | `oklch(74% 0.13 165)` | Lightened green; soft `oklch(30% 0.05 165)` |
| Type | Archivo only | Archivo (wdth 88-100) for labels + condensed numeral role for KPIs; mono for codes/timestamps | Density without glow |
| Spacing | unchanged | unchanged; increase `.screen` side padding one step (`--space-10` kept) so dark edges breathe | — |
| Radii | 0.375rem sheets | sheets `0.375rem` kept; pills kept; remove the one radial gradient | Flat control-room surfaces |

**Per-screen changes (all 11).**

| Screen | Change in B |
|---|---|
| Plant | Diagram inverts: graphite wires become light-grey, hot feeds molten-light; KPI row uses condensed numerals; attention strip keeps dot semantics |
| Detect | Chart re-themed to dark (grid grey, actual molten, expected dashed light-blue); alert deviation (`[deviation %]`) is the brightest element |
| Heats | Bench bands use dark soft washes; worst-heat row wash deepened; table header hairline lightened |
| Twin | `radial-gradient` removed; 3D stage flat dark; phase pill + control labels lightened; run button becomes light-on-dark primary |
| Bill | Ribbon segments re-lit (heating light-grey, melting mid-grey, holding molten, idle hatched dark); PF/demand, reject, carbon panels keep layout |
| Health | Bars become light-grey on dark track; scores (`[score /100]`) in condensed numerals; insights text at `--color-ink-2` |
| Plan | Board bands + blocks re-tuned to blueprint-light on dark; live deltas (`[ΔkWh]`, `[Δ₹]`) keep projected hue |
| Brief | Message card becomes the light sheet on dark (highest contrast on the screen); Tamil/Hindi to verify at full weight on the card (check shaping and weight with a rendering check) |
| Act | Stepper line light-grey, done nodes filled light, final verified node green-light; rec + result panels unchanged structurally |
| Prove | Hero saving (`[verified kWh]`) in lightened green at `--text-hero`; stamp stays solid green with dark text; guardrail + chart re-themed |
| Scale | Sliders use light thumbs on dark track; payback hero (`[months]`) in blueprint-light; scale table hairlines lightened |

**How the provenance rule survives.** The rule gets stricter on dark:
grey-on-dark is always normal, and the only saturated pixels are molten
(measured), blueprint-light (projected), and green-light (verified). Warn
red keeps its current role for critical states in data, re-tuned for dark
(proposed `oklch(70% 0.17 25)` with soft wash `oklch(30% 0.06 25)`): it
marks the over-limit segment (`.s-over` in `console.css`), worse-than-plan
deltas (`.pl-live .bad`), refused / not-comparable verdict stamps
(`.stamp.warn`), and warn badges (`.badge.warn`).

**Risks.** Contrast: every text/line pair must be re-checked — lightening
three hues at once easily breaks 4.5:1 on small Tamil/Devanagari glyphs.
Tamil/Hindi: Noto Tamil/Devanagari at light weights on dark can look thin
on projectors; keep 500+ weight minimum for `?lang=ta|hi` body. 16:9
stage: dark stages show letterbox gaps less, but dust and glare show more;
keep the surround near-black. Projector: the biggest win (dark halls) is
also the biggest risk in lit rooms — dark washes out faster than light.

**Effort: M-L (borderline).** Token inversion touches `tokens.css` plus
nearly every `console.css` surface, chart colours, ribbon/band washes, and
the 3D scenes. Structure in `index.html` barely changes. Call it M for
tokens + CSS, L if Plotly/Three themes need per-chart work.

## 2. Direction C — Stat-led bento

**Idea.** Each screen leads with one huge answer tile — the screen's
single takeaway (`[plant kW]`, `[worst heat kWh/t]`, `[verified saving]`)
— followed by irregular supporting tiles, never an equal 3-column grid.
The bento rhythm varies per screen (hero-left, hero-top, hero-right) so
all 11 screenshots read differently in the deck while the head contract
(h1 + sub + chips) stays put. Cool light paper, hero tile carries the
screen's main accent while supporting tiles keep their own
measured/projected/verified figure colours, tag-chip rows for provenance. Archive evidence supports the bones:
across 24 technical sites, ~75% set grotesks, light paper is most common,
and cool accents lead.

**References.**

- Supernova / Canvas — https://canvasapp.com — cool light paper with
  product data floating on soft shadow. Take: airy tile composition (their
  TWK Lausanne + Inter pairing is the type cue).
- DuckDB — https://duckdb.org — light paper, single strong accent,
  tag-chip rows. Take: chip-row provenance tagging.
- Burb — https://burb.co — bento of stat tiles under a heavy display face.
  Take: the lead-number tile pattern and irregular tile sizes.

**Token changes.**

| Token | Current | Proposed C | Note |
|---|---|---|---|
| `--color-paper` | `oklch(96% 0.005 110)` | `oklch(95% 0.01 230)` cool paper | Cooler canvas for bento tiles |
| `--color-sheet` | `oklch(99.4% 0.002 110)` | `oklch(99.5% 0.004 230)` hero tile | Hero tile pops one step above supporting tiles |
| `--color-ink` | `oklch(24% 0.025 255)` | `oklch(22% 0.03 260)` | Slightly inkier display face |
| `--color-accent` (molten) | `oklch(64% 0.19 42)` | `oklch(62% 0.19 42)` kept; hero tile carries the screen's main accent | Hero-led accent; supporting figures keep provenance colours |
| `--color-projected` | `oklch(52% 0.17 265)` | `oklch(50% 0.18 265)` slightly deepened | Reads on cooler paper |
| `--color-verified` | `oklch(50% 0.11 160)` | unchanged | — |
| Type | Archivo width axis | Archivo Expanded (wdth 112-125) hero numerals at `--text-hero` scale; mono for rule IDs/timestamps; supporting tiles at 88-100 width | Hero vs detail voice split |
| Spacing | even `--space-5` gaps | Keep scale; vary gap per screen (hero gap `--space-8`, detail gap `--space-4`) | Irregular rhythm from spacing, not new units |
| Radii | 0.375rem sheets | hero tile `0.75rem`, supporting `0.375rem`, chips pill | Size contrast carries hierarchy |

**Per-screen changes (all 11).**

| Screen | Hero answer tile + supporting tiles |
|---|---|
| Plant | Hero: `[live plant kW]`; support: attention strip, wiring diagram tile, `[open alerts]` count tile |
| Detect | Hero: `[largest deviation %]`; support: actual-vs-expected chart, alerts list, `[compressed-air note]` |
| Heats | Hero: `[worst heat kWh/t]`; support: benchmark scale, `[24h summary]` tiles, heats table |
| Twin | Hero: `[simulated heat cost ₹]`; support: 3D stage tile, controls tile, `[kWh + SEC]` out tile |
| Bill | Hero: `[last-24h ₹]` ribbon total; support: ribbon, PF/demand, reject-energy, carbon tiles (varied widths) |
| Health | Hero: `[lowest health score /100]`; support: score list, insights list |
| Plan | Hero: `[projected Δ₹]`; support: optimiser board, tariff strip, explainer |
| Brief | Hero: the brief message card itself; support: lang switch, `[top-INR rank]` list, why-panel |
| Act | Hero: current step (`[step k of 5]`); support: stepper strip, rec card, result list |
| Prove | Hero: `[verified kWh]` + stamp; support: guardrail steps, expected-vs-measured chart, `[₹ + CO2]` cards |
| Scale | Hero: `[payback months]`; support: sliders, ruler, scale table |

**How the provenance rule survives.** The hero tile carries the screen's
main accent: measured heroes (Plant, Detect, Heats, Twin, Bill) set
molten; projected heroes (Plan, Scale) set blueprint; verified heroes
(Prove, and Scale's verified-input line) set green. Supporting tiles still
colour their own measured / projected / verified figures by provenance
(e.g. hot rows in the Heats table, alert deviations on Detect, hot feeds
on the Plant diagram); only non-provenance chrome stays ink and grey, with
tag chips; the legend row is unchanged.

**Risks.** Contrast: oversized numerals at low weight can fail at stage
scale — keep hero weight >= 800. Tamil/Hindi: expanded display faces must
not touch Tamil/Devanagari strings; Brief hero stays in `--font-body`.
16:9 stage: bento grids must be designed at 1600x900 first — a hero +
irregular tiles that fits the stage can overflow the `<=760px` flow, so
the phone fallback stacks hero-first explicitly. Projector: best of the
three — huge numerals survive glare and photograph well for the deck.

**Effort: S-M.** Mostly `console.css` grid work (hero + tile classes per
screen) and `index.html` tile order; tokens barely move. Smallest logic
footprint of the three — no nav or theme inversion.

---

## 3. Comparison and recommendation

| Axis | A — Blueprint spine | B — Dark control room | C — Stat-led bento |
|---|---|---|---|
| Judge first impression | Most distinctive: the plant diagram as navigation reads as craft | Most dramatic in a dark hall; weakest in a lit room | Clearest: every screen answers in one number |
| Data density | Highest (diagram + tags + zoom panels) | Medium (dark needs more air to stay legible) | Medium-high (hero + supporting tiles, no equal grids) |
| Projector legibility | Riskiest (thin grid lines shimmer) | Best in dark halls, worst in lit rooms | Best overall (huge numerals survive glare) |
| Deck screenshot quality | Strong when zoomed; full-spine shots get busy | Striking covers, but mixed with light slides it jars | Strongest: 11 visually distinct answer-tiles |
| Effort | M (nav/breadcrumb + diagram CSS + zoom logic) | M-L (full theme inversion + chart/3D re-theme) | S-M (grid + tile order, tokens nearly still) |
| Risk | Grid contrast + Tamil in node tags + phone fallback for the spine | Contrast re-check on everything + lit-room washout | Hero overflow on small tiles + display-face discipline |

**Recommendation: build C first, steal one axis from A.**

C is the safest judge bet: it keeps the current light theme and
provenance discipline, costs the least, fixes the monotone-head audit
finding directly (every screen gets a different hero), and produces the
best deck screenshots — which is half the brief. Then take A's mini-map
breadcrumb ("Plant > Furnace > Heats") as a cheap second axis: it adds the
walking-the-plant feel to C's tiles without the full blueprint-grid
re-theme. Keep B in reserve for a dark-hall final: if the judging room is
confirmed dark, re-tune C's hero tiles onto B's dark paper as a follow-up
rather than betting the whole console on it now.

---

## Pick

Pick **A**, **B**, or **C** — or mix: say which axis from which
(e.g. "C tiles + A breadcrumb"). Nothing is built until you choose.
