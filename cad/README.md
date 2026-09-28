# JouleMitra — CAD references (Phase 7, owner-made, docs only)

`cad/electrical/` (AutoCAD Electrical schematic: power, signal, protection)
and `cad/enclosure/` (Fusion 360 enclosure) hold owner-made
references/exports only. No CAD files are in the repo yet — both folders
currently contain only a `.gitkeep`. No firmware, no deploy units, and no
physical hardware are covered here.

## Expected drawings

File naming: `<site>-<sheet>-<rev>.<ext>`, e.g.
`demoplant-power-01-A.pdf`. Native sources (`.dwg`, `.f3d`/`.step`) may sit
alongside the export; the export (`.pdf`/`.png`/`.step`) is authoritative
for review.

| # | Folder | Expected file | Must match |
|---|---|---|---|
| E1 | `cad/electrical/` | `<site>-power-01-<rev>.pdf` — single-line: feeder, CTs/PTs, meter aux supply, MCB/fuse, SPD, earthing | `docs/deployment/WIRING.md` §2 (CT/PT), §6 (protection/earthing) |
| E2 | `cad/electrical/` | `<site>-signal-02-<rev>.pdf` — RS-485 A/B/GND daisy-chain (meter to RS-485-to-TCP converter), termination points, shield ground (one end), segregation from mains; plus converter-to-gateway Ethernet run; or direct Modbus TCP Ethernet run | `docs/deployment/WIRING.md` §3 or §4 |
| E3 | `cad/electrical/` | `<site>-terminal-03-<rev>.pdf` — terminal/signal list: X1 shorting-link block, meter inputs, converter port + gateway Ethernet port | `docs/deployment/WIRING.md` §7 table |
| M1 | `cad/enclosure/` | `<site>-enclosure-01-<rev>.step/.pdf` — DIN-rail enclosure: meter, X1 block, MCB/fuse, RS-485-to-TCP converter, cable entries, IP rating note | `docs/deployment/WIRING.md` §6 (enclosure/IP) |

Every drawing carries its own title block (site, date, revision, drawn by);
ratings follow WIRING.md §6 and stay tagged ASSUMPTION until the plant
electrician confirms them. Monitoring-only boundary (WIRING.md §0) applies
to all sheets: no control or safety-circuit wiring appears on any drawing.
