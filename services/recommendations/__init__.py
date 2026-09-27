"""Recommendation engine package (Phase 4B, pure rules)."""

from services.recommendations.engine import BANNED_PHRASES, generate

__all__ = ["BANNED_PHRASES", "generate"]
