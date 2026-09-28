# JouleMitra — Reference wiring for a plant install (Phase 7, docs only)

Monitoring-only reference. No firmware, no control wiring, no commissioning
of physical hardware is covered here. The analytics consume only canonical
telemetry (see `docs/DEPLOYMENT.md`); this file describes how a real meter
reaches the gateway. Register layout is data: `edge/config/energy_meter_map.json`
(an ILLUSTRATIVE layout — confirm against the meter manual on site before
trusting any value).

## 0. Monitoring-only statement (spec MASTER_SPEC §6)

This install is monitoring only. JouleMitra is human-in-the-loop decision
support only: no connection from the meter, gateway, ESP32 node, or any
JouleMitra wiring to furnace / motor / actuator control, contactor coils,
drives, PLCs, or safety circuits. Control and protection stay exactly as the
plant found them.

All mains work (CT/PT terminations, MCB/fuse, earthing, enclosure) is done
by a licensed electrician per local code (IS 732 / CEA regulations — verify
which edition applies at this plant). De-energise, lock out, and prove dead
before touching any mains terminal.

## 1. Block diagram

```text
                    PLANT 3-PHASE SUPPLY (to load, e.g. furnace feeder)
                    L1 ─────────────■───────────────▶ load
                    L2 ─────────────■───────────────▶ load
                    L3 ─────────────■───────────────▶ load
                    N  ─────────────■───────────────▶ load
                                    │ CT window / PT tap (metering only)
            ┌───────────────────────┼───────────────────────┐
            │  CT1  CT2  CT3         │         PT / direct V │
            │  (S1/S2 each, shorting-link block)            │
            └───────┬───────────────┼───────────┬───────────┘
                    │ secondaries   │ V sense   │
            ┌───────▼───────────────▼───────────▼───────────┐
            │  THREE-PHASE ENERGY METER (metering only)     │
            │  CT inputs + V inputs + aux supply (fused)    │
            └───────┬───────────────────────────┬───────────┘
                    │ Modbus RTU (RS-485)       │ Modbus TCP (direct)
                    │ A/B/GND, daisy-chain      │ Ethernet to plant LAN
                    ▼                           ▼
            ┌───────────────────────┐           │
            │ RS-485-to-Modbus-TCP  │           │
            │ CONVERTER (serial     │           │
            │ device server /       │           │
            │ Modbus gateway,       │           │
            │ isolated, DIN-rail)   │           │
            └───────────┬───────────┘           │
                        │ Ethernet              │ Ethernet
                        ▼                       ▼
            ┌───────────────────────────────────────────────┐
            │  EDGE GATEWAY (Raspberry Pi or industrial PC) │
            │  Ethernet only — Modbus TCP (host/port);      │
            │  no direct serial RTU in current software     │
            │  → edge/gateway → POST /telemetry (HTTP)      │
            └───────────────────────────────────────────────┘
                                    ▲
                    optional health │ MQTT (ESP32 vibration node)
                    complement only │
            ┌───────────────────────┴───────────────────────┐
            │  ESP32 VIBRATION NODE (SELV, USB/adapter fed) │
            │  vibration + temperature; no mains contact    │
            └───────────────────────────────────────────────┘
```

Either the RTU-via-converter path or the direct-TCP path is used per
meter, not both. RTU meters never wire serial directly to the gateway: the
RS-485 bus ends at an RS-485-to-Modbus-TCP converter, and the gateway
reaches the meter over Ethernet as Modbus TCP (see §3). Direct serial RTU
on the gateway (USB/on-board RS-485 adapter) is NOT implemented in the
current software (`edge/modbus/device.py` provides a Modbus TCP client
only); adding it would be a code change (a serial device class) and is out
of scope. The ESP32 node is optional and never in the energy path.

## 2. Meter to CTs / PTs

- CTs are metering-class, one per phase (L1/L2/L3), sized to the feeder.
  CT ratio (e.g. ASSUMPTION: 200/5 A — verify with plant electrician)
  is programmed into the meter, not into JouleMitra.
- CT secondary (S1/S2) wiring lands on a shorting-link (disconnect/shorting)
  terminal block before the meter. Procedure: short the secondary at the
  block first, then work downstream. A CT secondary is never left
  open-circuit while the primary is energised (open secondaries develop
  dangerous voltage).
- Polarity (S1 toward source / P1 toward source) is kept consistent on all
  three phases so power and power factor read correctly; a reversed CT shows
  as negative power on that phase at the meter display.
- Voltage sensing is direct (LT 415 V nominal per `docs/ASSUMPTIONS.md` A3)
  or via PTs where the panel requires it. PT ratio, if any, is programmed
  into the meter (ASSUMPTION: direct 415 V connection — verify with plant
  electrician).
- Meter auxiliary supply is separately fused (ASSUMPTION: 2 A gG fuse or
  6 A MCB, C-curve — verify with plant electrician). Metering CT/PT leads
  are individually fused where the meter manual requires it.

## 3. Meter to gateway — Modbus RTU via RS-485-to-Modbus-TCP converter

- Path: meter RS-485 port → shielded-twisted-pair bus → RS-485-to-Modbus-TCP
  converter (serial device server / Modbus gateway, DIN-rail, isolated
  preferred) → Ethernet → edge gateway. The gateway itself speaks Modbus TCP
  only; there is no direct serial RTU connection to the gateway.
- Bus: shielded twisted pair, A / B / GND. GND (signal common) is wired;
  the bus is not left floating on A/B alone.
- Topology is daisy-chain from converter to meter(s), not star. One
  continuous run, short stubs only.
- Termination: 120 ohm resistor at each physical end of the bus only
  (converter end + far meter end). Intermediate devices are not terminated.
- Bias (fail-safe pull-up/pull-down) at one point on the bus, normally the
  converter end (ASSUMPTION: converter-provided 680 ohm bias — verify with
  plant electrician against the converter manual).
- Shield is grounded at one end only (converter end), to avoid ground loops.
- Cable is segregated from mains conductors (separate trunking/bundle;
  ASSUMPTION: 100 mm minimum separation — verify with plant electrician).
- Bus settings (slave ID, baud, parity, stop bits) are configured on the
  converter (and the meter), not in `gateway.json`. `gateway.json` holds
  only the converter's host, port, and `device_id` (slave/unit ID); see
  `docs/deployment/PROVISIONING.md`. Cable length/baud follow the converter
  and meter manuals.

## 4. Meter to gateway — Modbus TCP (alternative)

- Standard Ethernet from meter to the gateway (direct or via the plant LAN,
  whichever the site approves). No RS-485 termination/bias/shield rules
  apply on this path.
- Meter IP, subnet, gateway, Modbus TCP port (default 502), and unit/slave
  ID are recorded at deploy time in `gateway.json`.
- The register map is the same file (`edge/config/energy_meter_map.json`);
  only the transport differs.

## 5. Optional ESP32 vibration node (health complement only)

- The ESP32 node measures vibration/temperature near the machine frame and
  reports over MQTT. It is SELV-side only: USB or SELV adapter supply, no
  mains contact, no CT/PT connection, no control output.
- Mounting and sensor placement are mechanical (bracket/adhesive per sensor
  manual) and outside the scope of this wiring reference.

## 6. Protection, isolation, earthing, enclosure

All ratings below are PLACEHOLDERS tagged ASSUMPTION — verify with plant
electrician against the panel schedule and meter manual before purchase.

| Item | Reference value | Status |
|---|---|---|
| Meter aux-supply fuse/MCB | ASSUMPTION: 2 A gG fuse or 6 A MCB, C-curve | verify with plant electrician |
| CT secondary leads protection | ASSUMPTION: per meter manual; typically shorting-link block, no series fuse in the secondary loop unless the manual requires it | verify with plant electrician |
| RS-485 / SELV side isolation | galvanic isolation between mains (meter CT/PT side) and SELV/signal side (converter + gateway Ethernet/ESP32); isolated RS-485-to-TCP converter preferred | verify with plant electrician |
| Surge protection | ASSUMPTION: Type 2 SPD on the panel supply feeding the meter aux circuit, per existing panel scheme | verify with plant electrician |
| Earthing | panel earth bar bonded to enclosure, meter earth terminal, converter earth terminal, and RS-485 shield drain (one end) per IS 732 / CEA regulations | verify |
| Enclosure | DIN-rail enclosure for meter + shorting-link block + MCB/fuse + RS-485-to-Modbus-TCP converter; ASSUMPTION: IP54 in dusty plant areas (IP rating — verify with plant electrician for the location) | verify with plant electrician |
| Labelling | every core ferruled and labelled (L1/L2/L3/N, S1/S2 per CT, A/B/GND); single-line + terminal list pasted inside the enclosure door | — |

## 7. Terminal / signal table

Wire colours below follow no single plant standard — use the site's
standard and record it on the CAD schematic (see `cad/README.md`).

| From | To | Signal | Cable | Notes (§) |
|---|---|---|---|---|
| CT1/2/3 S1/S2 | shorting-link block X1 | 3× current secondaries | twisted pair per CT, 2.5 sq mm ASSUMPTION — verify with plant electrician | §2, never open-circuit |
| X1 load side | meter I1/I2/I3 inputs | current sense | same as above | polarity S1→I(k), S2→I(k*) |
| L1/L2/L3/N (fused tap) | meter V1/V2/V3/N (or via PTs) | voltage sense | 1.5 sq mm ASSUMPTION — verify with plant electrician | §2 |
| Panel aux (fused) | meter aux L/N | meter supply | per meter manual | §6 fuse row |
| Meter A/B/GND (RTU) | converter RS-485 port A/B/GND | Modbus RTU | shielded twisted pair + drain | §3, 120 ohm at converter end + far meter end only |
| Converter Eth | gateway Eth / plant LAN | Modbus TCP | Cat5e or better | §3, gateway.json holds converter host/port/device_id |
| Meter Eth (direct-TCP alt.) | gateway Eth / plant LAN | Modbus TCP | Cat5e or better | §4 |
| Converter supply (SELV) | converter power terminals | converter supply | per converter manual (SELV/aux as specified) | isolated converter preferred |
| ESP32 node (SELV) | gateway (MQTT over Wi-Fi/LAN) | vibration + temperature | no copper signal to mains side | §5, optional |

(Cable cross-sections are ASSUMPTIONs — verify with plant electrician
against run length and the meter manual.)

## 8. Register map (reference, not a copy)

The gateway decodes the meter using `edge/config/energy_meter_map.json`.
That file is the single source: `voltage_v` (addr 0, uint16, ×0.1),
`current_a` (addr 1, uint16, ×0.01), `power_kw` (addr 2, int32 big-endian
ABCD, register in W, ×0.001), `power_factor` (addr 4, int16, ×0.001),
`energy_kwh` (addr 5, uint32 little-endian CDAB low-word-first, register
in Wh, ×0.001), `reactive_power_kvar` (addr 7, float32 big-endian).
The map is ILLUSTRATIVE (see `docs/ASSUMPTIONS.md` A33): confirm addresses,
dtype, word/byte order, scale, and invalid sentinels against the installed
meter's manual during commissioning (`docs/deployment/PROVISIONING.md`),
and update the deployed copy of the map — never invent registers here.

## 9. What this doc does not cover

Firmware (`edge/firmware/` — not written), gateway service units
(`deploy/` — not written), CAD drawings themselves (`cad/` holds
owner-made references/exports only, none in the repo yet), cloud sync,
and any control or safety-circuit work (forbidden, §0).
