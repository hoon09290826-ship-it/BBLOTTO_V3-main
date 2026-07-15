from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..recommendation_engine import ENGINE_VERSION, build_backtest_cache, make_premium_combos

BACKTEST_VERSION = "BBLOTTO_BACKTEST_RC6_A"
DEFAULT_COMBO_COUNT = 10
DEFAULT_MIN_HISTORY = 1
MAX_STEP_SIZE = 5


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_numbers(value: Any) -> List[int]:
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        text = str(value or "").replace("[", " ").replace("]", " ").replace(",", " ")
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


def ensure_backtest_tables(c: Any) -> None:
    c.execute(
        "CREATE TABLE IF NOT EXISTS backtest_runs("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'ready', "
        "start_round INTEGER DEFAULT 1, end_round INTEGER DEFAULT 0, next_round INTEGER DEFAULT 1, "
        "combo_count INTEGER DEFAULT 10, min_history INTEGER DEFAULT 1, mode TEXT DEFAULT 'balanced', "
        "engine_version TEXT DEFAULT '', backtest_version TEXT DEFAULT '', total_rounds INTEGER DEFAULT 0, "
        "processed_rounds INTEGER DEFAULT 0, success_rounds INTEGER DEFAULT 0, failed_rounds INTEGER DEFAULT 0, "
        "skipped_rounds INTEGER DEFAULT 0, created_by INTEGER DEFAULT 0, created_at TEXT DEFAULT '', "
        "started_at TEXT DEFAULT '', completed_at TEXT DEFAULT '', updated_at TEXT DEFAULT '', error_message TEXT DEFAULT ''"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS backtest_results("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, target_round INTEGER NOT NULL, "
        "history_from INTEGER DEFAULT 0, history_to INTEGER DEFAULT 0, history_count INTEGER DEFAULT 0, "
        "mode TEXT DEFAULT 'balanced', engine_version TEXT DEFAULT '', seed TEXT DEFAULT '', "
        "winning_numbers TEXT DEFAULT '[]', bonus INTEGER DEFAULT 0, recommended_numbers TEXT DEFAULT '[]', "
        "details_json TEXT DEFAULT '[]', best_match INTEGER DEFAULT 0, best_rank TEXT DEFAULT '낙첨', "
        "match_distribution TEXT DEFAULT '{}', pool_match_count INTEGER DEFAULT 0, pool_numbers TEXT DEFAULT '[]', "
        "avg_combo_score REAL DEFAULT 0, max_combo_score REAL DEFAULT 0, generation_ms REAL DEFAULT 0, "
        "status TEXT DEFAULT 'ok', error_message TEXT DEFAULT '', created_at TEXT DEFAULT ''"
        ")"
    )
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_results_run_round "
        "ON backtest_results(run_id,target_round)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_backtest_results_round "
        "ON backtest_results(target_round)"
    )


def load_draws(c: Any) -> List[Dict[str, Any]]:
    rows = c.execute("SELECT round_no,draw_date,numbers,bonus FROM draws ORDER BY round_no").fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        nums = _parse_numbers(row["numbers"])
        if len(nums) != 6:
            continue
        out.append({
            "round": int(row["round_no"]),
            "date": row["draw_date"] or "",
            "numbers": nums,
            "bonus": int(row["bonus"] or 0),
        })
    return out


def _rank(match_count: int, bonus_match: bool) -> str:
    if match_count == 6:
        return "1등"
    if match_count == 5 and bonus_match:
        return "2등"
    if match_count == 5:
        return "3등"
    if match_count == 4:
        return "4등"
    if match_count == 3:
        return "5등"
    return "낙첨"


def _evaluate(combos: Sequence[Sequence[int]], details: Sequence[Dict[str, Any]], target: Dict[str, Any]) -> Dict[str, Any]:
    win = set(target["numbers"])
    bonus = int(target.get("bonus") or 0)
    distribution = Counter()
    best_match = 0
    best_rank = "낙첨"
    rank_order = {"1등": 6, "2등": 5.5, "3등": 5, "4등": 4, "5등": 3, "낙첨": 0}
    combo_rows: List[Dict[str, Any]] = []
    scores: List[float] = []
    pool = set()
    for idx, combo in enumerate(combos):
        nums = sorted(int(n) for n in combo)
        pool.update(nums)
        matches = len(set(nums) & win)
        bonus_match = bonus in nums
        rank = _rank(matches, bonus_match)
        distribution[str(matches)] += 1
        if matches > best_match or rank_order[rank] > rank_order[best_rank]:
            best_match = matches
            best_rank = rank
        detail = dict(details[idx]) if idx < len(details) else {}
        score = float(detail.get("score", 0) or 0)
        scores.append(score)
        combo_rows.append({
            "numbers": nums,
            "match_count": matches,
            "matched_numbers": sorted(set(nums) & win),
            "bonus_match": bonus_match,
            "rank": rank,
            "strategy": detail.get("strategy") or detail.get("type") or "균형형",
            "score": round(score, 4),
        })
    return {
        "best_match": best_match,
        "best_rank": best_rank,
        "match_distribution": dict(distribution),
        "pool_match_count": len(pool & win),
        "pool_numbers": sorted(pool),
        "combo_results": combo_rows,
        "avg_combo_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "max_combo_score": round(max(scores), 4) if scores else 0.0,
    }


def create_run(c: Any, *, created_by: int, combo_count: int = DEFAULT_COMBO_COUNT, mode: str = "balanced", min_history: int = DEFAULT_MIN_HISTORY) -> Dict[str, Any]:
    ensure_backtest_tables(c)
    draws = load_draws(c)
    if len(draws) < 2:
        raise ValueError("백테스트를 실행하려면 유효한 당첨 회차가 최소 2개 필요합니다.")
    first_round = int(draws[0]["round"])
    last_round = int(draws[-1]["round"])
    combo_count = max(1, min(50, int(combo_count or DEFAULT_COMBO_COUNT)))
    min_history = max(1, int(min_history or DEFAULT_MIN_HISTORY))
    start_round = first_round + 1
    eligible = [d for d in draws if int(d["round"]) >= start_round]
    cur = c.execute(
        "INSERT INTO backtest_runs(status,start_round,end_round,next_round,combo_count,min_history,mode,engine_version,backtest_version,total_rounds,processed_rounds,success_rounds,failed_rounds,skipped_rounds,created_by,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("ready", start_round, last_round, start_round, combo_count, min_history, mode or "balanced", ENGINE_VERSION, BACKTEST_VERSION, len(eligible), 0, 0, 0, 0, created_by, _now(), _now()),
    )
    c.commit()
    return get_run(c, int(cur.lastrowid))


def get_run(c: Any, run_id: int) -> Dict[str, Any]:
    ensure_backtest_tables(c)
    row = c.execute("SELECT * FROM backtest_runs WHERE id=?", (int(run_id),)).fetchone()
    if not row:
        raise KeyError("백테스트 실행 정보를 찾을 수 없습니다.")
    return dict(row)


def list_runs(c: Any, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_backtest_tables(c)
    rows = c.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", (max(1, min(100, int(limit))),)).fetchall()
    return [dict(row) for row in rows]


def cancel_run(c: Any, run_id: int) -> Dict[str, Any]:
    run = get_run(c, run_id)
    if run["status"] in {"completed", "cancelled"}:
        return run
    c.execute("UPDATE backtest_runs SET status='cancelled',updated_at=? WHERE id=?", (_now(), int(run_id)))
    c.commit()
    return get_run(c, run_id)


def process_step(c: Any, run_id: int, step_size: int = 2, *, weight_profile: Optional[Dict[str, Any]] = None, profile_label: str = "") -> Dict[str, Any]:
    ensure_backtest_tables(c)
    run = get_run(c, run_id)
    if run["status"] in {"completed", "cancelled"}:
        return {"run": run, "processed": 0, "done": run["status"] == "completed"}
    step_size = max(1, min(MAX_STEP_SIZE, int(step_size or 1)))
    draws = load_draws(c)
    by_round = {int(d["round"]): d for d in draws}
    ordered = sorted(draws, key=lambda d: int(d["round"]))
    positions = {int(d["round"]): i for i, d in enumerate(ordered)}
    target_rounds = [r for r in sorted(by_round) if int(r) >= int(run["next_round"]) and int(r) <= int(run["end_round"])][:step_size]
    if not target_rounds:
        c.execute("UPDATE backtest_runs SET status='completed',completed_at=?,updated_at=? WHERE id=?", (_now(), _now(), int(run_id)))
        c.commit()
        return {"run": get_run(c, run_id), "processed": 0, "done": True}

    if run["status"] == "ready":
        c.execute("UPDATE backtest_runs SET status='running',started_at=?,updated_at=? WHERE id=?", (_now(), _now(), int(run_id)))
        c.commit()

    processed = success = failed = skipped = 0
    for target_round in target_rounds:
        target = by_round[target_round]
        idx = positions[target_round]
        history = ordered[:idx]
        status = "ok"
        error = ""
        result: Dict[str, Any] = {}
        started = time.perf_counter()
        seed = f"{BACKTEST_VERSION}|run:{run_id}|round:{target_round}|mode:{run['mode']}|count:{run['combo_count']}|profile:{profile_label}"
        try:
            if len(history) < int(run["min_history"]):
                status = "skipped"
                error = f"이전 회차 {len(history)}개로 최소 이력 {run['min_history']}개를 충족하지 못했습니다."
                skipped += 1
            else:
                cache = build_backtest_cache(history)
                combos, details, stats = make_premium_combos(
                    int(run["combo_count"]),
                    mode=run["mode"],
                    member_grade="일반",
                    cache_override=cache,
                    deterministic_seed=seed,
                    lab_weight_profile=weight_profile,
                )
                result = _evaluate(combos, details, target)
                result["recommended_numbers"] = combos
                result["details"] = details
                result["engine_stats"] = stats
                success += 1
        except Exception as exc:
            status = "failed"
            error = f"{exc.__class__.__name__}: {exc}"[:1000]
            failed += 1
        generation_ms = round((time.perf_counter() - started) * 1000, 2)
        c.execute("DELETE FROM backtest_results WHERE run_id=? AND target_round=?", (int(run_id), int(target_round)))
        c.execute(
            "INSERT INTO backtest_results(run_id,target_round,history_from,history_to,history_count,mode,engine_version,seed,winning_numbers,bonus,recommended_numbers,details_json,best_match,best_rank,match_distribution,pool_match_count,pool_numbers,avg_combo_score,max_combo_score,generation_ms,status,error_message,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(run_id), int(target_round), int(history[0]["round"]) if history else 0, int(history[-1]["round"]) if history else 0, len(history), run["mode"], ENGINE_VERSION, seed,
                json.dumps(target["numbers"], ensure_ascii=False), int(target.get("bonus") or 0),
                json.dumps(result.get("recommended_numbers", []), ensure_ascii=False),
                json.dumps({"combo_results": result.get("combo_results", []), "engine_stats": result.get("engine_stats", {})}, ensure_ascii=False),
                int(result.get("best_match", 0)), result.get("best_rank", "낙첨"), json.dumps(result.get("match_distribution", {}), ensure_ascii=False),
                int(result.get("pool_match_count", 0)), json.dumps(result.get("pool_numbers", []), ensure_ascii=False),
                float(result.get("avg_combo_score", 0) or 0), float(result.get("max_combo_score", 0) or 0), generation_ms, status, error, _now(),
            ),
        )
        processed += 1
        next_round = int(target_round) + 1
        c.execute(
            "UPDATE backtest_runs SET next_round=?,processed_rounds=processed_rounds+1,success_rounds=success_rounds+?,failed_rounds=failed_rounds+?,skipped_rounds=skipped_rounds+?,updated_at=?,error_message=? WHERE id=?",
            (next_round, 1 if status == "ok" else 0, 1 if status == "failed" else 0, 1 if status == "skipped" else 0, _now(), error if status == "failed" else "", int(run_id)),
        )
        c.commit()

    updated = get_run(c, run_id)
    if int(updated["next_round"]) > int(updated["end_round"]):
        c.execute("UPDATE backtest_runs SET status='completed',completed_at=?,updated_at=? WHERE id=?", (_now(), _now(), int(run_id)))
        c.commit()
        updated = get_run(c, run_id)
    return {"run": updated, "processed": processed, "success": success, "failed": failed, "skipped": skipped, "done": updated["status"] == "completed"}


def get_summary(c: Any, run_id: int) -> Dict[str, Any]:
    run = get_run(c, run_id)
    rows = c.execute("SELECT * FROM backtest_results WHERE run_id=? AND status='ok' ORDER BY target_round", (int(run_id),)).fetchall()
    if not rows:
        return {"run": run, "summary": {"evaluated_rounds": 0}, "by_window": {}, "by_strategy": {}}
    records = [dict(r) for r in rows]

    def summarize(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(items)
        best_dist = Counter(int(x.get("best_match", 0) or 0) for x in items)
        rank_dist = Counter(str(x.get("best_rank") or "낙첨") for x in items)
        return {
            "evaluated_rounds": n,
            "avg_best_match": round(sum(int(x.get("best_match", 0) or 0) for x in items) / n, 4),
            "avg_pool_match": round(sum(int(x.get("pool_match_count", 0) or 0) for x in items) / n, 4),
            "rounds_with_3plus": sum(1 for x in items if int(x.get("best_match", 0) or 0) >= 3),
            "rounds_with_4plus": sum(1 for x in items if int(x.get("best_match", 0) or 0) >= 4),
            "rounds_with_5plus": sum(1 for x in items if int(x.get("best_match", 0) or 0) >= 5),
            "best_match_distribution": {str(k): v for k, v in sorted(best_dist.items())},
            "rank_distribution": dict(rank_dist),
            "avg_generation_ms": round(sum(float(x.get("generation_ms", 0) or 0) for x in items) / n, 2),
        }

    by_window: Dict[str, Any] = {"all": summarize(records)}
    for window in (50, 100, 300):
        by_window[str(window)] = summarize(records[-window:])

    strategy_agg: Dict[str, Dict[str, float]] = {}
    for row in records:
        try:
            payload = json.loads(row.get("details_json") or "{}")
        except Exception:
            payload = {}
        for combo in payload.get("combo_results", []) or []:
            strategy = str(combo.get("strategy") or "균형형")
            agg = strategy_agg.setdefault(strategy, {"combos": 0, "matches": 0, "three_plus": 0, "four_plus": 0})
            match = int(combo.get("match_count", 0) or 0)
            agg["combos"] += 1
            agg["matches"] += match
            agg["three_plus"] += 1 if match >= 3 else 0
            agg["four_plus"] += 1 if match >= 4 else 0
    by_strategy = {
        k: {
            "combos": int(v["combos"]),
            "avg_match": round(v["matches"] / v["combos"], 4) if v["combos"] else 0,
            "three_plus": int(v["three_plus"]),
            "four_plus": int(v["four_plus"]),
        }
        for k, v in sorted(strategy_agg.items())
    }

    # RC6-B report data: keep the UI light by returning 50-round trend blocks
    # instead of forcing the browser to download every detailed result.
    trend_blocks: List[Dict[str, Any]] = []
    block_size = 50
    for start in range(0, len(records), block_size):
        block = records[start:start + block_size]
        if not block:
            continue
        metrics = summarize(block)
        trend_blocks.append({
            "label": f"{int(block[0]['target_round'])}~{int(block[-1]['target_round'])}",
            "from_round": int(block[0]["target_round"]),
            "to_round": int(block[-1]["target_round"]),
            **metrics,
        })

    return {
        "run": run,
        "summary": by_window["all"],
        "by_window": by_window,
        "by_strategy": by_strategy,
        "trend_blocks": trend_blocks,
    }


def get_results(c: Any, run_id: int, page: int = 1, page_size: int = 30) -> Dict[str, Any]:
    get_run(c, run_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 30)))
    total = int(c.execute("SELECT COUNT(*) FROM backtest_results WHERE run_id=?", (int(run_id),)).fetchone()[0])
    rows = c.execute(
        "SELECT * FROM backtest_results WHERE run_id=? ORDER BY target_round DESC LIMIT ? OFFSET ?",
        (int(run_id), page_size, (page - 1) * page_size),
    ).fetchall()
    data: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, default in (("winning_numbers", []), ("recommended_numbers", []), ("match_distribution", {}), ("pool_numbers", []), ("details_json", {})):
            try:
                item[key] = json.loads(item.get(key) or json.dumps(default))
            except Exception:
                item[key] = default
        data.append(item)
    return {"run_id": int(run_id), "page": page, "page_size": page_size, "total": total, "items": data}
