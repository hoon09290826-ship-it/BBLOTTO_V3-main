"""Compatibility entry point for BBLOTTO explanation engine."""
from __future__ import annotations

from typing import Any, Dict, List

from .ai.explanation_engine import (
    EXPLANATION_ENGINE_VERSION,
    build_round_analysis,
    build_recommendation_analysis as _build_recommendation_analysis,
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
    return _build_recommendation_analysis(round_no, details)


__all__ = [
    "EXPLANATION_ENGINE_VERSION",
    "build_evidence_analysis",
    "build_recommendation_analysis",
]
