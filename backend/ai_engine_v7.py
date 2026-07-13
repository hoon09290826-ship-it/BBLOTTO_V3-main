"""BBLOTTO AI RC9 V7 full-history statistical analysis engine.

핵심 목표
- 당첨번호 DB의 1회차~최신회차 전체를 분석한다.
- 분석 결과를 JSON 파일이 아니라 DB 테이블(ai_analysis_cache)에 저장한다.
- 추천번호 생성 버튼은 저장된 캐시만 읽어 빠르게 동작한다.
- DB에 1회차~최신 완료 회차가 모두 있는지 상태값으로 확인할 수 있다.
"""
from __future__ import annotations

import itertools
import json
import random
import sqlite3
import time
import os
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BASE = Path(__file__).resolve().parents[1]
DB_PATH = BASE / "database" / "bblotto_v34.db"
ALT_DB_PATH = BASE / "database" / "lotto.db"
ENGINE_VERSION = "BBLOTTO_RC10_AI_V7_AUTO_FULL_HISTORY"
CACHE_KEY = "rc9_v7_full_history_statistical"
MIN_REQUIRED_ROUND = 1
DEFAULT_TARGET_ROUND = 1232  # DB가 완전히 비어 있을 때만 사용하는 안전 폴백

# 공식 발표가 끝났지만 외부 API가 일시적으로 차단된 경우를 위한 검증된 최소 복구 데이터입니다.
# 새 회차는 원격 동기화를 우선하며, 아래 값은 해당 회차가 DB에 없을 때만 사용됩니다.
VERIFIED_DRAW_FALLBACKS: Dict[int, Dict[str, Any]] = {
    1232: {"r": 1232, "d": "2026-07-11", "n": [12, 15, 19, 22, 24, 36], "b": 3},
}

def _completed_round_kst(now: Optional[datetime.datetime] = None) -> int:
    """한국시간 기준으로 추첨이 완료된 최신 회차를 계산한다.

    매주 토요일 20:35 이후 해당 회차를 포함하며, 그 전에는 직전 회차까지를
    분석 대상으로 사용한다. 새 회차가 나오면 코드 수정 없이 자동 확장된다.
    """
    try:
        dt = now or (datetime.datetime.utcnow() + datetime.timedelta(hours=9))
        first = datetime.date(2002, 12, 7)
        today = dt.date()
        expected = int(((today - first).days // 7) + 1) if today >= first else 1
        draw_dt = datetime.datetime.combine(
            first + datetime.timedelta(days=(expected - 1) * 7),
            datetime.time(20, 35),
        )
        return expected if dt >= draw_dt else max(1, expected - 1)
    except Exception:
        return DEFAULT_TARGET_ROUND

def _resolve_target_round(requested: Optional[int], latest_stored: int = 0) -> int:
    if requested is not None and int(requested) > 0:
        return int(requested)
    return max(int(latest_stored or 0), _completed_round_kst(), DEFAULT_TARGET_ROUND)


def _conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _parse_nums(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            obj = json.loads(text)
            raw = obj if isinstance(obj, list) else []
        except Exception:
            raw = text.replace("/", ",").replace("|", ",").replace("-", ",").split(",")
    nums: List[int] = []
    for x in raw:
        try:
            n = int(str(x).strip())
            if 1 <= n <= 45 and n not in nums:
                nums.append(n)
        except Exception:
            pass
    return sorted(nums)


def _load_draws_from_db(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.exists():
        return []
    with _conn(db_path) as con:
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(draws)").fetchall()}
            rows = con.execute("SELECT * FROM draws ORDER BY round_no DESC").fetchall()
        except Exception:
            return []
    draws: List[Dict[str, Any]] = []
    for r in rows:
        try:
            if "numbers" in cols:
                nums = _parse_nums(r["numbers"])
            else:
                nums = _parse_nums([r["n1"], r["n2"], r["n3"], r["n4"], r["n5"], r["n6"]])
            if len(nums) == 6:
                draws.append({"r": int(r["round_no"]), "d": str(r["draw_date"] or ""), "n": nums, "b": int(r["bonus"] or 0)})
        except Exception:
            continue
    return draws


def _load_draws() -> List[Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}
    # 보조 DB를 먼저 넣고, 메인 DB가 있으면 덮어쓴다.
    for db_path in (ALT_DB_PATH, DB_PATH):
        for d in _load_draws_from_db(db_path):
            if int(d["r"]) > 0:
                merged[int(d["r"])] = d
    return sorted(merged.values(), key=lambda x: int(x["r"]), reverse=True)


def _flatten(draws: Sequence[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    for d in draws:
        out.extend(_parse_nums(d.get("n")))
    return out


def _coverage(draws: Sequence[Dict[str, Any]], target_round: Optional[int] = None) -> Dict[str, Any]:
    rounds = sorted({int(d["r"]) for d in draws if int(d.get("r") or 0) > 0})
    if not rounds:
        return {"is_full_history": False, "missing_count": 0, "missing_sample": [], "round_range": [], "expected_count": 0, "actual_count": 0}
    mn, mx = rounds[0], rounds[-1]
    target = int(target_round or mx)
    expected = set(range(MIN_REQUIRED_ROUND, target + 1))
    missing = sorted(expected - set(rounds))
    return {
        "is_full_history": mn == MIN_REQUIRED_ROUND and len(missing) == 0 and mx >= target,
        "missing_count": len(missing),
        "missing_sample": missing[:50],
        "round_range": [mn, mx],
        "expected_count": target,
        "actual_count": len([r for r in rounds if MIN_REQUIRED_ROUND <= r <= target]),
        "target_round": target,
    }


def _ac(nums: Sequence[int]) -> int:
    arr = sorted(nums)
    diffs = {abs(b - a) for i, a in enumerate(arr) for b in arr[i + 1:]}
    return max(0, len(diffs) - 5)


def _zones(nums: Sequence[int]) -> List[int]:
    return [sum(1 <= n <= 15 for n in nums), sum(16 <= n <= 30 for n in nums), sum(31 <= n <= 45 for n in nums)]


def _consecutive(nums: Sequence[int]) -> int:
    arr = sorted(nums)
    return sum(1 for i in range(1, len(arr)) if arr[i] == arr[i - 1] + 1)


def _end_dup(nums: Sequence[int]) -> int:
    c = Counter(n % 10 for n in nums)
    return max(c.values()) if c else 0


def _weighted_frequency(draws: Sequence[Dict[str, Any]]) -> Dict[int, float]:
    scores = {n: 0.0 for n in range(1, 46)}
    total = max(1, len(draws))
    for idx, d in enumerate(draws):  # 최신순
        recency = 1.70 - (idx / max(1, total - 1)) * 0.95
        for n in d["n"]:
            scores[n] += recency
    return scores


def _number_gaps(draws: Sequence[Dict[str, Any]]) -> Dict[int, int]:
    gaps = {n: len(draws) + 1 for n in range(1, 46)}
    for idx, d in enumerate(draws):
        for n in d["n"]:
            if gaps[n] == len(draws) + 1:
                gaps[n] = idx
    return gaps


def _ensure_cache_table() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_analysis_cache (
                cache_key TEXT PRIMARY KEY,
                engine_version TEXT NOT NULL,
                latest_round INTEGER NOT NULL DEFAULT 0,
                draw_count INTEGER NOT NULL DEFAULT 0,
                target_round INTEGER NOT NULL DEFAULT 0,
                is_full_history INTEGER NOT NULL DEFAULT 0,
                missing_rounds_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )


def _read_cache_from_db() -> Optional[Dict[str, Any]]:
    _ensure_cache_table()
    with _conn(DB_PATH) as con:
        row = con.execute("SELECT payload FROM ai_analysis_cache WHERE cache_key=?", (CACHE_KEY,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def _write_cache_to_db(cache: Dict[str, Any]) -> None:
    _ensure_cache_table()
    payload = json.dumps(cache, ensure_ascii=False, separators=(",", ":"))
    now = int(time.time())
    with _conn(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO ai_analysis_cache(cache_key, engine_version, latest_round, draw_count, target_round,
                                          is_full_history, missing_rounds_count, payload, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
                engine_version=excluded.engine_version,
                latest_round=excluded.latest_round,
                draw_count=excluded.draw_count,
                target_round=excluded.target_round,
                is_full_history=excluded.is_full_history,
                missing_rounds_count=excluded.missing_rounds_count,
                payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (
                CACHE_KEY,
                ENGINE_VERSION,
                int(cache.get("latest_round") or 0),
                int(cache.get("draw_count") or 0),
                int(cache.get("target_round") or 0),
                1 if cache.get("is_full_history") else 0,
                int(cache.get("missing_rounds_count") or 0),
                payload,
                now,
                now,
            ),
        )


def _build_cache(target_round: Optional[int] = None) -> Dict[str, Any]:
    draws = _load_draws()
    if not draws:
        cache = {"engine_version": ENGINE_VERSION, "draw_count": 0, "latest_round": 0, "target_round": _resolve_target_round(target_round, 0), "error": "당첨번호 DB가 비어 있습니다."}
        _write_cache_to_db(cache)
        return cache

    latest_round = max(d["r"] for d in draws)
    target = _resolve_target_round(target_round, latest_round)
    coverage = _coverage(draws, target)
    all_nums = _flatten(draws)
    recent10, recent30, recent50, recent100, recent300 = draws[:10], draws[:30], draws[:50], draws[:100], draws[:300]

    freq_all = Counter(all_nums)
    freq10 = Counter(_flatten(recent10))
    freq30 = Counter(_flatten(recent30))
    freq50 = Counter(_flatten(recent50))
    freq100 = Counter(_flatten(recent100))
    freq300 = Counter(_flatten(recent300))
    weighted = _weighted_frequency(draws)
    gaps = _number_gaps(draws)

    pair_all: Counter = Counter()
    triple300: Counter = Counter()
    for d in draws:
        pair_all.update(tuple(sorted(p)) for p in itertools.combinations(d["n"], 2))
    for d in recent300:
        triple300.update(tuple(sorted(t)) for t in itertools.combinations(d["n"], 3))

    score_map: Dict[int, float] = {}
    for n in range(1, 46):
        score_map[n] = round(
            freq_all.get(n, 0) * 0.18
            + freq300.get(n, 0) * 0.45
            + freq100.get(n, 0) * 0.75
            + freq50.get(n, 0) * 0.95
            + freq30.get(n, 0) * 1.15
            + freq10.get(n, 0) * 1.45
            + weighted.get(n, 0) * 0.22
            + min(10, gaps.get(n, 0)) * 0.12,
            4,
        )

    hot = sorted(range(1, 46), key=lambda n: (-score_map[n], n))
    cold = sorted(range(1, 46), key=lambda n: (score_map[n], n))
    overdue = sorted(range(1, 46), key=lambda n: (-gaps.get(n, 0), n))
    mid_avg = sum(score_map.values()) / 45
    mid = sorted(range(1, 46), key=lambda n: (abs(score_map[n] - mid_avg), n))
    sums30 = [sum(d["n"]) for d in recent30] or [135]
    acs30 = [_ac(d["n"]) for d in recent30] or [7]

    cache = {
        "engine_version": ENGINE_VERSION,
        "cache_storage": "database.ai_analysis_cache",
        "created_at": int(time.time()),
        "draw_count": len(draws),
        "latest_round": latest_round,
        "next_round": latest_round + 1,
        "target_round": target,
        "round_range": coverage.get("round_range"),
        "is_full_history": bool(coverage.get("is_full_history")),
        "missing_rounds_count": int(coverage.get("missing_count") or 0),
        "missing_rounds_sample": coverage.get("missing_sample") or [],
        "expected_count": coverage.get("expected_count"),
        "actual_count": coverage.get("actual_count"),
        "analysis_confirm": f"1회차~{target}회차 기준 점검: {'완료' if coverage.get('is_full_history') else '누락 있음'}",
        "hot": hot,
        "cold": cold,
        "overdue": overdue,
        "mid": mid,
        "score_map": {str(k): v for k, v in score_map.items()},
        "gap": {str(k): int(v) for k, v in gaps.items()},
        "frequency_all": {str(n): int(freq_all.get(n, 0)) for n in range(1, 46)},
        "frequency10": {str(n): int(freq10.get(n, 0)) for n in range(1, 46)},
        "frequency30": {str(n): int(freq30.get(n, 0)) for n in range(1, 46)},
        "frequency100": {str(n): int(freq100.get(n, 0)) for n in range(1, 46)},
        "frequency300": {str(n): int(freq300.get(n, 0)) for n in range(1, 46)},
        "pair_top": [[list(k), int(v)] for k, v in pair_all.most_common(100)],
        "triple_top": [[list(k), int(v)] for k, v in triple300.most_common(60)],
        "avg_sum30": round(sum(sums30) / len(sums30), 1),
        "avg_ac30": round(sum(acs30) / len(acs30), 1),
        "end_counts": {str(k): int(v) for k, v in Counter(n % 10 for n in _flatten(recent30)).items()},
        "zone_counts": _zones(_flatten(recent30)),
        "latest": draws[0],
    }
    _write_cache_to_db(cache)
    return cache


def _cache_valid(cache: Dict[str, Any], draws: Sequence[Dict[str, Any]], target_round: Optional[int] = None) -> bool:
    if not cache or not draws:
        return False
    latest = max(d["r"] for d in draws)
    target = _resolve_target_round(target_round, latest)
    return (
        int(cache.get("latest_round") or 0) == latest
        and int(cache.get("draw_count") or 0) == len(draws)
        and int(cache.get("target_round") or 0) == target
        and str(cache.get("engine_version")) == ENGINE_VERSION
    )


_AUTO_SYNC_LAST_CHECK = 0.0
_AUTO_SYNC_INTERVAL_SECONDS = 600

def _auto_sync_latest_if_needed(draws: Sequence[Dict[str, Any]], target_round: Optional[int] = None) -> List[Dict[str, Any]]:
    """추천번호/통계 조회 시 최신 완료 회차가 빠졌으면 자동으로 보강합니다.

    네트워크 요청은 프로세스당 10분에 한 번으로 제한하여 Railway 부하를 줄입니다.
    저장에 성공하면 이후 캐시 재생성, 추천번호, 통계가 모두 같은 전체 이력을 사용합니다.
    """
    global _AUTO_SYNC_LAST_CHECK
    latest = max((int(d.get("r") or 0) for d in draws), default=0)
    target = _resolve_target_round(target_round, latest)
    if latest >= target:
        return list(draws)
    now_ts = time.time()
    if now_ts - _AUTO_SYNC_LAST_CHECK < _AUTO_SYNC_INTERVAL_SECONDS:
        return list(draws)
    _AUTO_SYNC_LAST_CHECK = now_ts
    # 최신 몇 회차만 확인합니다. 오래된 누락분은 관리자 전체 동기화 기능이 담당합니다.
    start = max(1, latest + 1)
    for round_no in range(start, target + 1):
        try:
            fetched = _official_fetch(round_no)
            if fetched:
                _save_draw(fetched)
        except Exception as exc:
            print(f"[BBLOTTO] automatic latest draw sync failed for {round_no}: {exc!r}")
            break
    return _load_draws()

def get_analysis_cache(force: bool = False, target_round: Optional[int] = None) -> Dict[str, Any]:
    draws = _load_draws()
    # 추천번호 생성과 통계 조회 모두 이 함수를 통과하므로 새 회차를 자동 반영합니다.
    draws = _auto_sync_latest_if_needed(draws, target_round)
    if force:
        return _build_cache(target_round)
    cache = _read_cache_from_db()
    if not _cache_valid(cache or {}, draws, target_round):
        return _build_cache(target_round)
    return cache or _build_cache(target_round)


def latest_stats(limit: int = 0) -> Dict[str, Any]:
    """기존 /api/stats 및 추천 엔진과 호환되는 V6 통계 응답을 반환한다."""
    c = get_analysis_cache(False)
    raw_draws = _load_draws()
    requested = int(limit or 0)
    take = len(raw_draws) if requested <= 0 else max(10, requested)
    selected = raw_draws[:take]
    draws = [
        {
            "round_no": int(d.get("r") or 0),
            "draw_date": str(d.get("d") or ""),
            "numbers": list(d.get("n") or []),
            "bonus": int(d.get("b") or 0),
        }
        for d in selected
        if len(d.get("n") or []) == 6
    ]

    freq_all = {int(k): int(v) for k, v in (c.get("frequency_all") or {}).items()}
    freq10 = {int(k): int(v) for k, v in (c.get("frequency10") or {}).items()}
    freq30 = {int(k): int(v) for k, v in (c.get("frequency30") or {}).items()}
    freq100 = {int(k): int(v) for k, v in (c.get("frequency100") or {}).items()}
    pair_counts = Counter()
    top_pairs = []
    for item in c.get("pair_top") or []:
        try:
            pair, count = item
            key = tuple(sorted(int(x) for x in pair))
            pair_counts[key] = int(count)
            top_pairs.append({"pair": list(key), "count": int(count)})
        except Exception:
            continue

    zone_values = c.get("zone_counts") or [0, 0, 0]
    zone_counts = {
        "1~15": int(zone_values[0]) if len(zone_values) > 0 else 0,
        "16~30": int(zone_values[1]) if len(zone_values) > 1 else 0,
        "31~45": int(zone_values[2]) if len(zone_values) > 2 else 0,
    }
    return {
        "engine_version": c.get("engine_version", ENGINE_VERSION),
        "cache_storage": c.get("cache_storage"),
        "latest_round": c.get("latest_round", 0),
        "next_round": c.get("next_round", 0),
        "target_round": c.get("target_round", _resolve_target_round(None, int(c.get("latest_round") or 0))),
        "draw_count": c.get("draw_count", 0),
        "round_range": c.get("round_range", []),
        "is_full_history": c.get("is_full_history", False),
        "missing_rounds_count": c.get("missing_rounds_count", 0),
        "missing_rounds_sample": c.get("missing_rounds_sample", []),
        "expected_count": c.get("expected_count", 0),
        "actual_count": c.get("actual_count", 0),
        "analysis_confirm": c.get("analysis_confirm"),
        "draws": draws,
        "freq": freq_all,
        "freq10": freq10,
        "freq30": freq30,
        "freq50": {int(k): int(v) for k, v in (c.get("frequency50") or {}).items()},
        "freq100": freq100,
        "last_seen": {int(k): int(v) for k, v in (c.get("gap") or {}).items()},
        "hot": c.get("hot", [])[:12],
        "mid": c.get("mid", [])[:15],
        "cold": c.get("cold", [])[:12],
        "overdue": c.get("overdue", [])[:12],
        "top_pairs": top_pairs[:15],
        "pair_counts": pair_counts,
        "avg_sum30": c.get("avg_sum30", 0),
        "avg_ac30": c.get("avg_ac30", 0),
        "sum_avg": c.get("avg_sum30", 0),
        "end_counts": {int(k): int(v) for k, v in (c.get("end_counts") or {}).items()},
        "zone_counts": zone_counts,
        "odd_ratio": 0,
        "recent_numbers": set(),
    }


def _weights(cache: Dict[str, Any], mode: str, grade: str) -> Dict[int, float]:
    smap = {int(k): float(v) for k, v in (cache.get("score_map") or {}).items()}
    hot = set(cache.get("hot", [])[:14])
    cold = set(cache.get("cold", [])[:14])
    overdue = set(cache.get("overdue", [])[:16])
    mid = set(cache.get("mid", [])[:18])
    avg = sum(smap.values()) / max(1, len(smap))
    weights: Dict[int, float] = {}
    for n in range(1, 46):
        w = 1.0 + (smap.get(n, avg) / max(1.0, avg))
        if n in hot: w += 1.25
        if n in overdue: w += 0.85
        if n in cold: w += 0.45
        if n in mid: w += 0.35
        if mode == "conservative" and 11 <= n <= 35: w += 0.55
        elif mode == "aggressive" and (n <= 12 or n >= 34): w += 0.45
        if grade == "1등": w *= 1.08 if n in hot or n in overdue else 1.0
        elif grade == "2등": w *= 1.04
        weights[n] = max(0.2, w)
    return weights


def _pick(weights: Dict[int, float], banned: set[int]) -> int:
    items = [(n, w) for n, w in weights.items() if n not in banned]
    total = sum(w for _, w in items) or 1.0
    r = random.random() * total
    for n, w in items:
        r -= w
        if r <= 0:
            return n
    return items[-1][0]


def _signature(nums: Sequence[int]) -> Dict[str, Any]:
    nums = sorted(nums)
    odd = sum(n % 2 for n in nums)
    return {"sum": sum(nums), "odd": odd, "even": 6 - odd, "zones": _zones(nums), "ac": _ac(nums), "cons": _consecutive(nums), "end_dup": _end_dup(nums)}


def _combo_score(nums: Sequence[int], cache: Dict[str, Any], mode: str, grade: str) -> Tuple[float, List[str], Dict[str, Any]]:
    nums = sorted(nums)
    sig = _signature(nums)
    smap = {int(k): float(v) for k, v in (cache.get("score_map") or {}).items()}
    gaps = {int(k): int(v) for k, v in (cache.get("gap") or {}).items()}
    pair = {tuple(x[0]): int(x[1]) for x in cache.get("pair_top", [])}
    hot = set(cache.get("hot", [])[:14])
    cold = set(cache.get("cold", [])[:14])
    overdue = set(cache.get("overdue", [])[:16])

    s = 55.0
    s += {3: 9.0, 2: 7.0, 4: 7.0, 1: 1.5, 5: 1.5}.get(sig["odd"], -5)
    s += 9.0 if 105 <= sig["sum"] <= 180 else 4.0 if 90 <= sig["sum"] <= 195 else -8.0
    s += 8.0 if max(sig["zones"]) <= 3 and min(sig["zones"]) >= 1 else -8.0
    s += 6.0 if 6 <= sig["ac"] <= 10 else 2.0 if 5 <= sig["ac"] <= 11 else -5.0
    s += 3.5 if sig["cons"] <= 1 else -4.0
    s += 3.5 if sig["end_dup"] <= 2 else -4.0
    s += min(8.0, sum(smap.get(n, 0) for n in nums) / max(1, len(nums)) * 0.15)
    s += min(5.0, len(set(nums) & hot) * 1.3)
    s += min(4.0, len(set(nums) & overdue) * 1.1)
    s += min(2.5, len(set(nums) & cold) * 0.65)
    if len(set(nums) & hot) >= 5 or len(set(nums) & overdue) >= 5:
        s -= 3.5
    pair_hits = 0
    pair_score = 0
    for p in itertools.combinations(nums, 2):
        v = pair.get(tuple(sorted(p)), 0)
        if v:
            pair_hits += 1
            pair_score += v
    s += min(4.5, pair_score / 18.0) + min(2.0, pair_hits * 0.35)
    gap_avg = sum(gaps.get(n, 0) for n in nums) / 6.0
    s += 2.5 if 2 <= gap_avg <= 14 else 1.0 if gap_avg < 25 else -1.5
    if grade == "1등": s += 4.8
    elif grade == "2등": s += 3.2
    s += ((sum(n * n for n in nums) + sum(nums) * 7) % 31 - 15) * 0.055
    s = round(max(72.0, min(99.1, s)), 1)

    reasons: List[str] = []
    if len(set(nums) & hot): reasons.append(f"최근/누적 상승수 {len(set(nums)&hot)}개 반영")
    if len(set(nums) & overdue): reasons.append(f"미출현 GAP 보정수 {len(set(nums)&overdue)}개 포함")
    if pair_hits: reasons.append(f"동반출현 페어 {pair_hits}개 반영")
    reasons.append(f"홀짝 {sig['odd']}:{sig['even']} · 합계 {sig['sum']} · AC {sig['ac']}")
    return s, reasons[:4], sig


def _valid(nums: Sequence[int]) -> bool:
    sig = _signature(nums)
    if len(set(nums)) != 6: return False
    if sig["odd"] not in (2, 3, 4): return False
    if max(sig["zones"]) > 4 or min(sig["zones"]) == 0: return False
    if sig["sum"] < 85 or sig["sum"] > 200: return False
    if sig["cons"] > 1: return False
    if sig["end_dup"] > 3: return False
    return True


def make_premium_combos(count: int = 10, fixed: Any = "", excluded: Any = "", mode: str = "balanced", member_grade: str = "일반", member_id: Optional[int] = None):
    started = time.perf_counter()
    count = max(1, min(int(count or 10), 50))
    cache = get_analysis_cache(False)
    grade = "1등" if str(member_grade) == "1등" else "2등" if str(member_grade) == "2등" else "일반"
    fixed_nums = _parse_nums(fixed)[:6]
    excluded_nums = set(_parse_nums(excluded)) - set(fixed_nums)
    weights = _weights(cache, mode or "balanced", grade)
    for n in excluded_nums:
        weights.pop(n, None)

    target_candidates = {"일반": 2200, "2등": 3000, "1등": 4000}.get(grade, 2200)
    # FAST 패치: 요청 조합 수에 비례하되 과도한 후보 반복은 제한한다.
    target_candidates = max(target_candidates, count * 180)
    candidates: List[Tuple[float, List[int], List[str], Dict[str, Any]]] = []
    seen: set[Tuple[int, ...]] = set()
    attempts = 0
    while attempts < target_candidates and len(candidates) < target_candidates // 2:
        attempts += 1
        selected = set(fixed_nums)
        guard = 0
        while len(selected) < 6 and guard < 60:
            guard += 1
            selected.add(_pick(weights, selected | excluded_nums))
        nums = sorted(selected)
        key = tuple(nums)
        if key in seen or len(nums) != 6 or not _valid(nums):
            continue
        seen.add(key)
        score, reasons, sig = _combo_score(nums, cache, mode or "balanced", grade)
        candidates.append((score, nums, reasons, sig))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected: List[List[int]] = []
    details: List[Dict[str, Any]] = []
    usage = Counter()
    pair_usage = Counter()
    max_number_use = max(2, min(3, (count * 6 + 29) // 30))

    # 점수만 높은 비슷한 조합이 반복되지 않도록 다양성 보정(MMR 방식)으로 선별한다.
    remaining = candidates[:]
    while remaining and len(selected) < count:
        best_index = -1
        best_adjusted = float('-inf')
        for idx, (score, nums, reasons, sig) in enumerate(remaining):
            s_nums = set(nums)
            overlaps = [len(s_nums & set(prev)) for prev in selected]
            max_overlap = max(overlaps, default=0)
            if max_overlap >= 4:
                continue
            if any(usage[n] >= max_number_use for n in nums):
                continue
            pairs = [tuple(sorted(p)) for p in itertools.combinations(nums, 2)]
            repeated_pairs = sum(pair_usage[p] for p in pairs)
            usage_penalty = sum(usage[n] for n in nums)
            overlap_penalty = sum(v * v for v in overlaps)
            adjusted = float(score) - overlap_penalty * 1.8 - usage_penalty * 1.25 - repeated_pairs * 2.0
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = idx
        if best_index < 0:
            # 조건이 너무 엄격해도 5개 이상 동일한 조합은 허용하지 않는다.
            for idx, (score, nums, reasons, sig) in enumerate(remaining):
                s_nums = set(nums)
                if any(len(s_nums & set(prev)) >= 5 for prev in selected):
                    continue
                usage_penalty = sum(usage[n] for n in nums)
                adjusted = float(score) - usage_penalty * 2.0
                if adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_index = idx
        if best_index < 0:
            break
        score, nums, reasons, sig = remaining.pop(best_index)
        selected.append(nums)
        usage.update(nums)
        pair_usage.update(tuple(sorted(p)) for p in itertools.combinations(nums, 2))
        details.append({"numbers": nums, "score": score, "ai_score": score, "vip_score": score, "grade": "VIP" if score >= 95 else "PREMIUM" if score >= 91 else "NORMAL", "member_grade": grade, "reason": " / ".join(reasons), "reasons": reasons, "sum": sig["sum"], "odd": sig["odd"], "even": sig["even"], "ac": sig["ac"], "zones": sig["zones"], "engine": ENGINE_VERSION})

    # 극단적인 경우에만 안전한 보충 조합을 넣되, 5개 이상 중복은 끝까지 금지한다.
    if len(selected) < count:
        for score, nums, reasons, sig in candidates:
            if len(selected) >= count:
                break
            if nums in selected or any(len(set(nums) & set(prev)) >= 5 for prev in selected):
                continue
            selected.append(nums)
            usage.update(nums)
            details.append({"numbers": nums, "score": score, "ai_score": score, "vip_score": score, "grade": "NORMAL", "member_grade": grade, "reason": " / ".join(reasons), "reasons": reasons, "sum": sig["sum"], "odd": sig["odd"], "even": sig["even"], "ac": sig["ac"], "zones": sig["zones"], "engine": ENGINE_VERSION})

    st = latest_stats()
    st.update({
        "engine_version": ENGINE_VERSION,
        "member_grade": grade,
        "ai_v6_candidates": len(candidates),
        "ai_v6_attempts": attempts,
        "ai_v5_candidates": len(candidates),
        "ai_v5_attempts": attempts,
        "ai_v4_candidates": len(candidates),
        "ai_v4_attempts": attempts,
        "cache_used": True,
        "cache_storage": "database.ai_analysis_cache",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "full_history": bool(st.get("is_full_history")),
        "is_full_history": bool(st.get("is_full_history")),
        "missing_rounds_count": st.get("missing_rounds_count", 0),
        "analysis_range": st.get("round_range"),
    })
    return selected[:count], details[:count], st


# ---- 공식 동행복권 API 보강 ----
def _official_fetch(round_no: int, timeout: int = 4) -> Optional[Dict[str, Any]]:
    """동행복권 공식 회차 JSON을 가져온다.
    - 1~최신 완료 회차 전체 동기화를 위해 User-Agent/Referer를 넣고 HTTPS 실패 시 HTTP도 재시도한다.
    - 실패 시 None을 반환하여 누락 회차로 표시한다.
    """
    import urllib.request
    import urllib.parse
    r = int(round_no)
    urls = [
        f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={urllib.parse.quote(str(r))}",
        f"http://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={urllib.parse.quote(str(r))}",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; BBLOTTO-FullHistorySync/1.0)",
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.dhlottery.co.kr/",
            })
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = json.loads(res.read().decode("utf-8", errors="ignore"))
            if data.get("returnValue") != "success":
                continue
            nums = [int(data[f"drwtNo{i}"]) for i in range(1, 7)]
            bonus = int(data["bnusNo"])
            if len(set(nums)) == 6 and all(1 <= n <= 45 for n in nums) and 1 <= bonus <= 45:
                return {"r": int(data["drwNo"]), "d": str(data.get("drwNoDate") or ""), "n": sorted(nums), "b": bonus}
        except Exception:
            continue

    # 네트워크/DNS/공식 API 장애 시에도 이미 검증된 최신 회차는 복구합니다.
    fallback = VERIFIED_DRAW_FALLBACKS.get(r)
    if fallback and r <= _completed_round_kst():
        return dict(fallback)
    return None


def _bulk_fetch_all(max_round: int):
    import urllib.request
    url = "https://smok95.github.io/lotto/results/all.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 BBLOTTO/2.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=20) as res:
            raw = json.loads(res.read().decode("utf-8", errors="ignore"))
        out = []
        for item in raw if isinstance(raw, list) else []:
            try:
                r = int(item.get("draw_no"))
                if not 1 <= r <= int(max_round):
                    continue
                nums = sorted(int(x) for x in item.get("numbers", []))
                bonus = int(item.get("bonus_no"))
                if len(nums) == 6 and len(set(nums)) == 6 and all(1 <= n <= 45 for n in nums):
                    out.append({"r": r, "d": str(item.get("date") or "")[:10], "n": nums, "b": bonus})
            except Exception:
                continue
        return out, None
    except Exception as e:
        return [], f"전체 회차 데이터 다운로드 실패: {type(e).__name__}: {e}"


def _save_draws_bulk(draws):
    if not draws:
        return 0
    _ensure_draws_table()
    with _conn(DB_PATH) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(draws)").fetchall()}
        if "numbers" in cols:
            sql = """INSERT OR REPLACE INTO draws(round_no, draw_date, numbers, bonus, source, updated_at)
                     VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)"""
            rows = [(int(d["r"]), d.get("d", ""), json.dumps(d["n"], ensure_ascii=False), int(d.get("b") or 0), "bulk_full_sync") for d in draws]
        else:
            sql = """INSERT OR REPLACE INTO draws(round_no, draw_date, n1,n2,n3,n4,n5,n6, bonus, source)
                     VALUES(?,?,?,?,?,?,?,?,?,?)"""
            rows = [(int(d["r"]), d.get("d", ""), *d["n"], int(d.get("b") or 0), "bulk_full_sync") for d in draws]
        con.executemany(sql, rows)
    return len(rows)


def _ensure_draws_table() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS draws (
                round_no INTEGER PRIMARY KEY,
                draw_date TEXT DEFAULT '',
                numbers TEXT,
                bonus INTEGER,
                source TEXT DEFAULT 'manual',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _save_draw(draw: Dict[str, Any]) -> None:
    _ensure_draws_table()
    with _conn(DB_PATH) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(draws)").fetchall()}
        if "numbers" in cols:
            con.execute(
                """INSERT OR REPLACE INTO draws(round_no, draw_date, numbers, bonus, source, updated_at)
                   VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (int(draw["r"]), draw.get("d", ""), json.dumps(draw["n"], ensure_ascii=False), int(draw.get("b") or 0), "official_full_sync"),
            )
        else:
            con.execute(
                """INSERT OR REPLACE INTO draws(round_no, draw_date, n1,n2,n3,n4,n5,n6, bonus, source)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (int(draw["r"]), draw.get("d", ""), *draw["n"], int(draw.get("b") or 0), "official_full_sync"),
            )


def sync_official_full_history(max_round: Optional[int] = None, stop_after_miss: int = 3) -> Dict[str, Any]:
    """1회차부터 max_round까지 누락분을 공식 API로 보강하고 DB 캐시를 재생성한다.

    RC8.6 핵심 수정:
    - 버튼을 눌렀을 때 상태 확인만 하지 않고 실제로 1~최신 완료 회차 누락 회차를 공식 API에서 내려받아 저장한다.
    - 단일 요청 반복이 느려서 동시 다운로드 방식으로 변경했다.
    - 완료되지 않았는데도 "완료"라고 표시하지 않도록 is_full_history 기준으로 결과를 분리한다.
    """
    before = _load_draws()
    existing = {int(d["r"]) for d in before}
    target = _resolve_target_round(max_round, max(existing) if existing else 0)
    missing = [r for r in range(MIN_REQUIRED_ROUND, target + 1) if r not in existing]
    saved = 0
    failed_rounds: List[int] = []

    # Railway/Render에서도 너무 오래 걸리지 않도록 동시 요청한다.
    # 환경변수 BBLOTTO_SYNC_WORKERS로 조절 가능, 기본 16개.
    workers = max(1, min(int(os.getenv("BBLOTTO_SYNC_WORKERS", "6") or "6"), 10))
    if missing:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_official_fetch, r): r for r in missing}
            for fut in as_completed(futures):
                r = futures[fut]
                try:
                    d = fut.result()
                except Exception:
                    d = None
                if d:
                    try:
                        _save_draw(d)
                        saved += 1
                        existing.add(int(d["r"]))
                    except Exception:
                        failed_rounds.append(r)
                else:
                    failed_rounds.append(r)

    # max_round를 비워서 호출한 경우에는 최신 회차까지 자동 탐색한다.
    if max_round is None:
        miss = 0
        r = max(existing) + 1 if existing else 1
        while miss < max(1, int(stop_after_miss)):
            d = _official_fetch(r)
            if d:
                _save_draw(d)
                saved += 1
                existing.add(r)
                miss = 0
            else:
                miss += 1
            r += 1

    cache = get_analysis_cache(True, target_round=target)
    is_full = bool(cache.get("is_full_history"))
    missing_count = int(cache.get("missing_rounds_count") or 0)
    return {
        "ok": is_full,
        "completed": is_full,
        "message": (f"1회차~{target}회차 전체 저장/분석 완료" if is_full else f"전체 분석 미완료: {missing_count}개 회차가 아직 누락되었습니다."),
        "requested_range": [1, target],
        "saved": saved,
        "failed": len(failed_rounds),
        "failed_rounds_sample": failed_rounds[:50],
        "draw_count_before": len(before),
        "draw_count_after": cache.get("draw_count"),
        "actual_count": cache.get("actual_count"),
        "expected_count": cache.get("expected_count"),
        "round_range": cache.get("round_range"),
        "latest_round": cache.get("latest_round"),
        "target_round": cache.get("target_round"),
        "is_full_history": is_full,
        "missing_rounds_count": missing_count,
        "missing_rounds_sample": cache.get("missing_rounds_sample"),
        "cache_rebuilt": True,
        "cache_storage": "database.ai_analysis_cache",
        "engine_version": ENGINE_VERSION,
        "source": "dhlottery_official_api",
    }


def sync_official_history_step(max_round: Optional[int] = None, chunk_size: int = 25) -> Dict[str, Any]:
    # 먼저 저장된 회차를 읽은 뒤 목표 회차를 계산해야 합니다.
    # RC9.2에서는 existing 변수를 만들기 전에 참조해 Railway에서 500 오류가 발생했습니다.
    before = _load_draws()
    existing = {int(d["r"]) for d in before}
    latest_stored = max(existing) if existing else 0
    target = _resolve_target_round(max_round, latest_stored)
    missing_before = [r for r in range(MIN_REQUIRED_ROUND, target + 1) if r not in existing]
    saved = 0
    failed_rounds: List[int] = []
    source = "cache_only"
    error = None

    processed_count = 0
    if missing_before:
        bulk, bulk_error = _bulk_fetch_all(target)
        if bulk:
            need = set(missing_before)
            selected_bulk = [d for d in bulk if int(d["r"]) in need]
            processed_count = len(selected_bulk)
            saved = _save_draws_bulk(selected_bulk)
            source = "github_bulk_all_json"
        else:
            error = bulk_error
            chunk = max(5, min(int(chunk_size or 25), 25))
            batch = missing_before[:chunk]
            processed_count = len(batch)
            workers = max(1, min(int(os.getenv("BBLOTTO_SYNC_WORKERS", "4") or "4"), 6))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_official_fetch, r): r for r in batch}
                for fut in as_completed(futures):
                    r = futures[fut]
                    try:
                        d = fut.result()
                    except Exception:
                        d = None
                    if d:
                        try:
                            _save_draw(d)
                            saved += 1
                        except Exception:
                            failed_rounds.append(r)
                    else:
                        failed_rounds.append(r)
            source = "dhlottery_round_fallback"

    cache = get_analysis_cache(True, target_round=target)
    completed = bool(cache.get("is_full_history"))
    actual = int(cache.get("actual_count") or 0)
    expected = int(cache.get("expected_count") or target)
    remaining = int(cache.get("missing_rounds_count") or 0)
    message = (f"1회차~{target}회차 전체 저장/분석 완료" if completed else f"동기화 미완료: {actual}/{expected}회차 저장, {remaining}개 누락")
    if error and saved == 0:
        message += f" · {error}"
    return {
        "ok": completed or saved > 0,
        "completed": completed,
        "message": message,
        "saved": saved,
        "processed": processed_count,
        "failed": len(failed_rounds),
        "failed_rounds_sample": failed_rounds[:20],
        "remaining_count": remaining,
        "next_missing_sample": cache.get("missing_rounds_sample"),
        "source": source,
        "error": error if saved == 0 else None,
        "cache": {
            "engine_version": cache.get("engine_version"),
            "cache_storage": cache.get("cache_storage"),
            "analysis_confirm": cache.get("analysis_confirm"),
            "actual_count": cache.get("actual_count"),
            "expected_count": cache.get("expected_count"),
            "round_range": cache.get("round_range"),
            "latest_round": cache.get("latest_round"),
            "target_round": cache.get("target_round"),
            "is_full_history": cache.get("is_full_history"),
            "missing_rounds_count": cache.get("missing_rounds_count"),
            "missing_rounds_sample": cache.get("missing_rounds_sample"),
        },
        "engine_version": ENGINE_VERSION,
    }


# ============================================================================
# RC9 / AI V7 statistical analysis overrides
# - empirical pattern distributions from every available draw
# - multi-window momentum and z-score normalization
# - recent-vs-full pair lift, gap-cycle balance, transition signal
# - walk-forward audit summary (descriptive validation; not a winning guarantee)
# ============================================================================
import math
import statistics


def _mean_sd(values: Sequence[float]) -> Tuple[float, float]:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0, 1.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    return mean, max(1e-9, math.sqrt(var))


def _percentile(values: Sequence[float], q: float) -> float:
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    pos = (len(vals) - 1) * max(0.0, min(1.0, q))
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _window_rate(counter: Counter, size: int, n: int) -> float:
    return float(counter.get(n, 0)) / max(1.0, float(size) * 6.0 / 45.0)


def _pattern_signature(draw: Dict[str, Any]) -> Dict[str, Any]:
    nums = _parse_nums(draw.get("n"))
    sig = _signature(nums)
    gaps = [nums[i] - nums[i-1] for i in range(1, len(nums))]
    return {
        **sig,
        "span": nums[-1] - nums[0] if len(nums) == 6 else 0,
        "gap_mean": round(sum(gaps) / len(gaps), 3) if gaps else 0,
        "low": sum(n <= 22 for n in nums),
        "high": sum(n >= 23 for n in nums),
    }


def _build_cache(target_round: Optional[int] = None) -> Dict[str, Any]:
    draws = _load_draws()
    if not draws:
        cache = {"engine_version": ENGINE_VERSION, "draw_count": 0, "latest_round": 0,
                 "target_round": _resolve_target_round(target_round, 0), "error": "당첨번호 DB가 비어 있습니다."}
        _write_cache_to_db(cache)
        return cache

    latest_round = max(int(d["r"]) for d in draws)
    target = _resolve_target_round(target_round, latest_round)
    coverage = _coverage(draws, target)
    windows = {10: draws[:10], 20: draws[:20], 30: draws[:30], 50: draws[:50], 100: draws[:100], 300: draws[:300]}
    counters = {k: Counter(_flatten(v)) for k, v in windows.items()}
    freq_all = Counter(_flatten(draws))
    gaps = _number_gaps(draws)

    pair_all, pair100, pair30, triple300 = Counter(), Counter(), Counter(), Counter()
    for d in draws:
        pair_all.update(tuple(sorted(p)) for p in itertools.combinations(d["n"], 2))
    for d in windows[100]:
        pair100.update(tuple(sorted(p)) for p in itertools.combinations(d["n"], 2))
    for d in windows[30]:
        pair30.update(tuple(sorted(p)) for p in itertools.combinations(d["n"], 2))
    for d in windows[300]:
        triple300.update(tuple(sorted(t)) for t in itertools.combinations(d["n"], 3))

    # Number-level standardized signals. Each window is normalized so a long history
    # cannot overwhelm a recent movement merely because it has more rows.
    z_by_window: Dict[int, Dict[int, float]] = {}
    for w, counter in counters.items():
        vals = [float(counter.get(n, 0)) for n in range(1, 46)]
        mean, sd = _mean_sd(vals)
        z_by_window[w] = {n: (counter.get(n, 0) - mean) / sd for n in range(1, 46)}
    all_vals = [float(freq_all.get(n, 0)) for n in range(1, 46)]
    all_mean, all_sd = _mean_sd(all_vals)
    z_all = {n: (freq_all.get(n, 0) - all_mean) / all_sd for n in range(1, 46)}

    # Gap is capped and centered; overdue numbers are represented but never treated
    # as "due" in a deterministic sense.
    gap_vals = [min(30, gaps.get(n, 0)) for n in range(1, 46)]
    gap_mean, gap_sd = _mean_sd(gap_vals)
    gap_z = {n: (min(30, gaps.get(n, 0)) - gap_mean) / gap_sd for n in range(1, 46)}

    latest_set = set(draws[0]["n"])
    previous_set = set(draws[1]["n"]) if len(draws) > 1 else set()
    transition = Counter()
    for newer, older in zip(draws[:-1], draws[1:]):
        for a in older["n"]:
            for b in newer["n"]:
                if a != b:
                    transition[(a, b)] += 1

    score_map: Dict[int, float] = {}
    signal_map: Dict[int, Dict[str, float]] = {}
    for n in range(1, 46):
        momentum = (z_by_window[10][n] * 0.16 + z_by_window[20][n] * 0.19 +
                    z_by_window[30][n] * 0.18 + z_by_window[50][n] * 0.16 +
                    z_by_window[100][n] * 0.13 + z_all[n] * 0.08)
        cycle = max(-1.5, min(1.5, gap_z[n])) * 0.14
        transition_score = sum(transition.get((a, n), 0) for a in latest_set) / max(1, len(draws) - 1)
        transition_score = min(1.5, transition_score * 8.0)
        repeat_penalty = -0.22 if n in latest_set else (-0.06 if n in previous_set else 0.0)
        composite = momentum + cycle + transition_score * 0.08 + repeat_penalty
        signal_map[n] = {
            "z10": round(z_by_window[10][n], 4), "z20": round(z_by_window[20][n], 4),
            "z30": round(z_by_window[30][n], 4), "z50": round(z_by_window[50][n], 4),
            "z100": round(z_by_window[100][n], 4), "z_all": round(z_all[n], 4),
            "gap_z": round(gap_z[n], 4), "transition": round(transition_score, 4),
            "composite": round(composite, 4),
        }
        score_map[n] = round(50.0 + composite * 12.0, 4)

    pattern_rows = [_pattern_signature(d) for d in draws]
    pattern_fields = ["sum", "ac", "span", "gap_mean", "odd", "cons", "end_dup", "low"]
    pattern_stats: Dict[str, Any] = {}
    for field in pattern_fields:
        vals = [float(r[field]) for r in pattern_rows]
        mean, sd = _mean_sd(vals)
        pattern_stats[field] = {
            "mean": round(mean, 4), "sd": round(sd, 4),
            "p05": round(_percentile(vals, .05), 4), "p10": round(_percentile(vals, .10), 4),
            "p25": round(_percentile(vals, .25), 4), "p50": round(_percentile(vals, .50), 4),
            "p75": round(_percentile(vals, .75), 4), "p90": round(_percentile(vals, .90), 4),
            "p95": round(_percentile(vals, .95), 4),
        }

    # Recent-vs-history lift ranks co-occurrence without claiming causal prediction.
    pair_lift = []
    for pair, recent_count in pair100.items():
        expected_recent = pair_all.get(pair, 0) * min(100, len(draws)) / max(1, len(draws))
        lift = (recent_count + 1.0) / (expected_recent + 1.0)
        pair_lift.append((pair, recent_count, pair_all.get(pair, 0), lift))
    pair_lift.sort(key=lambda x: (-x[3], -x[1], x[0]))

    hot = sorted(range(1, 46), key=lambda n: (-score_map[n], n))
    cold = sorted(range(1, 46), key=lambda n: (score_map[n], n))
    overdue = sorted(range(1, 46), key=lambda n: (-gaps.get(n, 0), n))
    mid_avg = sum(score_map.values()) / 45
    mid = sorted(range(1, 46), key=lambda n: (abs(score_map[n] - mid_avg), n))

    cache = {
        "engine_version": ENGINE_VERSION,
        "cache_storage": "database.ai_analysis_cache",
        "created_at": int(time.time()), "draw_count": len(draws), "latest_round": latest_round,
        "next_round": latest_round + 1, "target_round": target,
        "round_range": coverage.get("round_range"), "is_full_history": bool(coverage.get("is_full_history")),
        "missing_rounds_count": int(coverage.get("missing_count") or 0),
        "missing_rounds_sample": coverage.get("missing_sample") or [],
        "expected_count": coverage.get("expected_count"), "actual_count": coverage.get("actual_count"),
        "analysis_confirm": f"1회차~{latest_round}회차 실데이터 분석: {'완료' if coverage.get('is_full_history') else '누락 있음'}",
        "hot": hot, "cold": cold, "overdue": overdue, "mid": mid,
        "score_map": {str(k): v for k, v in score_map.items()},
        "signal_map": {str(k): v for k, v in signal_map.items()},
        "gap": {str(k): int(v) for k, v in gaps.items()},
        "frequency_all": {str(n): int(freq_all.get(n, 0)) for n in range(1, 46)},
        **{f"frequency{w}": {str(n): int(counters[w].get(n, 0)) for n in range(1, 46)} for w in windows},
        "pair_top": [[list(k), int(v)] for k, v in pair_all.most_common(150)],
        "pair_recent_top": [[list(k), int(v)] for k, v in pair100.most_common(120)],
        "pair_lift_top": [[list(k), int(r), int(a), round(float(l), 4)] for k, r, a, l in pair_lift[:120]],
        "triple_top": [[list(k), int(v)] for k, v in triple300.most_common(80)],
        "pattern_stats": pattern_stats,
        "avg_sum30": round(sum(sum(d["n"]) for d in windows[30]) / max(1, len(windows[30])), 1),
        "avg_ac30": round(sum(_ac(d["n"]) for d in windows[30]) / max(1, len(windows[30])), 1),
        "end_counts": {str(k): int(v) for k, v in Counter(n % 10 for n in _flatten(windows[30])).items()},
        "zone_counts": _zones(_flatten(windows[30])), "latest": draws[0],
        "methodology": [
            "전체회차 빈도 표준화", "최근 10·20·30·50·100회 모멘텀", "미출현 간격의 제한적 보정",
            "최근/누적 동반출현 리프트", "합계·AC·홀짝·구간·간격의 실증 분포", "조합 간 중복 최소화"
        ],
        "disclaimer": "통계 분석은 과거 데이터의 구조를 설명할 뿐 미래 당첨을 보장하지 않습니다.",
    }
    _write_cache_to_db(cache)
    return cache


def _empirical_fit(value: float, stats: Dict[str, Any], weight: float) -> float:
    mean, sd = float(stats.get("mean", 0)), max(1e-6, float(stats.get("sd", 1)))
    z = abs((float(value) - mean) / sd)
    return weight * max(-1.0, 1.0 - z / 2.2)


def _weights(cache: Dict[str, Any], mode: str, grade: str) -> Dict[int, float]:
    smap = {int(k): float(v) for k, v in (cache.get("score_map") or {}).items()}
    avg, sd = _mean_sd(list(smap.values()))
    weights = {}
    for n in range(1, 46):
        z = (smap.get(n, avg) - avg) / sd
        # Softmax-like bounded weighting: no number becomes effectively impossible.
        w = math.exp(max(-1.4, min(1.4, z)) * 0.42)
        if mode == "conservative" and 10 <= n <= 36:
            w *= 1.05
        elif mode == "aggressive" and (n <= 12 or n >= 34):
            w *= 1.05
        if grade == "1등":
            w = 0.92 * w + 0.08
        elif grade == "2등":
            w = 0.96 * w + 0.04
        weights[n] = max(0.35, min(2.4, w))
    return weights


def _combo_score(nums: Sequence[int], cache: Dict[str, Any], mode: str, grade: str) -> Tuple[float, List[str], Dict[str, Any]]:
    nums = sorted(nums)
    sig = _signature(nums)
    gaps_arr = [nums[i] - nums[i-1] for i in range(1, 6)]
    sig["span"] = nums[-1] - nums[0]
    sig["gap_mean"] = sum(gaps_arr) / 5.0
    sig["low"] = sum(n <= 22 for n in nums)
    pstats = cache.get("pattern_stats") or {}
    smap = {int(k): float(v) for k, v in (cache.get("score_map") or {}).items()}
    smean, ssd = _mean_sd(list(smap.values()))

    score = 72.0
    for field, weight in [("sum", 5.0), ("ac", 4.0), ("span", 3.0), ("gap_mean", 3.0), ("odd", 3.0), ("low", 2.0)]:
        if field in pstats:
            score += _empirical_fit(sig[field], pstats[field], weight)
    number_signal = sum((smap.get(n, smean) - smean) / ssd for n in nums) / 6.0
    score += max(-4.0, min(4.0, number_signal * 2.2))

    lift_map = {tuple(item[0]): float(item[3]) for item in cache.get("pair_lift_top", []) if len(item) >= 4}
    lifts = [lift_map.get(tuple(sorted(p)), 1.0) for p in itertools.combinations(nums, 2)]
    useful_lifts = [l for l in lifts if l > 1.0]
    score += min(4.5, sum(min(1.0, l - 1.0) for l in useful_lifts) * 0.45)

    # Structural penalties use broad empirical limits, avoiding overfitting to one pattern.
    if sig["cons"] > 1: score -= 4.5
    if sig["end_dup"] > 2: score -= 4.0
    if max(sig["zones"]) > 3 or min(sig["zones"]) == 0: score -= 5.0
    latest = set((cache.get("latest") or {}).get("n") or [])
    overlap_latest = len(set(nums) & latest)
    if overlap_latest >= 4: score -= 5.0
    elif overlap_latest == 3: score -= 1.5
    if grade == "1등": score += 1.0
    elif grade == "2등": score += 0.5
    score = round(max(60.0, min(98.8, score)), 1)

    reasons = [
        f"전체·최근 다중구간 신호 {number_signal:+.2f}",
        f"실증분포 적합: 합계 {sig['sum']} · AC {sig['ac']} · 홀짝 {sig['odd']}:{6-sig['odd']}",
        f"최근/누적 동반출현 리프트 {len(useful_lifts)}개 반영",
        f"구간 {sig['zones'][0]}-{sig['zones'][1]}-{sig['zones'][2]} · 번호폭 {sig['span']}",
    ]
    return score, reasons, sig


def _valid(nums: Sequence[int]) -> bool:
    if len(set(nums)) != 6:
        return False
    sig = _signature(nums)
    arr = sorted(nums)
    span = arr[-1] - arr[0]
    # Broad historical plausibility filters only; selection remains diverse.
    if sig["odd"] not in (2, 3, 4): return False
    if min(sig["zones"]) == 0 or max(sig["zones"]) > 3: return False
    if not (90 <= sig["sum"] <= 190): return False
    if not (5 <= sig["ac"] <= 10): return False
    if sig["cons"] > 1 or sig["end_dup"] > 2: return False
    if not (22 <= span <= 44): return False
    return True


def rc9_audit() -> Dict[str, Any]:
    """Return a reproducible integrity audit of the loaded history and engine features."""
    cache = get_analysis_cache(False)
    draws = _load_draws()
    rounds = sorted(int(d["r"]) for d in draws)
    duplicate_rounds = len(rounds) - len(set(rounds))
    invalid_rows = sum(1 for d in draws if len(_parse_nums(d.get("n"))) != 6)
    return {
        "engine_version": ENGINE_VERSION,
        "round_range": cache.get("round_range"), "draw_count": len(draws),
        "is_full_history": cache.get("is_full_history", False),
        "missing_rounds_count": cache.get("missing_rounds_count", 0),
        "duplicate_rounds": duplicate_rounds, "invalid_draw_rows": invalid_rows,
        "latest_round": cache.get("latest_round", 0), "next_round": cache.get("next_round", 0),
        "features": cache.get("methodology", []),
        "cache_storage": cache.get("cache_storage"),
        "disclaimer": cache.get("disclaimer"),
    }

# ===================== STABLE-11 DYNAMIC PORTFOLIO & EXPLAINABLE ENGINE =====================
# 기존 통계/캐시/후보 생성은 그대로 사용하고 최종 조합의 다양성과 설명 데이터를 강화한다.
_STABLE11_BASE_MAKE_PREMIUM_COMBOS = make_premium_combos
STABLE11_ENGINE_VERSION = "BBLOTTO_STABLE_11_FAST_DYNAMIC_EXPLAINABLE"


def _stable11_archetype(nums: Sequence[int], detail: Dict[str, Any], cache: Dict[str, Any]) -> str:
    sig = _signature(nums)
    hot = set((cache.get("hot") or [])[:14])
    overdue = set((cache.get("overdue") or [])[:14])
    hot_count = len(set(nums) & hot)
    overdue_count = len(set(nums) & overdue)
    if hot_count >= 3 and overdue_count >= 2:
        return "흐름혼합형"
    if overdue_count >= 3:
        return "반등분산형"
    if hot_count >= 3:
        return "상승흐름형"
    if sig["odd"] == 3 and max(sig["zones"]) <= 2 and 6 <= sig["ac"] <= 10:
        return "정밀균형형"
    if sig["sum"] <= 125:
        return "저중심확장형"
    if sig["sum"] >= 165:
        return "중고분산형"
    if sig["cons"] == 1:
        return "연속수혼합형"
    return "구간분산형"


def _stable11_number_evidence(n: int, cache: Dict[str, Any]) -> str:
    freq10 = int((cache.get("frequency10") or {}).get(str(n), 0))
    freq30 = int((cache.get("frequency30") or {}).get(str(n), 0))
    freq100 = int((cache.get("frequency100") or {}).get(str(n), 0))
    gap = int((cache.get("gap") or {}).get(str(n), 0))
    hot_rank = {v: i + 1 for i, v in enumerate(cache.get("hot") or [])}
    overdue_rank = {v: i + 1 for i, v in enumerate(cache.get("overdue") or [])}
    if n in hot_rank and hot_rank[n] <= 12:
        return f"최근 10·30·100회 통합 신호 상위권(최근30회 {freq30}회)"
    if n in overdue_rank and overdue_rank[n] <= 12:
        return f"최근 {gap}회 공백을 반영한 반등 후보"
    if freq10 >= 2:
        return f"최근 10회 {freq10}회 출현한 단기 흐름 후보"
    if freq100 >= 14:
        return f"최근 100회 {freq100}회 출현한 장기 안정 후보"
    return f"단기 빈도와 미출현 간격을 함께 고려한 보완 후보"


def _stable11_portfolio_value(combo: Sequence[int], detail: Dict[str, Any], selected: List[List[int]], usage: Counter, archetype_usage: Counter, cache: Dict[str, Any]) -> float:
    value = float(detail.get("score") or detail.get("ai_score") or 0)
    combo_set = set(combo)
    for prev in selected:
        overlap = len(combo_set & set(prev))
        value -= {0: 0, 1: 0.1, 2: 0.8, 3: 4.2, 4: 15.0, 5: 40.0, 6: 100.0}.get(overlap, 100.0)
    value -= sum(usage[n] * 0.72 + max(0, usage[n] - 1) * 1.35 for n in combo)
    archetype = _stable11_archetype(combo, detail, cache)
    value -= archetype_usage[archetype] * 2.4
    sig = _signature(combo)
    if sig["odd"] == 3: value += 0.7
    if max(sig["zones"]) <= 2: value += 0.9
    if len({n % 10 for n in combo}) >= 5: value += 0.6
    if 115 <= sig["sum"] <= 170: value += 0.5
    return value


def make_premium_combos(count: int = 10, fixed: Any = "", excluded: Any = "", mode: str = "balanced", member_grade: str = "일반", member_id: Optional[int] = None):
    target = max(1, min(50, int(count or 10)))
    # 최종 요청 수보다 넓은 후보군을 만든 뒤 포트폴리오 단위로 다시 선별한다.
    candidate_count = min(50, max(target, 18 if target <= 10 else int(target * 1.5)))
    combos, details, st = _STABLE11_BASE_MAKE_PREMIUM_COMBOS(candidate_count, fixed, excluded, mode, member_grade, member_id=member_id)
    cache = get_analysis_cache(False)
    detail_map = {tuple(sorted(d.get("numbers") or [])): dict(d) for d in (details or [])}
    pool: List[Tuple[List[int], Dict[str, Any]]] = []
    seen = set()
    for combo in combos or []:
        key = tuple(sorted(int(n) for n in combo))
        if len(key) == 6 and key not in seen:
            seen.add(key)
            pool.append((list(key), detail_map.get(key, {"numbers": list(key), "score": 0})))

    selected: List[List[int]] = []
    selected_details: List[Dict[str, Any]] = []
    usage: Counter = Counter()
    archetype_usage: Counter = Counter()
    while pool and len(selected) < target:
        ranked = sorted(
            ((_stable11_portfolio_value(c, d, selected, usage, archetype_usage, cache), c, d) for c, d in pool),
            key=lambda x: (-x[0], x[1]),
        )
        _, combo, detail = ranked[0]
        pool = [(c, d) for c, d in pool if c != combo]
        selected.append(combo)
        usage.update(combo)
        archetype = _stable11_archetype(combo, detail, cache)
        archetype_usage[archetype] += 1
        sig = _signature(combo)
        # STABLE-13: 설명 엔진이 추측하지 않도록 생성 시점의 실제 통계 근거를 구조화해 함께 저장한다.
        pair_counts = {}
        for item in cache.get("pair_recent_top") or cache.get("pair_top") or []:
            try:
                pair, cnt = item[0], item[1]
                pair_counts[tuple(sorted(int(x) for x in pair))] = int(cnt)
            except Exception:
                continue
        hot_rank = {int(v): i + 1 for i, v in enumerate(cache.get("hot") or [])}
        overdue_rank = {int(v): i + 1 for i, v in enumerate(cache.get("overdue") or [])}
        score_map = cache.get("score_map") or {}
        evidence = []
        for n in combo:
            partners = sorted(
                ((m, pair_counts.get(tuple(sorted((n, m))), 0)) for m in combo if m != n),
                key=lambda x: (-x[1], x[0]),
            )[:2]
            evidence.append({
                "number": n,
                "reason": _stable11_number_evidence(n, cache),
                "freq10": int((cache.get("frequency10") or {}).get(str(n), 0)),
                "freq30": int((cache.get("frequency30") or {}).get(str(n), 0)),
                "freq100": int((cache.get("frequency100") or {}).get(str(n), 0)),
                "gap": int((cache.get("gap") or {}).get(str(n), 0)),
                "hot_rank": hot_rank.get(n),
                "overdue_rank": overdue_rank.get(n),
                "selection_score": round(float(score_map.get(str(n), score_map.get(n, 0)) or 0), 3),
                "partners": [{"number": m, "count": c} for m, c in partners if c > 0],
                "role": ("강세수" if hot_rank.get(n, 99) <= 12 else "반등수" if overdue_rank.get(n, 99) <= 12 else "균형수"),
            })
        hot = set((cache.get("hot") or [])[:14])
        overdue = set((cache.get("overdue") or [])[:14])
        reason_lines = [
            f"{archetype}: 저·중·고 구간 {sig['zones'][0]}-{sig['zones'][1]}-{sig['zones'][2]}, 홀짝 {sig['odd']}:{6-sig['odd']}",
            f"합계 {sig['sum']} · AC {sig['ac']} · 끝수 {len({n % 10 for n in combo})}종으로 구조 균형 확보",
            f"최근 흐름 후보 {len(set(combo)&hot)}개와 미출현 보완 후보 {len(set(combo)&overdue)}개를 혼합",
        ]
        detail.update({
            "numbers": combo,
            "engine_version": STABLE11_ENGINE_VERSION,
            "engine": STABLE11_ENGINE_VERSION,
            "type": archetype,
            "strategy": archetype,
            "portfolio_type": archetype,
            "number_evidence": evidence,
            "reasons": reason_lines,
            "reason": " / ".join(reason_lines),
            "sum": sig["sum"], "odd": sig["odd"], "even": 6-sig["odd"], "ac": sig["ac"], "zones": sig["zones"],
        })
        selected_details.append(detail)

    st.update({
        "engine_version": STABLE11_ENGINE_VERSION,
        "stable11": True,
        "stable11_candidate_count": len(combos or []),
        "stable11_unique_numbers": len(usage),
        "stable11_max_number_use": max(usage.values(), default=0),
        "stable11_archetypes": dict(archetype_usage),
        "methodology": [
            "최근 10·30·100회와 전체 누적 출현 신호", "미출현 간격", "동반출현", "홀짝·구간·합계·AC·끝수",
            "조합 간 번호 중복과 전략 유형 분산", "번호별 선택 근거 자동 생성",
        ],
    })
    return selected[:target], selected_details[:target], st
# ===================== /STABLE-11 DYNAMIC PORTFOLIO & EXPLAINABLE ENGINE =====================
