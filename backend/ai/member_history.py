from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

MIN_RECOMMENDATION_RUNS = 20
MAX_RECOMMENDATION_RUNS = 300
MAX_STRATEGY_ADJUSTMENT = 2.5
MAX_STRUCTURE_ADJUSTMENT = 1.5


def _parse_numbers(value: Any) -> List[int]:
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        text = str(value or "").replace("[", " ").replace("]", " ").replace(",", " ")
        raw = text.split()
    out: List[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 45 and number not in out:
            out.append(number)
    return sorted(out)


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _strategy_name(value: Any) -> str:
    text = str(value or "균형형").strip()
    if "최근" in text or "흐름" in text:
        return "최근 흐름형"
    if "반등" in text or "미출현" in text:
        return "반등 혼합형"
    if "동반" in text or "페어" in text:
        return "동반출현형"
    return "균형형"


def _combo_signature(numbers: Sequence[int]) -> Dict[str, Any]:
    nums = sorted(int(n) for n in numbers)
    odd = sum(n % 2 for n in nums)
    zones = [sum(1 for n in nums if 1 <= n <= 15), sum(1 for n in nums if 16 <= n <= 30), sum(1 for n in nums if 31 <= n <= 45)]
    diffs = {b - a for i, a in enumerate(nums) for b in nums[i + 1 :]}
    ac = max(0, len(diffs) - 5)
    return {"sum": sum(nums), "odd": odd, "zones": zones, "ac": ac}


def analyze_member_history(c: Any, member_id: int, *, min_runs: int = MIN_RECOMMENDATION_RUNS, max_runs: int = MAX_RECOMMENDATION_RUNS) -> Dict[str, Any]:
    member_id = int(member_id)
    member = c.execute("SELECT id,name FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        raise KeyError("회원을 찾을 수 없습니다.")

    rec_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(recommendations)").fetchall()}
    required = {"id", "member_id", "round_no", "numbers"}
    if not required.issubset(rec_columns):
        rows = []
    else:
        detail_expr = "details_json" if "details_json" in rec_columns else "'[]' AS details_json"
        mode_expr = "mode" if "mode" in rec_columns else "'balanced' AS mode"
        created_expr = "created_at" if "created_at" in rec_columns else "'' AS created_at"
        saved_filter = " AND COALESCE(explicit_saved,1)=1" if "explicit_saved" in rec_columns else ""
        rows = c.execute(
            f"SELECT id,round_no,numbers,{detail_expr},{mode_expr},{created_expr} FROM recommendations "
            f"WHERE member_id=?{saved_filter} ORDER BY id DESC LIMIT ?",
            (member_id, max(1, min(1000, int(max_runs)))),
        ).fetchall()
    draw_rows = c.execute("SELECT round_no,numbers,bonus FROM draws").fetchall()
    draws = {int(row["round_no"]): {"numbers": _parse_numbers(row["numbers"]), "bonus": int(row["bonus"] or 0)} for row in draw_rows}

    strategy_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    timeline: List[Dict[str, Any]] = []
    successful_structures: List[Dict[str, Any]] = []
    evaluated_runs = 0
    total_combos = 0
    all_match_values: List[int] = []

    for row in reversed(rows):
        round_no = int(row["round_no"] or 0)
        target = draws.get(round_no)
        if not target or len(target["numbers"]) != 6:
            continue
        combos = _json(row["numbers"], [])
        details = _json(row["details_json"], [])
        valid_combos = [_parse_numbers(combo) for combo in combos]
        valid_combos = [combo for combo in valid_combos if len(combo) == 6]
        if not valid_combos:
            continue
        evaluated_runs += 1
        winning = set(target["numbers"])
        run_best = 0
        run_pool = set()
        run_strategy_best: Dict[str, int] = defaultdict(int)
        for index, combo in enumerate(valid_combos):
            detail = details[index] if index < len(details) and isinstance(details[index], dict) else {}
            strategy = _strategy_name(detail.get("strategy") or detail.get("type") or row["mode"])
            match_count = len(set(combo) & winning)
            run_best = max(run_best, match_count)
            run_strategy_best[strategy] = max(run_strategy_best[strategy], match_count)
            run_pool.update(combo)
            total_combos += 1
            all_match_values.append(match_count)
            signature = _combo_signature(combo)
            metric = {
                "match": match_count,
                "three_plus": 1 if match_count >= 3 else 0,
                "four_plus": 1 if match_count >= 4 else 0,
                "sum": signature["sum"],
                "odd": signature["odd"],
                "zones": signature["zones"],
                "ac": signature["ac"],
            }
            strategy_rows[strategy].append(metric)
            if match_count >= 3:
                successful_structures.append(metric)
        timeline.append({
            "round_no": round_no,
            "created_at": row["created_at"] or "",
            "best_match": run_best,
            "pool_match_count": len(run_pool & winning),
            "strategy_best": dict(run_strategy_best),
        })

    overall_avg = sum(all_match_values) / len(all_match_values) if all_match_values else 0.0
    overall_three = sum(1 for value in all_match_values if value >= 3) / len(all_match_values) if all_match_values else 0.0
    overall_four = sum(1 for value in all_match_values if value >= 4) / len(all_match_values) if all_match_values else 0.0
    overall_index = overall_avg + overall_three * 1.2 + overall_four * 0.8
    run_confidence = min(1.0, evaluated_runs / 100.0)
    enabled = evaluated_runs >= max(1, int(min_runs))

    strategies: List[Dict[str, Any]] = []
    adjustments: Dict[str, float] = {}
    for name in ["균형형", "최근 흐름형", "반등 혼합형", "동반출현형"]:
        items = strategy_rows.get(name, [])
        count = len(items)
        avg = sum(item["match"] for item in items) / count if count else 0.0
        rate3 = sum(item["three_plus"] for item in items) / count if count else 0.0
        rate4 = sum(item["four_plus"] for item in items) / count if count else 0.0
        raw_index = avg + rate3 * 1.2 + rate4 * 0.8
        sample_confidence = min(1.0, count / 200.0)
        confidence = run_confidence * sample_confidence
        adjustment = (raw_index - overall_index) * 2.0 * confidence if enabled else 0.0
        adjustment = max(-MAX_STRATEGY_ADJUSTMENT, min(MAX_STRATEGY_ADJUSTMENT, adjustment))
        adjustments[name] = round(adjustment, 4)
        strategies.append({
            "strategy": name,
            "combo_samples": count,
            "avg_match": round(avg, 4),
            "three_plus_rate": round(rate3 * 100, 2),
            "four_plus_rate": round(rate4 * 100, 2),
            "performance_index": round(raw_index, 4),
            "adaptive_adjustment": round(adjustment, 4),
        })

    structure_source = successful_structures if len(successful_structures) >= 5 else [item for items in strategy_rows.values() for item in items]
    if structure_source:
        preferred_sum = sum(item["sum"] for item in structure_source) / len(structure_source)
        preferred_odd = sum(item["odd"] for item in structure_source) / len(structure_source)
        preferred_ac = sum(item["ac"] for item in structure_source) / len(structure_source)
        preferred_zones = [sum(item["zones"][i] for item in structure_source) / len(structure_source) for i in range(3)]
    else:
        preferred_sum, preferred_odd, preferred_ac, preferred_zones = 138.0, 3.0, 7.0, [2.0, 2.0, 2.0]

    best_strategy = max(strategies, key=lambda item: (item["performance_index"], item["combo_samples"]), default=None)
    return {
        "member_id": member_id,
        "member_name": member["name"],
        "enabled": enabled,
        "minimum_runs": int(min_runs),
        "evaluated_runs": evaluated_runs,
        "evaluated_combos": total_combos,
        "confidence": round(run_confidence, 4),
        "overall": {
            "avg_match": round(overall_avg, 4),
            "three_plus_rate": round(overall_three * 100, 2),
            "four_plus_rate": round(overall_four * 100, 2),
            "performance_index": round(overall_index, 4),
        },
        "strategies": strategies,
        "strategy_adjustments": adjustments,
        "preferred_structure": {
            "sum": round(preferred_sum, 2),
            "odd": round(preferred_odd, 2),
            "ac": round(preferred_ac, 2),
            "zones": [round(value, 2) for value in preferred_zones],
            "sample_count": len(structure_source),
        },
        "best_strategy": best_strategy["strategy"] if best_strategy else "균형형",
        "timeline": timeline[-50:],
        "safety": {
            "base_engine_share": 90 if enabled else 100,
            "member_history_share": min(10, round(run_confidence * 10)) if enabled else 0,
            "max_strategy_adjustment": MAX_STRATEGY_ADJUSTMENT,
            "max_structure_adjustment": MAX_STRUCTURE_ADJUSTMENT,
            "number_repetition_learning": False,
        },
    }


def load_member_profile(db_path: Path, member_id: Optional[int]) -> Dict[str, Any]:
    if not member_id:
        return {"enabled": False, "member_id": 0, "strategy_adjustments": {}}
    try:
        connection = sqlite3.connect(str(db_path), timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            return analyze_member_history(connection, int(member_id))
        finally:
            connection.close()
    except Exception as exc:
        return {"enabled": False, "member_id": int(member_id), "strategy_adjustments": {}, "error": str(exc)}


def member_structure_adjustment(detail: Dict[str, Any], profile: Dict[str, Any]) -> float:
    if not profile.get("enabled"):
        return 0.0
    preferred = profile.get("preferred_structure") or {}
    confidence = float(profile.get("confidence") or 0.0)
    sum_gap = abs(float(detail.get("sum", 138) or 138) - float(preferred.get("sum", 138) or 138))
    odd_gap = abs(float(detail.get("odd", 3) or 3) - float(preferred.get("odd", 3) or 3))
    ac_gap = abs(float(detail.get("ac", 7) or 7) - float(preferred.get("ac", 7) or 7))
    zones = detail.get("zones") or [2, 2, 2]
    preferred_zones = preferred.get("zones") or [2, 2, 2]
    zone_gap = sum(abs(float(zones[i]) - float(preferred_zones[i])) for i in range(min(3, len(zones), len(preferred_zones))))
    closeness = 1.0 - min(1.0, sum_gap / 60.0 + odd_gap / 4.0 + ac_gap / 12.0 + zone_gap / 8.0)
    adjustment = (closeness - 0.5) * 2.0 * MAX_STRUCTURE_ADJUSTMENT * confidence
    return round(max(-MAX_STRUCTURE_ADJUSTMENT, min(MAX_STRUCTURE_ADJUSTMENT, adjustment)), 4)
