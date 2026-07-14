"""Compatibility entry point for BBLOTTO AI-03 explanation engine.

The recommendation engine generates numbers; this module only explains the
actual AI-01 cache and AI-02 recommendation output in 3-5 concise Korean lines.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .ai.explanation_engine import (
    EXPLANATION_ENGINE_VERSION,
    build_round_analysis,
)


def build_evidence_analysis(
    round_no: int,
    stats: Dict[str, Any],
    mode: str,
    fixed: Any,
    excluded: Any,
    details: List[Dict[str, Any]],
) -> str:
    return build_round_analysis(round_no, stats, mode, fixed, excluded, details)


def build_recommendation_analysis(round_no: int, details: List[Dict[str, Any]]) -> str:
    return build_round_analysis(round_no, {}, "balanced", None, None, details)


__all__ = [
    "EXPLANATION_ENGINE_VERSION",
    "build_evidence_analysis",
    "build_recommendation_analysis",
]
