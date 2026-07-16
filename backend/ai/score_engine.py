from __future__ import annotations

import math
from collections import Counter
from itertools import combinations
from typing import Any, Callable, Dict, Sequence, Tuple

SCORE_ENGINE_VERSION = "BBLOTTO_AI_SCORE_V14_1_VERIFIED_GRADE"


def _value(mapping: Dict[str, Any], number: int, default: float = 0.0) -> float:
    try:
        return float(mapping.get(str(number), default))
    except (TypeError, ValueError):
        return default


def _normalize(values: Dict[int, float]) -> Dict[int, float]:
    if not values:
        return {number: 0.5 for number in range(1, 46)}
    low = min(values.values())
    high = max(values.values())
    if math.isclose(low, high):
        return {number: 0.5 for number in range(1, 46)}
    width = high - low
    return {number: (values[number] - low) / width for number in range(1, 46)}


def build_number_weights(cache: Dict[str, Any], mode: str = "balanced", grade: str = "일반") -> Dict[int, float]:
    """Build grade-specific number weights from recent and full history.

    Every grade uses the same verified cache, but the evidence blend is
    intentionally different.  Pair/triple centrality uses both recent and
    all-history maps so MASTER is not merely a scaled version of BASIC.
    """
    def norm_field(name: str, default: float = 0.0) -> Dict[int, float]:
        return _normalize({n: _value(cache.get(name, {}), n, default) for n in range(1, 46)})

    normalized = {
        "base": norm_field("score_map", 50.0),
        "f10": norm_field("frequency10"),
        "f30": norm_field("frequency30"),
        "f100": norm_field("frequency100"),
        "f300": norm_field("frequency300"),
        "all": norm_field("frequency_all"),
        "gap": _normalize({n: min(30.0, _value(cache.get("gap", {}), n)) for n in range(1, 46)}),
        "momentum": norm_field("momentum"),
    }

    def centrality(mapping_name: str, size: int) -> Dict[int, float]:
        mapping = cache.get(mapping_name, {}) or {}
        totals = {n: 0.0 for n in range(1, 46)}
        for key, raw in mapping.items():
            try:
                nums = [int(x) for x in str(key).split("-")]
                value = float(raw or 0)
            except (TypeError, ValueError):
                continue
            if len(nums) != size:
                continue
            for n in nums:
                if 1 <= n <= 45:
                    totals[n] += value
        return _normalize(totals)

    pair_recent = centrality("pair_counts", 2)
    pair_all = centrality("pair_all_counts", 2)
    triple_recent = centrality("triple_counts", 3)
    triple_all = centrality("triple_all_counts", 3)

    mode_key = (mode or "balanced").strip().lower()
    grade_key = str(grade or "일반").strip()
    weights: Dict[int, float] = {}
    for number in range(1, 46):
        short_flow = 0.62 * normalized["f10"][number] + 0.38 * normalized["f30"][number]
        stable_flow = 0.52 * normalized["f100"][number] + 0.28 * normalized["f300"][number] + 0.20 * normalized["all"][number]
        recent_link = 0.72 * pair_recent[number] + 0.28 * triple_recent[number]
        long_link = 0.74 * pair_all[number] + 0.26 * triple_all[number]
        rebound = normalized["gap"][number]
        trend = normalized["momentum"][number]

        if grade_key == "1등":
            combined = (0.17 * normalized["base"][number] + 0.12 * short_flow +
                        0.27 * stable_flow + 0.08 * trend + 0.08 * rebound +
                        0.10 * recent_link + 0.18 * long_link)
        elif grade_key == "2등":
            combined = (0.20 * normalized["base"][number] + 0.23 * short_flow +
                        0.22 * stable_flow + 0.11 * trend + 0.09 * rebound +
                        0.10 * recent_link + 0.05 * long_link)
        else:
            combined = (0.20 * normalized["base"][number] + 0.18 * short_flow +
                        0.20 * stable_flow + 0.08 * trend + 0.24 * rebound +
                        0.06 * recent_link + 0.04 * long_link)

        if mode_key in {"hot", "강세", "aggressive"}:
            combined = 0.72 * combined + 0.20 * short_flow + 0.08 * trend
        elif mode_key in {"cold", "반등", "rebound"}:
            combined = 0.65 * combined + 0.29 * rebound + 0.06 * stable_flow

        weights[number] = max(0.01, 16.0 + 84.0 * max(0.0, min(1.0, combined)))
    return weights



def build_number_weights_profile(cache: Dict[str, Any], profile: Dict[str, Any], mode: str = "balanced", grade: str = "일반") -> Dict[int, float]:
    """Build number weights from an AI LAB profile without changing live defaults."""
    required = {"recent_10", "recent_30", "recent_100", "full_history", "momentum", "overdue", "pair", "combo_balance"}
    clean = {str(k): float(v) for k, v in (profile or {}).items() if str(k) in required}
    if set(clean) != required or not 0.99 <= sum(clean.values()) <= 1.01:
        raise ValueError("AI LAB 가중치 프로필 형식이 올바르지 않습니다.")
    f10 = _normalize({n: _value(cache.get("frequency10", {}), n) for n in range(1, 46)})
    f30 = _normalize({n: _value(cache.get("frequency30", {}), n) for n in range(1, 46)})
    f100 = _normalize({n: _value(cache.get("frequency100", {}), n) for n in range(1, 46)})
    fall = _normalize({n: _value(cache.get("frequency_all", {}), n) for n in range(1, 46)})
    momentum = _normalize({n: _value(cache.get("momentum", {}), n) for n in range(1, 46)})
    overdue = _normalize({n: min(30.0, _value(cache.get("gap", {}), n)) for n in range(1, 46)})
    pairs = cache.get("pair_counts", {})
    pair_raw = {}
    for n in range(1, 46):
        pair_raw[n] = sum(float(pairs.get(f"{min(n,m)}-{max(n,m)}", 0) or 0) for m in range(1,46) if m != n)
    pair_norm = _normalize(pair_raw)
    base = build_number_weights(cache, mode=mode, grade=grade)
    base_norm = _normalize(base)
    out = {}
    for n in range(1,46):
        combined = (
            clean["recent_10"] * f10[n] + clean["recent_30"] * f30[n] +
            clean["recent_100"] * f100[n] + clean["full_history"] * fall[n] +
            clean["momentum"] * momentum[n] + clean["overdue"] * overdue[n] +
            clean["pair"] * pair_norm[n] + clean["combo_balance"] * base_norm[n]
        )
        # Preserve the activated AI LAB profile, then blend a small amount of
        # the grade strategy so activated profiles still retain grade identity.
        grade_base = build_number_weights(cache, mode=mode, grade=grade)
        grade_norm = _normalize(grade_base)
        combined = 0.88 * combined + 0.12 * grade_norm[n]
        score = 16.0 + 84.0 * max(0.0, min(1.0, combined))
        out[n] = max(0.01, score)
    return out

def pair_strength(numbers: Sequence[int], cache: Dict[str, Any]) -> float:
    pairs = cache.get("pair_counts", {})
    values = [float(pairs.get(f"{a}-{b}", 0) or 0) for a, b in combinations(sorted(numbers), 2)]
    return sum(values) / max(1, len(values))


def triple_strength(numbers: Sequence[int], cache: Dict[str, Any]) -> float:
    triples = cache.get("triple_counts", {})
    return sum(float(triples.get("-".join(map(str, triple)), 0) or 0) for triple in combinations(sorted(numbers), 3))


def _gaussian(value: float, mean: float, spread: float) -> float:
    spread = max(0.1, spread)
    return math.exp(-((value - mean) ** 2) / (2.0 * spread ** 2))


def score_combo(
    numbers: Sequence[int],
    cache: Dict[str, Any],
    weights: Dict[int, float],
    signature_fn: Callable[[Sequence[int]], Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    """Score a six-number combination without database access."""
    sig = signature_fn(numbers)
    pattern = cache.get("pattern", {})

    base_score = sum(weights[number] for number in numbers) / 6.0
    sum_mean = float(pattern.get("sum_mean", 138.0) or 138.0)
    sum_sd = max(10.0, float(pattern.get("sum_sd", 25.0) or 25.0))
    odd_mean = float(pattern.get("odd_mean", 3.0) or 3.0)
    ac_mean = float(pattern.get("ac_mean", 7.0) or 7.0)
    consecutive_mean = float(pattern.get("consecutive_mean", 0.8) or 0.8)

    pair = pair_strength(numbers, cache)
    triple = triple_strength(numbers, cache)
    score = base_score
    score += 13.0 * _gaussian(float(sig["sum"]), sum_mean, sum_sd)
    score += 7.0 * _gaussian(float(sig["odd"]), odd_mean, 1.15)
    score += 5.5 * _gaussian(float(sig["ac"]), ac_mean, 2.2)
    score += 2.0 * _gaussian(float(sig["consecutive"]), consecutive_mean, 1.0)
    score += min(7.0, pair * 0.85)
    score += min(3.0, triple * 0.55)

    zones = list(sig.get("zones", [0, 0, 0]))
    if max(zones, default=6) <= 3:
        score += 4.5
    elif max(zones, default=6) >= 5:
        score -= 5.0
    if int(sig.get("max_end_dup", 6)) <= 2:
        score += 3.0
    if int(sig.get("end_types", 0)) >= 5:
        score += 1.3
    if int(sig.get("spread", 0)) >= 25:
        score += 2.0

    latest_sets = [set(item) for item in cache.get("latest_numbers", []) if isinstance(item, (list, tuple, set))]
    selected = set(numbers)
    max_overlap = max((len(selected & recent) for recent in latest_sets), default=0)
    if max_overlap >= 4:
        score -= 13.0
    elif max_overlap == 3:
        score -= 3.5

    # Penalize a combination dominated by a single role/range.
    decades = Counter((number - 1) // 10 for number in numbers)
    if max(decades.values(), default=0) >= 4:
        score -= 4.5

    detail = dict(sig)
    detail.update({
        "pair_strength": round(pair, 2),
        "triple_strength": round(triple, 2),
        "max_recent_overlap": max_overlap,
        "score_engine_version": SCORE_ENGINE_VERSION,
        "base_number_score": round(base_score, 3),
    })
    return round(score, 4), detail
