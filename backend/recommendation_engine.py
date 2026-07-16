from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import random
import sqlite3
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .ai.cache_engine import get_analysis_cache as _persistent_analysis_cache
from .ai.scheduler import ensure_scheduler_started as _ensure_ai_scheduler_started
from .ai.member_history import load_member_profile as _load_member_profile, member_structure_adjustment as _member_structure_adjustment
from .ai.score_engine import (
    SCORE_ENGINE_VERSION,
    build_number_weights as _build_number_weights,
    build_number_weights_profile as _build_number_weights_profile,
    pair_strength as _score_pair_strength,
    score_combo as _score_combo_v13,
    triple_strength as _score_triple_strength,
)

ENGINE_VERSION = "BBLOTTO_AI_RECOMMENDATION_RC6_D8"
_ensure_ai_scheduler_started()
_CACHE_LOCK = threading.RLock()
_MEMORY_CACHE: Dict[str, Any] = {}
_SYNC_LOCK = threading.Lock()


def _resolve_primary_db_path() -> Path:
    db_dir = os.getenv("BBLOTTO_DB_DIR", "").strip()
    if db_dir:
        return Path(db_dir).expanduser().resolve() / "bblotto_v34.db"
    return (Path(__file__).resolve().parents[1] / "database" / "bblotto_v34.db").resolve()


DB_PATH = _resolve_primary_db_path()


def _conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or _resolve_primary_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), timeout=20, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    return c


def _parse_nums(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        text = str(value).replace("[", " ").replace("]", " ").replace(",", " ")
        raw = text.split()
    out: List[int] = []
    for item in raw:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 45 and n not in out:
            out.append(n)
    return sorted(out)


def _load_draws() -> List[Dict[str, Any]]:
    path = _resolve_primary_db_path()
    if not path.exists():
        return []
    with _conn(path) as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='draws'").fetchone()
        if not exists:
            return []
        rows = c.execute("SELECT round_no, draw_date, numbers, bonus FROM draws ORDER BY round_no").fetchall()
    draws: List[Dict[str, Any]] = []
    for r in rows:
        nums = _parse_nums(r["numbers"])
        if len(nums) == 6:
            draws.append({"round": int(r["round_no"]), "date": r["draw_date"] or "", "numbers": nums, "bonus": int(r["bonus"] or 0)})
    return draws


def _ac(nums: Sequence[int]) -> int:
    return len({b - a for a, b in combinations(sorted(nums), 2)}) - 5


def _zones(nums: Sequence[int]) -> List[int]:
    return [sum(1 for n in nums if n <= 15), sum(1 for n in nums if 16 <= n <= 30), sum(1 for n in nums if n >= 31)]


def _consecutive_pairs(nums: Sequence[int]) -> int:
    s = set(nums)
    return sum(1 for n in nums if n + 1 in s)


def _max_end_dup(nums: Sequence[int]) -> int:
    return max(Counter(n % 10 for n in nums).values(), default=0)


def _sig(nums: Sequence[int]) -> Dict[str, Any]:
    nums = sorted(nums)
    odd = sum(n % 2 for n in nums)
    return {
        "sum": sum(nums), "odd": odd, "even": 6 - odd, "zones": _zones(nums),
        "ac": _ac(nums), "consecutive": _consecutive_pairs(nums),
        "end_types": len({n % 10 for n in nums}), "max_end_dup": _max_end_dup(nums),
        "spread": nums[-1] - nums[0], "low_high": [sum(n <= 22 for n in nums), sum(n >= 23 for n in nums)],
    }


def _norm_map(values: Dict[int, float]) -> Dict[int, float]:
    if not values:
        return {n: 0.5 for n in range(1, 46)}
    lo, hi = min(values.values()), max(values.values())
    if math.isclose(lo, hi):
        return {n: 0.5 for n in range(1, 46)}
    return {n: (values.get(n, lo) - lo) / (hi - lo) for n in range(1, 46)}


def _frequency(draws: Sequence[Dict[str, Any]], window: int) -> Counter:
    subset = draws[-window:] if window and len(draws) > window else draws
    return Counter(n for d in subset for n in d["numbers"])


def _gaps(draws: Sequence[Dict[str, Any]]) -> Dict[int, int]:
    latest = len(draws)
    last = {n: -1 for n in range(1, 46)}
    for idx, d in enumerate(draws):
        for n in d["numbers"]:
            last[n] = idx
    return {n: latest if last[n] < 0 else latest - 1 - last[n] for n in range(1, 46)}


def _build_cache(draws_override: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Build an analysis cache from a supplied historical prefix or the live DB.

    ``draws_override`` is used by the backtest engine so a target round can
    never see future winning numbers. Live recommendation calls remain
    unchanged and continue to use the persistent cache.
    """
    started = time.perf_counter()
    draws = list(draws_override) if draws_override is not None else _load_draws()
    latest_round = draws[-1]["round"] if draws else 0
    windows = (10, 30, 50, 100, 300)
    freqs = {w: _frequency(draws, w) for w in windows}
    all_freq = _frequency(draws, 0)
    gaps = _gaps(draws)

    pair_all: Counter = Counter()
    pair_recent: Counter = Counter()
    triple_recent: Counter = Counter()
    for i, d in enumerate(draws):
        for p in combinations(d["numbers"], 2):
            pair_all[p] += 1
        if i >= max(0, len(draws) - 100):
            for p in combinations(d["numbers"], 2):
                pair_recent[p] += 1
            for t in combinations(d["numbers"], 3):
                triple_recent[t] += 1

    n10 = _norm_map({n: freqs[10][n] / 10 for n in range(1, 46)})
    n30 = _norm_map({n: freqs[30][n] / 30 for n in range(1, 46)})
    n100 = _norm_map({n: freqs[100][n] / 100 for n in range(1, 46)})
    n300 = _norm_map({n: freqs[300][n] / max(1, min(300, len(draws))) for n in range(1, 46)})
    nall = _norm_map({n: all_freq[n] / max(1, len(draws)) for n in range(1, 46)})
    ngap = _norm_map({n: float(gaps[n]) for n in range(1, 46)})

    score_map: Dict[int, float] = {}
    momentum: Dict[int, float] = {}
    for n in range(1, 46):
        mom = (n10[n] - n100[n]) * 0.65 + (n30[n] - n300[n]) * 0.35
        momentum[n] = mom
        score_map[n] = (
            0.22 * n10[n] + 0.20 * n30[n] + 0.18 * n100[n] + 0.10 * n300[n]
            + 0.08 * nall[n] + 0.14 * ngap[n] + 0.08 * max(0.0, min(1.0, 0.5 + mom))
        )

    pattern_sigs = [_sig(d["numbers"]) for d in draws]
    recent_patterns = pattern_sigs[-200:] or pattern_sigs
    # Empirical structure distributions are used as a smoothed prior.  This
    # avoids rewarding only individual-number popularity and gives the final
    # ranker a historical reference for whole-combination shape.
    structure_distributions = {
        "odd": dict(Counter(int(x["odd"]) for x in recent_patterns)),
        "ac": dict(Counter(int(x["ac"]) for x in recent_patterns)),
        "consecutive": dict(Counter(int(x["consecutive"]) for x in recent_patterns)),
        "end_types": dict(Counter(int(x["end_types"]) for x in recent_patterns)),
        "zones": dict(Counter("-".join(map(str, x["zones"])) for x in recent_patterns)),
    }
    def avg(key: str, default: float) -> float:
        vals = [float(x[key]) for x in recent_patterns]
        return sum(vals) / len(vals) if vals else default
    sums = [x["sum"] for x in recent_patterns]
    sum_mean = sum(sums) / len(sums) if sums else 138.0
    sum_sd = math.sqrt(sum((x - sum_mean) ** 2 for x in sums) / len(sums)) if sums else 25.0

    ranked = sorted(range(1, 46), key=lambda n: (-score_map[n], n))
    overdue = sorted(range(1, 46), key=lambda n: (-gaps[n], n))
    cold = sorted(range(1, 46), key=lambda n: (freqs[30][n], freqs[100][n], n))
    latest_numbers = [d["numbers"] for d in draws[-12:]]

    return {
        "engine_version": ENGINE_VERSION,
        "cache_storage": "memory+db-source",
        "analysis_confirm": f"1회차부터 {latest_round}회차까지 {len(draws)}개 회차 분석",
        "draw_count": len(draws), "actual_count": len(draws), "expected_count": latest_round,
        "round_range": [draws[0]["round"], latest_round] if draws else [0, 0],
        "latest_round": latest_round, "target_round": latest_round + 1 if latest_round else 1,
        "is_full_history": bool(draws and draws[0]["round"] == 1 and len(draws) == latest_round),
        "missing_rounds_count": max(0, latest_round - len(draws)), "missing_rounds_sample": [],
        "frequency10": {str(n): freqs[10][n] for n in range(1, 46)},
        "frequency30": {str(n): freqs[30][n] for n in range(1, 46)},
        "frequency50": {str(n): freqs[50][n] for n in range(1, 46)},
        "frequency100": {str(n): freqs[100][n] for n in range(1, 46)},
        "frequency300": {str(n): freqs[300][n] for n in range(1, 46)},
        "frequency_all": {str(n): all_freq[n] for n in range(1, 46)},
        "gap": {str(n): gaps[n] for n in range(1, 46)},
        "score_map": {str(n): round(score_map[n] * 100, 4) for n in range(1, 46)},
        "momentum": {str(n): round(momentum[n], 5) for n in range(1, 46)},
        "hot": ranked[:15], "cold": cold[:15], "overdue": overdue[:15],
        "pair_top": [[list(p), c] for p, c in pair_all.most_common(100)],
        "pair_recent_top": [[list(p), c] for p, c in pair_recent.most_common(100)],
        "triple_recent_top": [[list(t), c] for t, c in triple_recent.most_common(50)],
        "pair_counts": {f"{a}-{b}": c for (a, b), c in pair_recent.items()},
        "triple_counts": {"-".join(map(str, t)): c for t, c in triple_recent.items()},
        "pattern": {
            "sum_mean": round(sum_mean, 2), "sum_sd": round(sum_sd, 2),
            "odd_mean": round(avg("odd", 3), 2), "ac_mean": round(avg("ac", 7), 2),
            "consecutive_mean": round(avg("consecutive", 0.8), 2),
            "sample_count": len(recent_patterns),
            "distributions": structure_distributions,
        },
        "latest_numbers": latest_numbers,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "build_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _cache_key() -> Tuple[str, int, int]:
    path = _resolve_primary_db_path()
    try:
        st = path.stat()
        return str(path), int(st.st_mtime_ns), int(st.st_size)
    except FileNotFoundError:
        return str(path), 0, 0


def get_analysis_cache(force: bool = False, target_round: Optional[int] = None) -> Dict[str, Any]:
    """Return the persistent full-history cache managed by AI PATCH 01."""
    return _persistent_analysis_cache(
        force=force,
        target_round=target_round,
        recommendation_engine_version=ENGINE_VERSION,
    )


def latest_stats(limit: int = 0) -> Dict[str, Any]:
    c = get_analysis_cache(False)
    if limit:
        c = dict(c)
        c["hot"] = c.get("hot", [])[:limit]
        c["cold"] = c.get("cold", [])[:limit]
        c["overdue"] = c.get("overdue", [])[:limit]
    return c


def _mode_weights(cache: Dict[str, Any], mode: str, grade: str) -> Dict[int, float]:
    return _build_number_weights(cache, mode=mode, grade=grade)

def _weighted_sample(rng: random.Random, weights: Dict[int, float], k: int, excluded: set[int]) -> List[int]:
    pool = [n for n in range(1, 46) if n not in excluded]
    result: List[int] = []
    for _ in range(k):
        total = sum(weights[n] for n in pool)
        pick = rng.random() * total
        acc = 0.0
        chosen = pool[-1]
        for n in pool:
            acc += weights[n]
            if acc >= pick:
                chosen = n
                break
        result.append(chosen)
        pool.remove(chosen)
    return sorted(result)


def _pair_strength(nums: Sequence[int], cache: Dict[str, Any]) -> float:
    return _score_pair_strength(nums, cache)


def _triple_strength(nums: Sequence[int], cache: Dict[str, Any]) -> float:
    return _score_triple_strength(nums, cache)


def _combo_score(nums: Sequence[int], cache: Dict[str, Any], weights: Dict[int, float]) -> Tuple[float, Dict[str, Any]]:
    return _score_combo_v13(nums, cache, weights, _sig)

def _valid(nums: Sequence[int]) -> bool:
    if len(set(nums)) != 6: return False
    s = _sig(nums)
    return 75 <= s["sum"] <= 210 and 1 <= s["odd"] <= 5 and max(s["zones"]) <= 4 and s["max_end_dup"] <= 3 and s["ac"] >= 4 and s["consecutive"] <= 3


def _number_evidence(n: int, cache: Dict[str, Any], weights: Optional[Dict[int, float]] = None) -> Dict[str, Any]:
    """Return the exact inputs used when number *n* was ranked.

    The explanation layer consumes this record verbatim.  Keep values numeric
    so the UI never has to invent a reason after generation.
    """
    hot_rank = {x: i + 1 for i, x in enumerate(cache.get("hot", []))}
    cold_rank = {x: i + 1 for i, x in enumerate(cache.get("cold", []))}
    overdue_rank = {x: i + 1 for i, x in enumerate(cache.get("overdue", []))}
    f10 = int(cache.get("frequency10", {}).get(str(n), 0) or 0)
    f30 = int(cache.get("frequency30", {}).get(str(n), 0) or 0)
    f100 = int(cache.get("frequency100", {}).get(str(n), 0) or 0)
    gap = int(cache.get("gap", {}).get(str(n), 0) or 0)
    momentum = float(cache.get("momentum", {}).get(str(n), 0) or 0)
    base_score = float(cache.get("score_map", {}).get(str(n), 0) or 0)
    final_weight = float((weights or {}).get(n, base_score) or 0)

    factors: List[Dict[str, Any]] = []
    if hot_rank.get(n, 999) <= 15:
        factors.append({"code": "hot", "label": "최근 강세", "value": hot_rank[n], "text": f"HOT {hot_rank[n]}위"})
    if momentum > 0.04:
        factors.append({"code": "momentum", "label": "상승 모멘텀", "value": round(momentum, 4), "text": f"모멘텀 +{momentum:.3f}"})
    if overdue_rank.get(n, 999) <= 15 or gap >= 7:
        factors.append({"code": "overdue", "label": "미출현 보강", "value": gap, "text": f"{gap}회 미출현"})
    if cold_rank.get(n, 999) <= 12:
        factors.append({"code": "cold", "label": "저빈도 반등", "value": cold_rank[n], "text": f"COLD {cold_rank[n]}위"})
    if not factors:
        factors.append({"code": "balance", "label": "누적 균형", "value": round(base_score, 3), "text": f"전체 점수 {base_score:.1f}"})

    primary = factors[0]["code"]
    role = {"hot": "강세수", "momentum": "상승수", "overdue": "반등수", "cold": "저빈도 보강수"}.get(primary, "균형수")
    reason = " · ".join(f["text"] for f in factors[:3])
    return {
        "number": n, "role": role, "reason": reason, "factors": factors,
        "freq10": f10, "freq30": f30, "freq100": f100, "gap": gap,
        "momentum": round(momentum, 5), "base_score": round(base_score, 4),
        "selection_score": round(final_weight, 4),
        "hot_rank": hot_rank.get(n), "cold_rank": cold_rank.get(n),
        "overdue_rank": overdue_rank.get(n),
    }


def _combo_evidence(nums: Sequence[int], detail: Dict[str, Any], cache: Dict[str, Any], weights: Dict[int, float]) -> Dict[str, Any]:
    """Persist the exact combination-level facts used by the explanation engine."""
    pair_map = cache.get("pair_counts", {}) or {}
    pairs: List[Dict[str, Any]] = []
    ordered = sorted(int(n) for n in nums)
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            raw = pair_map.get(f"{left}-{right}", pair_map.get(f"{right}-{left}", 0))
            try:
                value = float(raw or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                pairs.append({"numbers": [left, right], "strength": round(value, 3)})
    pairs.sort(key=lambda item: (-item["strength"], item["numbers"]))

    number_scores = sorted(
        ({"number": int(n), "selection_score": round(float(weights.get(int(n), 0) or 0), 4)} for n in ordered),
        key=lambda item: (-item["selection_score"], item["number"]),
    )
    return {
        "top_number_scores": number_scores[:3],
        "pair_highlights": pairs[:3],
        "constraints": {
            "sum_in_range": 75 <= int(detail.get("sum", sum(ordered))) <= 210,
            "odd_even_balanced": 1 <= int(detail.get("odd", sum(n % 2 for n in ordered))) <= 5,
            "zone_limit_passed": max(detail.get("zones", [0, 0, 0])) <= 4,
            "end_digit_limit_passed": int(detail.get("max_end_dup", 0)) <= 3,
            "ac_passed": int(detail.get("ac", 0)) >= 4,
            "consecutive_limit_passed": int(detail.get("consecutive", 0)) <= 3,
        },
    }



def _strategy_fit(combo: Sequence[int], detail: Dict[str, Any], cache: Dict[str, Any], strategy: str, member_profile: Optional[Dict[str, Any]] = None) -> Tuple[float, Dict[str, float]]:
    """Return a transparent strategy bonus for the candidate combination.

    Strategies do not bypass the common quality validator. They only change
    the ordering among already valid candidates so the final portfolio is not
    dominated by one style.
    """
    selected = set(int(n) for n in combo)
    hot = set(int(n) for n in (cache.get("hot", []) or [])[:15])
    overdue = set(int(n) for n in (cache.get("overdue", []) or [])[:15])
    hot_count = len(selected & hot)
    overdue_count = len(selected & overdue)
    pair = float(detail.get("pair_strength", 0) or 0)
    zones = list(detail.get("zones", [0, 0, 0]))
    zone_balance = 1.0 - (max(zones) - min(zones)) / 6.0 if zones else 0.0
    end_types = int(detail.get("end_types", 0) or 0)
    momentum_map = cache.get("momentum", {}) or {}
    momentum = sum(float(momentum_map.get(str(n), 0) or 0) for n in selected) / 6.0

    components: Dict[str, float] = {}
    if strategy == "최근 흐름형":
        components["hot_bonus"] = min(8.0, hot_count * 2.0)
        components["momentum_bonus"] = max(-2.0, min(5.0, momentum * 18.0))
    elif strategy == "반등 혼합형":
        components["overdue_bonus"] = min(8.0, overdue_count * 2.0)
        components["balance_bonus"] = max(0.0, zone_balance * 3.0)
    elif strategy == "동반출현형":
        components["pair_bonus"] = min(9.0, pair * 1.8)
        components["end_spread_bonus"] = min(2.5, max(0, end_types - 3) * 0.8)
    else:  # 균형형
        components["zone_balance_bonus"] = max(0.0, zone_balance * 5.0)
        components["sum_center_bonus"] = max(0.0, 4.0 - abs(float(detail.get("sum", 138)) - 138.0) / 18.0)
        components["end_spread_bonus"] = min(2.5, max(0, end_types - 3) * 0.8)
    if member_profile and member_profile.get("enabled"):
        history_bonus = float((member_profile.get("strategy_adjustments") or {}).get(strategy, 0) or 0)
        structure_bonus = _member_structure_adjustment(detail, member_profile)
        components["member_strategy_adjustment"] = history_bonus
        components["member_structure_adjustment"] = structure_bonus
    return round(sum(components.values()), 4), {k: round(v, 4) for k, v in components.items()}


def _portfolio_adjustment(
    combo: Sequence[int],
    selected: Sequence[Sequence[int]],
    usage: Counter,
    target: int,
) -> Tuple[float, Dict[str, float]]:
    """Score portfolio diversity without weakening combination validity."""
    overlap = max((len(set(combo) & set(prev)) for prev in selected), default=0)
    soft_cap = max(2, math.ceil(target * 6 / 45) + 1)
    repeat_excess = sum(max(0, usage[int(n)] + 1 - soft_cap) for n in combo)
    repeat_penalty = repeat_excess * 4.2
    overlap_penalty = {0: 0.0, 1: 0.0, 2: 0.6, 3: 4.5, 4: 11.0}.get(overlap, 18.0)

    # Reward numbers not yet represented and underrepresented zones.
    new_number_bonus = sum(1 for n in combo if usage[int(n)] == 0) * 0.7
    existing_zone_usage = [0, 0, 0]
    for n, count in usage.items():
        zone = 0 if n <= 15 else 1 if n <= 30 else 2
        existing_zone_usage[zone] += int(count)
    zone_bonus = 0.0
    if selected:
        min_zone = min(existing_zone_usage)
        for n in combo:
            zone = 0 if n <= 15 else 1 if n <= 30 else 2
            if existing_zone_usage[zone] == min_zone:
                zone_bonus += 0.35

    adjustment = new_number_bonus + zone_bonus - repeat_penalty - overlap_penalty
    return round(adjustment, 4), {
        "new_number_bonus": round(new_number_bonus, 4),
        "zone_coverage_bonus": round(zone_bonus, 4),
        "number_repeat_penalty": round(repeat_penalty, 4),
        "combo_overlap_penalty": round(overlap_penalty, 4),
        "max_previous_overlap": float(overlap),
        "usage_soft_cap": float(soft_cap),
    }

def make_premium_combos(count: int = 10, fixed: Any = "", excluded: Any = "", mode: str = "balanced", member_grade: str = "일반", member_id: Optional[int] = None, *, cache_override: Optional[Dict[str, Any]] = None, deterministic_seed: Optional[str] = None, lab_weight_profile: Optional[Dict[str, Any]] = None):
    started = time.perf_counter()
    target = max(1, min(50, int(count or 10)))
    fixed_nums = _parse_nums(fixed)
    excluded_nums = set(_parse_nums(excluded)) - set(fixed_nums)
    if len(fixed_nums) > 6:
        raise ValueError("고정수는 최대 6개까지 입력할 수 있습니다.")
    if len(set(range(1, 46)) - excluded_nums) < 6:
        raise ValueError("제외수가 너무 많습니다.")

    cache = cache_override if cache_override is not None else get_analysis_cache(False)
    weights = _build_number_weights_profile(cache, lab_weight_profile, mode=mode, grade=member_grade) if lab_weight_profile else _mode_weights(cache, mode, member_grade)
    member_profile = _load_member_profile(_resolve_primary_db_path(), member_id) if member_id and cache_override is None else {"enabled": False, "member_id": int(member_id or 0), "strategy_adjustments": {}}
    seed_basis = deterministic_seed if deterministic_seed is not None else str(time.time_ns())
    seed_text = f"{seed_basis}|{member_id}|{member_grade}|{mode}|{fixed_nums}|{sorted(excluded_nums)}|{cache.get('latest_round')}"
    rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16))

    candidate_target = min(2000, max(240, target * 60))
    pool: Dict[Tuple[int, ...], Tuple[float, Dict[str, Any]]] = {}
    attempts = 0
    while len(pool) < candidate_target and attempts < candidate_target * 5:
        attempts += 1
        remain = 6 - len(fixed_nums)
        picked = _weighted_sample(rng, weights, remain, excluded_nums | set(fixed_nums))
        combo = tuple(sorted(fixed_nums + picked))
        if not _valid(combo):
            continue
        score, detail = _combo_score(combo, cache, weights)
        pool[combo] = (score, detail)

    ranked = sorted(pool.items(), key=lambda x: (-x[1][0], x[0]))
    selected: List[List[int]] = []
    selected_details: List[Dict[str, Any]] = []
    usage: Counter = Counter()
    strategy_cycle = ["균형형", "최근 흐름형", "반등 혼합형", "동반출현형"]
    candidate_rank = {combo: index + 1 for index, (combo, _) in enumerate(ranked)}
    available = {combo: (score, detail) for combo, (score, detail) in ranked}

    # Pick each combination against the portfolio already selected. This avoids
    # simply taking the highest six-number scores repeatedly.
    while len(selected) < target and available:
        strategy = strategy_cycle[len(selected) % len(strategy_cycle)]
        best = None
        for combo, (base_score, detail) in list(available.items()):
            overlap = max((len(set(combo) & set(prev)) for prev in selected), default=0)
            # For a normal 10-combination portfolio, four or more shared
            # numbers makes tickets too similar. Larger exports retain a
            # slightly looser limit so generation cannot deadlock.
            overlap_limit = 4 if target <= 20 else 5
            if overlap >= overlap_limit:
                continue
            strategy_bonus, strategy_components = _strategy_fit(combo, detail, cache, strategy, member_profile)
            portfolio_adjustment, portfolio_components = _portfolio_adjustment(combo, selected, usage, target)
            final_score = float(base_score) + strategy_bonus + portfolio_adjustment
            candidate = (final_score, float(base_score), tuple(combo), detail, strategy_bonus, strategy_components, portfolio_adjustment, portfolio_components)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
        if best is None:
            break

        final_score, base_score, combo, detail, strategy_bonus, strategy_components, portfolio_adjustment, portfolio_components = best
        available.pop(combo, None)
        selected.append(list(combo))
        usage.update(combo)

        hot_count = len(set(combo) & set(cache.get("hot", [])[:12]))
        overdue_count = len(set(combo) & set(cache.get("overdue", [])[:12]))
        pair_strength = float(detail.get("pair_strength", 0) or 0)
        evidence = [_number_evidence(n, cache, weights) for n in combo]

        alternative = None
        for alt_combo, (alt_score, alt_detail) in ranked:
            if alt_combo == combo:
                continue
            common = set(combo) & set(alt_combo)
            if len(common) != 5:
                continue
            removed = sorted(set(combo) - set(alt_combo))
            added = sorted(set(alt_combo) - set(combo))
            alternative = {
                "numbers": list(alt_combo),
                "base_score": round(float(alt_score), 2),
                "chosen_base_score": round(float(base_score), 2),
                "score_advantage": round(float(base_score) - float(alt_score), 2),
                "kept_number": removed[0] if removed else None,
                "replaced_candidate": added[0] if added else None,
                "common_count": len(common),
                "sum": alt_detail.get("sum"),
                "ac": alt_detail.get("ac"),
                "pair_strength": alt_detail.get("pair_strength"),
            }
            break

        reasons = [
            f"{strategy} 기준으로 번호 점수와 조합 구조를 함께 재평가",
            f"홀짝 {detail['odd']}:{detail['even']} · 구간 {detail['zones'][0]}-{detail['zones'][1]}-{detail['zones'][2]} · 합계 {detail['sum']}",
            f"AC {detail['ac']} · 동반출현 {pair_strength:.2f} · 최근 당첨조합 최대 중복 {detail['max_recent_overlap']}개",
        ]
        selected_details.append({
            "numbers": list(combo), "score": round(final_score, 2), "base_score": round(base_score, 2),
            "strategy_bonus": round(strategy_bonus, 2), "portfolio_adjustment": round(portfolio_adjustment, 2),
            "diversity_penalty": round(portfolio_components["number_repeat_penalty"], 2),
            "overlap_penalty": round(portfolio_components["combo_overlap_penalty"], 2),
            "max_previous_overlap": int(portfolio_components["max_previous_overlap"]),
            "selection_rank": len(selected), "candidate_rank": candidate_rank.get(combo),
            "engine_version": ENGINE_VERSION, "engine": ENGINE_VERSION,
            "type": strategy, "strategy": strategy, "portfolio_type": strategy,
            "number_evidence": evidence, "alternative_candidate": alternative,
            "combo_evidence": _combo_evidence(combo, detail, cache, weights),
            "member_adaptation": {
                "enabled": bool(member_profile.get("enabled")),
                "evaluated_runs": int(member_profile.get("evaluated_runs", 0) or 0),
                "confidence": float(member_profile.get("confidence", 0) or 0),
                "best_strategy": member_profile.get("best_strategy") or "균형형",
                "strategy_adjustment": round(float(strategy_components.get("member_strategy_adjustment", 0) or 0), 4),
                "structure_adjustment": round(float(strategy_components.get("member_structure_adjustment", 0) or 0), 4),
            },
            "score_components": {
                "base_combo_score": round(base_score, 4),
                "strategy_bonus": round(strategy_bonus, 4),
                "portfolio_adjustment": round(portfolio_adjustment, 4),
                "strategy": strategy_components,
                "portfolio": portfolio_components,
                "hot_count": hot_count, "overdue_count": overdue_count,
            },
            "selection_trace": {
                "candidate_base_score": round(base_score, 2),
                "portfolio_score": round(final_score, 2),
                "strategy_bonus": round(strategy_bonus, 2),
                "number_repeat_penalty": round(portfolio_components["number_repeat_penalty"], 2),
                "combo_overlap_penalty": round(portfolio_components["combo_overlap_penalty"], 2),
                "max_previous_overlap": int(portfolio_components["max_previous_overlap"]),
                "candidate_rank": candidate_rank.get(combo),
                "strategy": strategy,
            },
            "reasons": reasons, "reason": " / ".join(reasons), **detail,
        })

    # 드문 조건에서 후보가 부족하면 일반 후보와 같은 품질 기준을 유지해 보완 생성합니다.
    # 무한 반복을 막기 위해 시도 횟수를 제한하고, 검증을 통과한 조합만 추가합니다.
    fallback_attempts = 0
    fallback_attempt_limit = max(300, (target - len(selected)) * 250)
    while len(selected) < target and fallback_attempts < fallback_attempt_limit:
        fallback_attempts += 1
        combo = sorted(
            fixed_nums
            + _weighted_sample(
                rng,
                weights,
                6 - len(fixed_nums),
                excluded_nums | set(fixed_nums),
            )
        )

        # 일반 후보와 동일하게 조합 품질, 고정수, 제외수, 중복을 다시 검증합니다.
        if not _valid(combo):
            continue
        if any(n not in combo for n in fixed_nums):
            continue
        if any(n in excluded_nums for n in combo):
            continue
        if combo in selected:
            continue

        overlap = max((len(set(combo) & set(prev)) for prev in selected), default=0)
        overlap_limit = 4 if target <= 20 else 5
        if overlap >= overlap_limit:
            continue

        base_score, detail = _combo_score(combo, cache, weights)
        diversity_penalty = sum(
            max(0, usage[n] - max(1, target // 5)) for n in combo
        ) * 3.2
        overlap_penalty = max(0, overlap - 2) * 4.5
        adjusted = base_score - diversity_penalty - overlap_penalty

        selected.append(combo)
        usage.update(combo)
        evidence = [_number_evidence(n, cache, weights) for n in combo]
        reasons = [
            "일반 후보와 동일한 검증 기준을 통과한 보완 균형형",
            f"홀짝 {detail['odd']}:{detail['even']} · 구간 {detail['zones'][0]}-{detail['zones'][1]}-{detail['zones'][2]} · 합계 {detail['sum']}",
            f"AC {detail['ac']} · 끝수 {detail['end_types']}종 · 이전 조합 최대 중복 {overlap}개",
        ]
        selected_details.append({
            "numbers": combo,
            "score": round(adjusted, 2),
            "base_score": round(base_score, 2),
            "diversity_penalty": round(diversity_penalty, 2),
            "overlap_penalty": round(overlap_penalty, 2),
            "max_previous_overlap": overlap,
            "selection_rank": len(selected),
            "engine_version": ENGINE_VERSION,
            "engine": ENGINE_VERSION,
            "type": "보완 균형형",
            "strategy": "보완 균형형",
            "portfolio_type": "보완 균형형",
            "number_evidence": evidence,
            "alternative_candidate": None,
            "combo_evidence": _combo_evidence(combo, detail, cache, weights),
            "selection_trace": {
                "candidate_base_score": round(base_score, 2),
                "portfolio_score": round(adjusted, 2),
                "number_repeat_penalty": round(diversity_penalty, 2),
                "combo_overlap_penalty": round(overlap_penalty, 2),
                "max_previous_overlap": overlap,
                "candidate_rank": None,
                "fallback": True,
            },
            "reasons": reasons,
            "reason": " / ".join(reasons),
            **detail,
        })

    if len(selected) < target:
        raise RuntimeError(
            f"요청한 {target}개 조합 중 {len(selected)}개만 생성되었습니다. "
            "고정수·제외수 조건을 완화한 뒤 다시 시도해주세요."
        )

    # Keep the raw score for deterministic ranking, but expose a bounded
    # 0-100 display score based on the candidate-pool distribution.  This
    # prevents internal additive scores (for example 140+) being mistaken for
    # a probability or a 100-point scale.
    raw_values = [float(item[1][0]) for item in ranked] or [1.0]
    raw_mean = sum(raw_values) / len(raw_values)
    raw_sd = math.sqrt(sum((v - raw_mean) ** 2 for v in raw_values) / max(1, len(raw_values))) or 1.0
    for item in selected_details:
        raw = float(item.get("score", 0) or 0)
        z = max(-3.0, min(3.0, (raw - raw_mean) / raw_sd))
        display_score = 50.0 + 15.0 * z
        item["raw_score"] = round(raw, 2)
        item["display_score"] = round(max(0.0, min(100.0, display_score)), 1)
        item["score_scale"] = "relative_0_100"

    elapsed = round((time.perf_counter() - started) * 1000, 2)
    stats = {
        "engine_version": ENGINE_VERSION, "engine": ENGINE_VERSION, "score_engine_version": SCORE_ENGINE_VERSION, "full_history": True,
        "draw_count": cache.get("draw_count", 0), "latest_round": cache.get("latest_round", 0),
        "analysis_confirm": cache.get("analysis_confirm"), "cache_build_ms": cache.get("build_ms", 0),
        "generation_ms": elapsed, "candidate_count": len(pool), "attempts": attempts,
        "hot": cache.get("hot", [])[:12], "cold": cache.get("cold", [])[:12], "overdue": cache.get("overdue", [])[:12],
        "unique_numbers": len(usage), "max_number_use": max(usage.values(), default=0),
        "ai_lab_profile_applied": bool(lab_weight_profile),
        "member_adaptation": {"enabled": bool(member_profile.get("enabled")), "member_id": int(member_id or 0), "evaluated_runs": int(member_profile.get("evaluated_runs", 0) or 0), "confidence": float(member_profile.get("confidence", 0) or 0), "best_strategy": member_profile.get("best_strategy") or "균형형", "safety": member_profile.get("safety") or {}},
        "methodology": ["AI-01 영구 캐시 기반", "1회차~최신 회차 전체 분석", "최근 10·30·50·100·300회 다중 가중치", "미출현 간격·모멘텀", "동반출현·트리플", "홀짝·구간·합계·AC·끝수", "조합 간 중복 억제", "전략별 포트폴리오 재평가", "번호 반복·구간 편중 동적 보정"],
    }
    return selected[:target], selected_details[:target], stats



def build_backtest_cache(draws: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Public, side-effect free cache builder for walk-forward backtests."""
    return _build_cache(draws_override=draws)


def _official_fetch(round_no: int, timeout: int = 4) -> Optional[Dict[str, Any]]:
    url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={int(round_no)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("returnValue") != "success": return None
        nums = [int(data[f"drwtNo{i}"]) for i in range(1, 7)]
        return {"round": int(data["drwNo"]), "date": data.get("drwNoDate", ""), "numbers": nums, "bonus": int(data.get("bnusNo") or 0)}
    except Exception:
        return None


def _ensure_draws_table(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS draws(round_no INTEGER PRIMARY KEY, draw_date TEXT DEFAULT '', numbers TEXT, bonus INTEGER, source TEXT DEFAULT 'manual', updated_at TEXT)")


def _save_draw(c: sqlite3.Connection, d: Dict[str, Any]) -> None:
    c.execute("INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)", (d["round"], d.get("date", ""), json.dumps(d["numbers"]), d.get("bonus", 0), "official_sync", dt.datetime.now().isoformat(timespec="seconds")))


def sync_official_history_step(max_round: Optional[int] = None, chunk_size: int = 25) -> Dict[str, Any]:
    with _SYNC_LOCK:
        cache = get_analysis_cache(False)
        start = int(cache.get("latest_round", 0)) + 1
        end = int(max_round or (start + max(1, chunk_size) - 1))
        saved = 0
        with _conn() as c:
            _ensure_draws_table(c)
            for r in range(start, end + 1):
                d = _official_fetch(r)
                if not d: break
                _save_draw(c, d); saved += 1
            c.commit()
        if saved: get_analysis_cache(True)
        return {"ok": True, "start": start, "requested_end": end, "saved": saved, "latest_round": get_analysis_cache(False).get("latest_round", 0)}


def sync_official_full_history(max_round: Optional[int] = None, stop_after_miss: int = 3) -> Dict[str, Any]:
    with _SYNC_LOCK:
        end = int(max_round or 2000)
        saved, miss = 0, 0
        with _conn() as c:
            _ensure_draws_table(c)
            existing = {int(r[0]) for r in c.execute("SELECT round_no FROM draws").fetchall()}
            for r in range(1, end + 1):
                if r in existing: continue
                d = _official_fetch(r)
                if not d:
                    miss += 1
                    if miss >= stop_after_miss: break
                    continue
                miss = 0; _save_draw(c, d); saved += 1
            c.commit()
        get_analysis_cache(True)
        cache = get_analysis_cache(False)
        return {"ok": True, "saved": saved, "latest_round": cache.get("latest_round", 0), "draw_count": cache.get("draw_count", 0), "is_full_history": cache.get("is_full_history", False)}


def rc9_audit() -> Dict[str, Any]:
    c = get_analysis_cache(False)
    return {"ok": True, "engine_version": ENGINE_VERSION, "draw_count": c.get("draw_count", 0), "latest_round": c.get("latest_round", 0), "is_full_history": c.get("is_full_history", False), "cache_build_ms": c.get("build_ms", 0)}
