"""Modbus register map -> canonical fields (pure decoding, no I/O).

A register map is data (JSON), one entry per canonical field:
  {"field": "energy_kwh", "address": 40, "dtype": "uint32", "word_order": "big",
   "byte_order": "big", "scale": 0.001, "offset": 0.0, "unit": "kWh",
   "min": 0, "max": 1e9, "invalid": [4294967295]}

- dtype: uint16 | int16 | uint32 | int32 | float32 (32-bit types use two
  registers). Modbus sends each register big-endian. Devices differ in how
  they order the two words of a 32-bit value (word_order "big" = high word
  first, "ABCD"; "little" = low word first, "CDAB") and a few also swap the
  bytes inside each register (byte_order "little", "BADC"/"DCBA").
- value = raw * scale + offset (unit conversion, e.g. Wh -> kWh = 0.001).
- invalid: vendor "not available" sentinels (e.g. 0xFFFF / 0x7FFF / NaN).
  A sentinel, non-finite value or out-of-range value becomes None plus an
  issue. It is never forwarded as a number.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

WIDTH = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}
FMT = {"uint16": ">H", "int16": ">h", "uint32": ">I", "int32": ">i", "float32": ">f"}


@dataclass
class RegisterSpec:
    field: str
    address: int
    dtype: str = "uint16"
    word_order: str = "big"
    byte_order: str = "big"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    min: float | None = None
    max: float | None = None
    invalid: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dtype not in WIDTH:
            raise ValueError(f"unsupported dtype {self.dtype!r}")
        if self.word_order not in ("big", "little") or self.byte_order not in ("big", "little"):
            raise ValueError("word_order / byte_order must be 'big' or 'little'")

    @property
    def width(self) -> int:
        return WIDTH[self.dtype]


def raw_value(spec: RegisterSpec, regs: list[int]) -> float:
    """Decode the raw (unscaled) number from this spec's registers."""
    if len(regs) != spec.width or any(not 0 <= r <= 0xFFFF for r in regs):
        raise ValueError(f"{spec.field}: expected {spec.width} 16-bit register(s), got {regs}")
    words = list(regs) if spec.word_order == "big" else list(reversed(regs))
    data = b"".join(w.to_bytes(2, "big") for w in words)
    if spec.byte_order == "little":
        data = b"".join(data[i:i + 2][::-1] for i in range(0, len(data), 2))
    return struct.unpack(FMT[spec.dtype], data)[0]


def encode(spec: RegisterSpec, raw: float) -> list[int]:
    """Inverse of raw_value (used by the simulated meter and tests)."""
    fmt = FMT[spec.dtype]
    data = struct.pack(fmt, raw if spec.dtype == "float32" else int(raw))
    if spec.byte_order == "little":
        data = b"".join(data[i:i + 2][::-1] for i in range(0, len(data), 2))
    words = [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]
    return words if spec.word_order == "big" else list(reversed(words))


def decode(specs: list[RegisterSpec], block: dict[int, int]) -> tuple[dict, list[str]]:
    """Decode every spec from an address->register map. Returns (fields, issues)."""
    fields: dict[str, float | None] = {}
    issues: list[str] = []
    for s in specs:
        regs = [block.get(s.address + k) for k in range(s.width)]
        if any(r is None for r in regs):
            fields[s.field] = None
            issues.append(f"{s.field}: register {s.address} not read")
            continue
        raw = raw_value(s, regs)
        if raw in s.invalid or (isinstance(raw, float) and not math.isfinite(raw)):
            fields[s.field] = None
            issues.append(f"{s.field}: device reports 'not available' ({raw})")
            continue
        value = raw * s.scale + s.offset
        if (s.min is not None and value < s.min) or (s.max is not None and value > s.max):
            fields[s.field] = None
            issues.append(f"{s.field}: {value} {s.unit} outside plausible range "
                          f"[{s.min}, {s.max}]")
            continue
        fields[s.field] = round(value, 6)
    return fields, issues


def load_map(entries: list[dict]) -> list[RegisterSpec]:
    return [RegisterSpec(**e) for e in entries]


def span(specs: list[RegisterSpec]) -> tuple[int, int]:
    """(first address, count) covering every register in the map (one read)."""
    lo = min(s.address for s in specs)
    hi = max(s.address + s.width for s in specs)
    return lo, hi - lo
