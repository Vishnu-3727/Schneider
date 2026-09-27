"""Recommendation / intervention lifecycle: the one place transitions are allowed.

PENDING_REVIEW (= PROJECTED) -> APPROVED | REJECTED
CONFLICT                     -> APPROVED | REJECTED
APPROVED -> APPLIED -> MEASURED -> VERIFIED | NOT_VERIFIED | NOT_COMPARABLE
                                   | INSUFFICIENT_DATA
Everything else is terminal.
"""

from __future__ import annotations

OUTCOMES = ("VERIFIED", "NOT_VERIFIED", "NOT_COMPARABLE", "INSUFFICIENT_DATA")

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING_REVIEW": ("APPROVED", "REJECTED"),
    "CONFLICT": ("APPROVED", "REJECTED"),
    "APPROVED": ("APPLIED",),
    "APPLIED": ("MEASURED",),
    "MEASURED": OUTCOMES,
}


def allowed(current: str) -> tuple[str, ...]:
    return TRANSITIONS.get(current, ())


def can(current: str, target: str) -> bool:
    return target in allowed(current)
