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
from .ai.score_engine import (
    SCORE_ENGINE_VERSION,
    build_number_weights as _build_number_weights,
    pair_strength as _score_pair_strength,
    score_combo as _score_combo_v13,
    triple_strength as _score_triple_strength,
)

ENGINE_VERSION = "BBLOTTO_AI_RECOMMENDATION_V13_02"
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


def _build_cache() -> Dict[str, Any]:
    started = time.perf_counter()
    draws = _load_draws()
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
    recent_patterns = pattern_sigs[-100:] or pattern_sigs
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


def _number_evidence(n: int, cache: Dict[str, Any]) -> Dict[str, Any]:
    hot_rank = {x: i + 1 for i, x in enumerate(cache.get("hot", []))}
    overdue_rank = {x: i + 1 for i, x in enumerate(cache.get("overdue", []))}
    f10 = cache.get("frequency10", {}).get(str(n), 0)
    f30 = cache.get("frequency30", {}).get(str(n), 0)
    gap = cache.get("gap", {}).get(str(n), 0)
    if hot_rank.get(n, 99) <= 10:
        role, reason = "강세수", f"최근 10회 {f10}회·30회 {f30}회 출현한 상승 흐름"
    elif overdue_rank.get(n, 99) <= 10:
        role, reason = "반등수", f"최근 {gap}회 미출현한 반등 관찰 후보"
    else:
        role, reason = "균형수", f"단기·중기 빈도와 전체 흐름이 균형적인 후보"
    return {"number": n, "role": role, "reason": reason, "freq10": f10, "freq30": f30, "freq100": cache.get("frequency100", {}).get(str(n), 0), "gap": gap, "selection_score": cache.get("score_map", {}).get(str(n), 0)}


def make_premium_combos(count: int = 10, fixed: Any = "", excluded: Any = "", mode: str = "balanced", member_grade: str = "일반", member_id: Optional[int] = None):
    started = time.perf_counter()
    target = max(1, min(50, int(count or 10)))
    fixed_nums = _parse_nums(fixed)
    excluded_nums = set(_parse_nums(excluded)) - set(fixed_nums)
    if len(fixed_nums) > 6:
        raise ValueError("고정수는 최대 6개까지 입력할 수 있습니다.")
    if len(set(range(1, 46)) - excluded_nums) < 6:
        raise ValueError("제외수가 너무 많습니다.")

    cache = get_analysis_cache(False)
    weights = _mode_weights(cache, mode, member_grade)
    seed_text = f"{time.time_ns()}|{member_id}|{member_grade}|{mode}|{fixed_nums}|{sorted(excluded_nums)}|{cache.get('latest_round')}"
    rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16))

    candidate_target = min(1800, max(180, target * 45))
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
    for combo, (base_score, detail) in ranked:
        if len(selected) >= target:
            break
        overlap = max((len(set(combo) & set(prev)) for prev in selected), default=0)
        if overlap >= 5:
            continue
        diversity_penalty = sum(max(0, usage[n] - max(1, target // 5)) for n in combo) * 3.2
        adjusted = base_score - diversity_penalty - max(0, overlap - 2) * 4.5
        # 후보 상위권 안에서 포트폴리오 점수로 재평가
        if selected and adjusted < ranked[min(len(ranked)-1, target*8)][1][0] - 18:
            continue
        selected.append(list(combo))
        usage.update(combo)
        archetype = "강세 균형형"
        hot_count = len(set(combo) & set(cache.get("hot", [])[:12]))
        overdue_count = len(set(combo) & set(cache.get("overdue", [])[:12]))
        if overdue_count >= 2: archetype = "반등 혼합형"
        elif hot_count >= 3: archetype = "최근 흐름형"
        elif detail["pair_strength"] >= 2.5: archetype = "동반출현형"
        evidence = [_number_evidence(n, cache) for n in combo]
        reasons = [
            f"최근·중기·전체 출현 흐름과 미출현 간격을 종합한 {archetype}",
            f"홀짝 {detail['odd']}:{detail['even']} · 구간 {detail['zones'][0]}-{detail['zones'][1]}-{detail['zones'][2]} · 합계 {detail['sum']}",
            f"AC {detail['ac']} · 끝수 {detail['end_types']}종 · 최근 당첨조합 최대 중복 {detail['max_recent_overlap']}개",
        ]
        selected_details.append({
            "numbers": list(combo), "score": round(adjusted, 2), "engine_version": ENGINE_VERSION,
            "engine": ENGINE_VERSION, "type": archetype, "strategy": archetype, "portfolio_type": archetype,
            "number_evidence": evidence, "reasons": reasons, "reason": " / ".join(reasons), **detail,
        })

    # 드문 조건에서 후보가 부족하면 제약을 유지한 보완 생성
    while len(selected) < target:
        combo = sorted(fixed_nums + _weighted_sample(rng, weights, 6-len(fixed_nums), excluded_nums | set(fixed_nums)))
        if combo not in selected:
            score, detail = _combo_score(combo, cache, weights)
            selected.append(combo)
            selected_details.append({"numbers": combo, "score": score, "engine_version": ENGINE_VERSION, "engine": ENGINE_VERSION, "type": "보완 균형형", "strategy": "보완 균형형", "portfolio_type": "보완 균형형", "number_evidence": [_number_evidence(n, cache) for n in combo], "reasons": ["전체 이력 가중치 기반 보완 조합"], "reason": "전체 이력 가중치 기반 보완 조합", **detail})

    elapsed = round((time.perf_counter() - started) * 1000, 2)
    stats = {
        "engine_version": ENGINE_VERSION, "engine": ENGINE_VERSION, "score_engine_version": SCORE_ENGINE_VERSION, "full_history": True,
        "draw_count": cache.get("draw_count", 0), "latest_round": cache.get("latest_round", 0),
        "analysis_confirm": cache.get("analysis_confirm"), "cache_build_ms": cache.get("build_ms", 0),
        "generation_ms": elapsed, "candidate_count": len(pool), "attempts": attempts,
        "hot": cache.get("hot", [])[:12], "cold": cache.get("cold", [])[:12], "overdue": cache.get("overdue", [])[:12],
        "unique_numbers": len(usage), "max_number_use": max(usage.values(), default=0),
        "methodology": ["AI-01 영구 캐시 기반", "1회차~최신 회차 전체 분석", "최근 10·30·50·100·300회 다중 가중치", "미출현 간격·모멘텀", "동반출현·트리플", "홀짝·구간·합계·AC·끝수", "조합 간 중복 억제"],
    }
    return selected[:target], selected_details[:target], stats


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
