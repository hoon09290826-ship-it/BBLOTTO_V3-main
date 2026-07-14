from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CACHE_ENGINE_VERSION = "BBLOTTO_AI_CACHE_V13_04"
_CACHE_KEY = "full_history_statistics"
_LOCK = threading.RLock()
_MEMORY: Dict[str, Any] = {}
_REFRESH_THREAD: Optional[threading.Thread] = None
_REFRESH_REQUESTED = threading.Event()
_STOP_REQUESTED = threading.Event()
_SIGNATURE_TTL_SECONDS = max(5, int(os.getenv("BBLOTTO_AI_SIGNATURE_TTL", "30") or 30))


def _normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if not value or value.startswith("${{"):
        return ""
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://"):]
    return value


def _database_url() -> str:
    direct = os.getenv("DATABASE_URL", "") or os.getenv("POSTGRES_URL", "")
    if direct:
        return _normalize_database_url(direct)
    host = os.getenv("PGHOST", "").strip()
    user = os.getenv("PGUSER", "").strip() or os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("PGPASSWORD", "").strip() or os.getenv("POSTGRES_PASSWORD", "").strip()
    name = os.getenv("PGDATABASE", "").strip() or os.getenv("POSTGRES_DB", "").strip()
    port = os.getenv("PGPORT", "5432").strip() or "5432"
    if host and user and name:
        return f"postgresql://{urllib.parse.quote(user)}:{urllib.parse.quote(password)}@{host}:{port}/{name}"
    return ""


def _sqlite_path() -> Path:
    directory = os.getenv("BBLOTTO_DB_DIR", "").strip()
    if directory:
        return Path(directory).expanduser().resolve() / "bblotto_v34.db"
    return (Path(__file__).resolve().parents[2] / "database" / "bblotto_v34.db").resolve()


def _parse_numbers(value: Any) -> List[int]:
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value or "").replace("[", " ").replace("]", " ").replace(",", " ").split()
    result: List[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 45 and number not in result:
            result.append(number)
    return sorted(result)


def _source_signature() -> Tuple[str, int, int, int]:
    url = _database_url()
    if url:
        try:
            import psycopg2
            with psycopg2.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(MIN(round_no),0), COALESCE(MAX(round_no),0), COUNT(*) FROM draws")
                    first_round, latest_round, count = cur.fetchone()
            return "postgresql", int(first_round), int(latest_round), int(count)
        except Exception:
            return "postgresql", 0, 0, 0
    path = _sqlite_path()
    if not path.exists():
        return "sqlite", 0, 0, 0
    try:
        with sqlite3.connect(str(path), timeout=15) as conn:
            row = conn.execute("SELECT COALESCE(MIN(round_no),0), COALESCE(MAX(round_no),0), COUNT(*) FROM draws").fetchone()
        return "sqlite", int(row[0]), int(row[1]), int(row[2])
    except sqlite3.DatabaseError:
        return "sqlite", 0, 0, 0


def _fetch_draws(after_round: int = 0) -> List[Dict[str, Any]]:
    url = _database_url()
    rows: Sequence[Sequence[Any]]
    if url:
        import psycopg2
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT round_no, draw_date, numbers, bonus FROM draws WHERE round_no > %s ORDER BY round_no",
                    (int(after_round),),
                )
                rows = cur.fetchall()
    else:
        path = _sqlite_path()
        if not path.exists():
            return []
        with sqlite3.connect(str(path), timeout=15) as conn:
            rows = conn.execute(
                "SELECT round_no, draw_date, numbers, bonus FROM draws WHERE round_no > ? ORDER BY round_no",
                (int(after_round),),
            ).fetchall()
    draws: List[Dict[str, Any]] = []
    for round_no, draw_date, numbers, bonus in rows:
        parsed = _parse_numbers(numbers)
        if len(parsed) == 6:
            draws.append({
                "round": int(round_no),
                "date": str(draw_date or ""),
                "numbers": parsed,
                "bonus": int(bonus or 0),
            })
    return draws



def _source_rounds() -> List[int]:
    """Return every valid round number currently stored in the primary draws table."""
    url = _database_url()
    if url:
        try:
            import psycopg2
            with psycopg2.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT round_no FROM draws ORDER BY round_no")
                    return [int(row[0]) for row in cur.fetchall() if int(row[0] or 0) > 0]
        except Exception:
            return []
    path = _sqlite_path()
    if not path.exists():
        return []
    try:
        with sqlite3.connect(str(path), timeout=15) as conn:
            return [int(row[0]) for row in conn.execute("SELECT round_no FROM draws ORDER BY round_no").fetchall() if int(row[0] or 0) > 0]
    except sqlite3.DatabaseError:
        return []


def _official_fetch(round_no: int, timeout: int = 5) -> Optional[Dict[str, Any]]:
    """Fetch one official draw. Used only by the administrator repair action."""
    url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={int(round_no)}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BBLOTTO/13"})
        with urllib.request.urlopen(request, timeout=max(2, int(timeout))) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("returnValue") != "success":
            return None
        numbers = [int(data[f"drwtNo{i}"]) for i in range(1, 7)]
        if len(numbers) != 6:
            return None
        return {
            "round": int(data["drwNo"]),
            "date": str(data.get("drwNoDate") or ""),
            "numbers": sorted(numbers),
            "bonus": int(data.get("bnusNo") or 0),
        }
    except Exception:
        return None


def _save_repaired_draws(draws: Sequence[Dict[str, Any]]) -> int:
    if not draws:
        return 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    url = _database_url()
    if url:
        import psycopg2
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                for draw in draws:
                    cur.execute(
                        """
                        INSERT INTO draws(round_no,draw_date,numbers,bonus,source,updated_at)
                        VALUES(%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(round_no) DO UPDATE SET
                          draw_date=EXCLUDED.draw_date,
                          numbers=EXCLUDED.numbers,
                          bonus=EXCLUDED.bonus,
                          source=EXCLUDED.source,
                          updated_at=EXCLUDED.updated_at
                        """,
                        (draw["round"], draw.get("date", ""), json.dumps(draw["numbers"]), draw.get("bonus", 0), "official_repair", now),
                    )
        return len(draws)
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path), timeout=20) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS draws(round_no INTEGER PRIMARY KEY, draw_date TEXT DEFAULT '', numbers TEXT, bonus INTEGER, source TEXT DEFAULT 'manual', updated_at TEXT)")
        conn.executemany(
            "INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)",
            [(d["round"], d.get("date", ""), json.dumps(d["numbers"]), d.get("bonus", 0), "official_repair", now) for d in draws],
        )
    return len(draws)


def repair_missing_history(max_round: Optional[int] = None, chunk_size: int = 25) -> Dict[str, Any]:
    """Fill a bounded batch of missing source draws, then rebuild the analysis cache.

    The endpoint calls this repeatedly, avoiding a single long request while still
    repairing old partial databases such as 1131~1232-only installations.
    """
    rounds = _source_rounds()
    latest = int(max_round or (max(rounds) if rounds else 0))
    if latest <= 0:
        payload = refresh_cache(force=True)
        return {"ok": True, "saved": 0, "completed": False, "cache": payload, "message": "당첨 회차 데이터가 없습니다."}
    existing = set(rounds)
    missing = [round_no for round_no in range(1, latest + 1) if round_no not in existing]
    batch = missing[:max(1, min(int(chunk_size or 25), 100))]
    fetched: List[Dict[str, Any]] = []
    if batch:
        workers = min(8, len(batch))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bblotto-history-repair") as executor:
            futures = {executor.submit(_official_fetch, round_no): round_no for round_no in batch}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    fetched.append(result)
        fetched.sort(key=lambda item: item["round"])
        _save_repaired_draws(fetched)
    payload = refresh_cache(force=True)
    remaining = int(payload.get("missing_rounds_count", 0) or 0)
    return {
        "ok": True,
        "saved": len(fetched),
        "requested": len(batch),
        "completed": remaining == 0 and bool(payload.get("is_full_history")),
        "remaining": remaining,
        "cache": payload,
        "message": "전체 회차 복구 완료" if remaining == 0 else f"누락 회차 복구 중: {remaining}개 남음",
    }


def _ensure_cache_table() -> None:
    url = _database_url()
    if url:
        import psycopg2
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_analysis_cache (
                        cache_key TEXT PRIMARY KEY,
                        engine_version TEXT NOT NULL,
                        latest_round INTEGER NOT NULL DEFAULT 0,
                        draw_count INTEGER NOT NULL DEFAULT 0,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        return
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path), timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_analysis_cache (
                cache_key TEXT PRIMARY KEY,
                engine_version TEXT NOT NULL,
                latest_round INTEGER NOT NULL DEFAULT 0,
                draw_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _load_persisted() -> Optional[Dict[str, Any]]:
    _ensure_cache_table()
    url = _database_url()
    row: Optional[Sequence[Any]]
    if url:
        import psycopg2
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM ai_analysis_cache WHERE cache_key=%s", (_CACHE_KEY,))
                row = cur.fetchone()
    else:
        with sqlite3.connect(str(_sqlite_path()), timeout=15) as conn:
            row = conn.execute("SELECT payload FROM ai_analysis_cache WHERE cache_key=?", (_CACHE_KEY,)).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_persisted(payload: Dict[str, Any]) -> None:
    _ensure_cache_table()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    now = dt.datetime.now().isoformat(timespec="seconds")
    latest = int(payload.get("latest_round", 0))
    count = int(payload.get("draw_count", 0))
    url = _database_url()
    if url:
        import psycopg2
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_analysis_cache(cache_key,engine_version,latest_round,draw_count,payload,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(cache_key) DO UPDATE SET
                      engine_version=EXCLUDED.engine_version,
                      latest_round=EXCLUDED.latest_round,
                      draw_count=EXCLUDED.draw_count,
                      payload=EXCLUDED.payload,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (_CACHE_KEY, CACHE_ENGINE_VERSION, latest, count, encoded, now),
                )
        return
    with sqlite3.connect(str(_sqlite_path()), timeout=15) as conn:
        conn.execute(
            """
            INSERT INTO ai_analysis_cache(cache_key,engine_version,latest_round,draw_count,payload,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
              engine_version=excluded.engine_version,
              latest_round=excluded.latest_round,
              draw_count=excluded.draw_count,
              payload=excluded.payload,
              updated_at=excluded.updated_at
            """,
            (_CACHE_KEY, CACHE_ENGINE_VERSION, latest, count, encoded, now),
        )


def _ac(numbers: Sequence[int]) -> int:
    return len({b - a for a, b in combinations(sorted(numbers), 2)}) - 5


def _signature(numbers: Sequence[int]) -> Dict[str, Any]:
    nums = sorted(numbers)
    odd = sum(n % 2 for n in nums)
    zones = [sum(n <= 15 for n in nums), sum(16 <= n <= 30 for n in nums), sum(n >= 31 for n in nums)]
    return {
        "sum": sum(nums), "odd": odd, "even": 6 - odd, "zones": zones, "ac": _ac(nums),
        "consecutive": sum(1 for n in nums if n + 1 in set(nums)),
        "end_types": len({n % 10 for n in nums}),
        "max_end_dup": max(Counter(n % 10 for n in nums).values(), default=0),
        "spread": nums[-1] - nums[0],
    }


def _norm(values: Dict[int, float]) -> Dict[int, float]:
    lo, hi = min(values.values(), default=0.0), max(values.values(), default=0.0)
    if math.isclose(lo, hi):
        return {n: 0.5 for n in range(1, 46)}
    return {n: (values.get(n, lo) - lo) / (hi - lo) for n in range(1, 46)}


def _materialize(draws: List[Dict[str, Any]], started: float, update_mode: str, added_count: int) -> Dict[str, Any]:
    latest_round = draws[-1]["round"] if draws else 0
    windows = (10, 30, 50, 100, 300)
    frequencies: Dict[int, Counter] = {
        window: Counter(n for draw in draws[-window:] for n in draw["numbers"])
        for window in windows
    }
    all_frequency = Counter(n for draw in draws for n in draw["numbers"])
    last_seen = {n: -1 for n in range(1, 46)}
    for index, draw in enumerate(draws):
        for number in draw["numbers"]:
            last_seen[number] = index
    gaps = {n: len(draws) if last_seen[n] < 0 else len(draws) - 1 - last_seen[n] for n in range(1, 46)}

    pair_all: Counter = Counter()
    for draw in draws:
        pair_all.update(combinations(draw["numbers"], 2))
    recent = draws[-100:]
    pair_recent: Counter = Counter()
    triple_recent: Counter = Counter()
    for draw in recent:
        pair_recent.update(combinations(draw["numbers"], 2))
        triple_recent.update(combinations(draw["numbers"], 3))

    n10 = _norm({n: frequencies[10][n] / 10 for n in range(1, 46)})
    n30 = _norm({n: frequencies[30][n] / 30 for n in range(1, 46)})
    n100 = _norm({n: frequencies[100][n] / 100 for n in range(1, 46)})
    n300 = _norm({n: frequencies[300][n] / max(1, min(300, len(draws))) for n in range(1, 46)})
    nall = _norm({n: all_frequency[n] / max(1, len(draws)) for n in range(1, 46)})
    ngap = _norm({n: float(gaps[n]) for n in range(1, 46)})
    score_map: Dict[int, float] = {}
    momentum: Dict[int, float] = {}
    for number in range(1, 46):
        change = (n10[number] - n100[number]) * 0.65 + (n30[number] - n300[number]) * 0.35
        momentum[number] = change
        score_map[number] = (
            0.22 * n10[number] + 0.20 * n30[number] + 0.18 * n100[number]
            + 0.10 * n300[number] + 0.08 * nall[number] + 0.14 * ngap[number]
            + 0.08 * max(0.0, min(1.0, 0.5 + change))
        )

    signatures = [_signature(draw["numbers"]) for draw in recent]
    sums = [item["sum"] for item in signatures]
    sum_mean = sum(sums) / len(sums) if sums else 138.0
    sum_sd = math.sqrt(sum((value - sum_mean) ** 2 for value in sums) / len(sums)) if sums else 25.0
    def average(key: str, default: float) -> float:
        return sum(float(item[key]) for item in signatures) / len(signatures) if signatures else default

    ranked = sorted(range(1, 46), key=lambda n: (-score_map[n], n))
    overdue = sorted(range(1, 46), key=lambda n: (-gaps[n], n))
    cold = sorted(range(1, 46), key=lambda n: (frequencies[30][n], frequencies[100][n], n))
    first_round = draws[0]["round"] if draws else 0
    present_rounds = {int(draw["round"]) for draw in draws}
    missing_rounds = [round_no for round_no in range(1, latest_round + 1) if round_no not in present_rounds]
    return {
        "engine_version": CACHE_ENGINE_VERSION,
        "recommendation_engine_version": "",
        "cache_storage": "database+persistent-memory",
        "cache_update_mode": update_mode,
        "incremental_added_rounds": added_count,
        "analysis_confirm": f"1회차부터 {latest_round}회차까지 {len(draws)}개 회차 분석",
        "draw_count": len(draws), "actual_count": len(draws), "expected_count": latest_round,
        "round_range": [first_round, latest_round], "latest_round": latest_round,
        "target_round": latest_round + 1 if latest_round else 1,
        "is_full_history": bool(draws and first_round == 1 and not missing_rounds),
        "missing_rounds_count": len(missing_rounds), "missing_rounds_sample": missing_rounds[:20],
        "frequency10": {str(n): frequencies[10][n] for n in range(1, 46)},
        "frequency30": {str(n): frequencies[30][n] for n in range(1, 46)},
        "frequency50": {str(n): frequencies[50][n] for n in range(1, 46)},
        "frequency100": {str(n): frequencies[100][n] for n in range(1, 46)},
        "frequency300": {str(n): frequencies[300][n] for n in range(1, 46)},
        "frequency_all": {str(n): all_frequency[n] for n in range(1, 46)},
        "gap": {str(n): gaps[n] for n in range(1, 46)},
        "score_map": {str(n): round(score_map[n] * 100, 4) for n in range(1, 46)},
        "momentum": {str(n): round(momentum[n], 5) for n in range(1, 46)},
        "hot": ranked[:15], "cold": cold[:15], "overdue": overdue[:15],
        "pair_top": [[list(pair), count] for pair, count in pair_all.most_common(100)],
        "pair_recent_top": [[list(pair), count] for pair, count in pair_recent.most_common(100)],
        "triple_recent_top": [[list(triple), count] for triple, count in triple_recent.most_common(50)],
        "pair_counts": {f"{a}-{b}": count for (a, b), count in pair_recent.items()},
        "triple_counts": {"-".join(map(str, triple)): count for triple, count in triple_recent.items()},
        "pattern": {
            "sum_mean": round(sum_mean, 2), "sum_sd": round(sum_sd, 2),
            "odd_mean": round(average("odd", 3), 2), "ac_mean": round(average("ac", 7), 2),
            "consecutive_mean": round(average("consecutive", 0.8), 2),
        },
        "latest_numbers": [draw["numbers"] for draw in draws[-12:]],
        # 다음 증분 갱신 때 DB 전체를 재조회하지 않기 위한 최소 원본 상태입니다.
        "_draw_history": draws,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "build_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _refresh(force: bool = False) -> Dict[str, Any]:
    started = time.perf_counter()
    source_engine, first_round, latest_round, count = _source_signature()
    persisted = None if force else _load_persisted()
    history = list((persisted or {}).get("_draw_history") or [])
    cached_latest = int((persisted or {}).get("latest_round", 0))
    cached_count = int((persisted or {}).get("draw_count", 0))
    cached_first = int(history[0].get("round", 0)) if history else 0
    cached_rounds = {int(item.get("round", 0)) for item in history if int(item.get("round", 0)) > 0}
    cached_complete = bool(history and cached_first == 1 and cached_latest > 0 and len(cached_rounds) == cached_latest)
    append_only = bool(
        persisted and cached_complete and cached_count == len(history)
        and first_round == 1 and count >= cached_count and latest_round >= cached_latest
        and (count - cached_count) == (latest_round - cached_latest)
    )
    if append_only:
        added = _fetch_draws(cached_latest)
        if added:
            history.extend(added)
            mode = "incremental"
        else:
            payload = dict(persisted)
            payload["cache_update_mode"] = "cache-hit"
            payload["incremental_added_rounds"] = 0
            payload["build_ms"] = round((time.perf_counter() - started) * 1000, 2)
            payload["source_engine"] = source_engine
            return payload
    else:
        history = _fetch_draws(0)
        added = history
        mode = "full-rebuild"
    payload = _materialize(history, started, mode, len(added))
    payload["source_engine"] = source_engine
    _save_persisted(payload)
    return payload


def refresh_cache(force: bool = False) -> Dict[str, Any]:
    """캐시를 동기 갱신합니다. 관리자 강제 갱신이나 최초 부팅에만 사용합니다."""
    signature = _source_signature()
    payload = _refresh(force=force)
    with _LOCK:
        _MEMORY.clear()
        _MEMORY.update({
            "signature": signature,
            "payload": payload,
            "signature_checked_at": time.monotonic(),
            "refreshing": False,
            "last_error": "",
        })
    return payload


def _background_refresh_worker() -> None:
    with _LOCK:
        _MEMORY["refreshing"] = True
    try:
        signature = _source_signature()
        with _LOCK:
            previous = _MEMORY.get("signature")
            has_payload = bool(_MEMORY.get("payload"))
        if not has_payload or signature != previous:
            payload = _refresh(force=False)
            with _LOCK:
                _MEMORY["signature"] = signature
                _MEMORY["payload"] = payload
                _MEMORY["last_error"] = ""
        with _LOCK:
            _MEMORY["signature_checked_at"] = time.monotonic()
    except Exception as exc:
        with _LOCK:
            _MEMORY["last_error"] = f"{type(exc).__name__}: {exc}"
            _MEMORY["signature_checked_at"] = time.monotonic()
    finally:
        with _LOCK:
            _MEMORY["refreshing"] = False


def request_background_refresh(force_check: bool = False) -> bool:
    """사용자 요청을 막지 않고 새 회차 여부를 백그라운드에서 확인합니다."""
    global _REFRESH_THREAD
    now = time.monotonic()
    with _LOCK:
        checked_at = float(_MEMORY.get("signature_checked_at", 0.0) or 0.0)
        if not force_check and now - checked_at < _SIGNATURE_TTL_SECONDS:
            return False
        if bool(_MEMORY.get("refreshing")):
            return False
        _MEMORY["refreshing"] = True
    thread = threading.Thread(target=_background_refresh_worker, name="bblotto-ai-cache-refresh", daemon=True)
    _REFRESH_THREAD = thread
    thread.start()
    return True


def get_cache_status() -> Dict[str, Any]:
    with _LOCK:
        payload = dict(_MEMORY.get("payload") or {})
        return {
            "engine_version": CACHE_ENGINE_VERSION,
            "latest_round": int(payload.get("latest_round", 0) or 0),
            "draw_count": int(payload.get("draw_count", 0) or 0),
            "refreshing": bool(_MEMORY.get("refreshing")),
            "last_error": str(_MEMORY.get("last_error", "") or ""),
            "signature_ttl_seconds": _SIGNATURE_TTL_SECONDS,
        }


def get_analysis_cache(
    force: bool = False,
    target_round: Optional[int] = None,
    recommendation_engine_version: str = "",
) -> Dict[str, Any]:
    # 최초 1회만 동기로 구성하고 이후에는 stale-while-revalidate 방식으로 즉시 반환합니다.
    with _LOCK:
        has_payload = bool(_MEMORY.get("payload"))
    if force or not has_payload:
        refresh_cache(force=force)
    else:
        request_background_refresh(force_check=False)

    with _LOCK:
        result = dict(_MEMORY.get("payload") or {})
        result["background_refreshing"] = bool(_MEMORY.get("refreshing"))
        result["cache_last_error"] = str(_MEMORY.get("last_error", "") or "")
    result.pop("_draw_history", None)
    result["recommendation_engine_version"] = recommendation_engine_version
    if target_round:
        result["target_round"] = int(target_round)
    return result
