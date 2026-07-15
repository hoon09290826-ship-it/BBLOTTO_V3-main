from __future__ import annotations

from typing import Any, Dict, List

from .ai_lab_core import _json, _loads, _now, ensure_ai_lab_tables, get_job
from .ai_lab_candidates import list_job_candidates
from .backtest_engine import create_run, get_run, get_summary, load_draws, process_step

COMPARE_VERSION = "RC6_D1_4_CANDIDATE_COMPARE"


def _configure_run(c: Any, run_id: int, range_type: str) -> Dict[str, Any]:
    run = get_run(c, run_id)
    draws = load_draws(c)
    eligible = [int(d["round"]) for d in draws if int(d["round"]) >= int(run["start_round"])]
    if not eligible:
        raise ValueError("Candidate 검증에 사용할 회차가 없습니다.")
    wanted = 300 if range_type == "recent300" else 500 if range_type == "recent500" else len(eligible)
    selected = eligible[-wanted:]
    c.execute(
        "UPDATE backtest_runs SET start_round=?,end_round=?,next_round=?,total_rounds=?,processed_rounds=0,success_rounds=0,failed_rounds=0,skipped_rounds=0,status='ready',started_at='',completed_at='',updated_at=?,error_message='' WHERE id=?",
        (selected[0], selected[-1], selected[0], len(selected), _now(), int(run_id)),
    )
    c.execute("DELETE FROM backtest_results WHERE run_id=?", (int(run_id),))
    c.commit()
    return get_run(c, run_id)


def _score(summary: Dict[str, Any]) -> float:
    rounds = max(1, int(summary.get("evaluated_rounds") or 0))
    return round(
        float(summary.get("avg_best_match") or 0) * 45.0 +
        float(summary.get("avg_pool_match") or 0) * 16.0 +
        int(summary.get("rounds_with_3plus") or 0) / rounds * 24.0 +
        int(summary.get("rounds_with_4plus") or 0) / rounds * 45.0 +
        int(summary.get("rounds_with_5plus") or 0) / rounds * 90.0,
        6,
    )


def initialize_candidate_runs(c: Any, job_id: int, *, created_by: int = 0) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    job = get_job(c, job_id)
    if job.get("status") not in {"candidates_ready", "candidates_testing", "candidates_ranked"}:
        raise ValueError("Candidate 생성이 완료된 작업에서만 비교할 수 있습니다.")
    result = dict(job.get("result") or {})
    run_map = {str(k): int(v) for k, v in (result.get("candidate_backtest_runs") or {}).items()}
    candidates = list_job_candidates(c, job_id)
    for candidate in candidates:
        vid = int(candidate["id"])
        if str(vid) in run_map:
            continue
        run = create_run(c, created_by=created_by, combo_count=10, mode="balanced", min_history=1)
        run = _configure_run(c, int(run["id"]), str(job.get("range_type") or "recent300"))
        run_map[str(vid)] = int(run["id"])
    result["candidate_backtest_runs"] = run_map
    result["compare_version"] = COMPARE_VERSION
    result["operating_engine_changed"] = False
    c.execute("UPDATE ai_learning_jobs SET status='candidates_testing',result_json=?,updated_at=? WHERE id=?", (_json(result), _now(), int(job_id)))
    c.commit()
    return get_job(c, job_id)


def process_compare_step(c: Any, job_id: int, *, step_size: int = 2, created_by: int = 0) -> Dict[str, Any]:
    job = initialize_candidate_runs(c, job_id, created_by=created_by)
    result = dict(job.get("result") or {})
    candidates = {int(x["id"]): x for x in list_job_candidates(c, job_id)}
    run_map = {int(k): int(v) for k, v in (result.get("candidate_backtest_runs") or {}).items()}
    active = None
    for vid in sorted(run_map):
        run = get_run(c, run_map[vid])
        if run.get("status") not in {"completed", "cancelled"}:
            active = (vid, run)
            break
    if active:
        vid, run = active
        candidate = candidates[vid]
        stepped = process_step(c, int(run["id"]), step_size=max(1, min(5, int(step_size))), weight_profile=candidate.get("weights") or {}, profile_label=f"candidate:{vid}")
        return {"job": get_job(c, job_id), "candidate_version_id": vid, "backtest_run": stepped["run"], "processed": stepped.get("processed", 0), "done": False, "operating_engine_changed": False}
    rankings = finalize_rankings(c, job_id, created_by=created_by)
    return {"job": get_job(c, job_id), "rankings": rankings, "processed": 0, "done": True, "operating_engine_changed": False}


def finalize_rankings(c: Any, job_id: int, *, created_by: int = 0) -> List[Dict[str, Any]]:
    job = get_job(c, job_id)
    result = dict(job.get("result") or {})
    baseline = result.get("summary") or {}
    baseline_score = _score(baseline)
    candidates = {int(x["id"]): x for x in list_job_candidates(c, job_id)}
    run_map = {int(k): int(v) for k, v in (result.get("candidate_backtest_runs") or {}).items()}
    rows: List[Dict[str, Any]] = []
    for vid, run_id in run_map.items():
        summary = get_summary(c, run_id).get("summary") or {}
        score = _score(summary)
        improvement = round(score - baseline_score, 6)
        item = {"version_id": vid, "version_name": candidates[vid].get("version_name"), "backtest_run_id": run_id, "score": score, "baseline_score": baseline_score, "improvement": improvement, "summary": summary, "weight_deltas": (candidates[vid].get("metrics") or {}).get("weight_deltas", []), "recommendation": "승인 검토" if improvement > 0 else "보류"}
        rows.append(item)
    rows.sort(key=lambda x: (-x["score"], x["version_id"]))
    for rank, item in enumerate(rows, 1):
        item["rank"] = rank
        version = c.execute("SELECT metrics_json FROM ai_engine_versions WHERE id=?", (item["version_id"],)).fetchone()
        metrics = _loads(version["metrics_json"] if version else "{}", {})
        metrics.update({"validation_status": "backtest_completed", "candidate_rank": rank, "candidate_score": item["score"], "stable_score": baseline_score, "improvement": item["improvement"], "backtest_summary": item["summary"], "backtest_run_id": item["backtest_run_id"], "operating_engine_changed": False})
        c.execute("UPDATE ai_engine_versions SET metrics_json=?,notes=? WHERE id=?", (_json(metrics), f"RC6-D1 4단계 백테스트 순위 {rank}위. Stable 자동 적용 금지.", item["version_id"]))
    best = rows[0]["version_id"] if rows and rows[0]["improvement"] > 0 else 0
    result.update({"candidate_rankings": rows, "best_candidate_version_id": best, "compare_version": COMPARE_VERSION, "operating_engine_changed": False})
    c.execute("UPDATE ai_learning_jobs SET status='candidates_ranked',best_candidate_version_id=?,result_json=?,updated_at=? WHERE id=?", (best, _json(result), _now(), int(job_id)))
    body = "Candidate 비교가 완료되었습니다. " + (f"1위 후보는 버전 #{best}이며 Stable 대비 개선 후보입니다." if best else "Stable을 넘어선 후보가 없어 운영 엔진을 유지합니다.")
    c.execute("INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)", (int(job_id), int(best or job.get("base_version_id") or 0), "candidate_ranking_completed", "Candidate 비교·순위 완료", body, _json({"rankings": rows, "operating_engine_changed": False}), int(created_by), _now()))
    c.commit()
    return rows


def get_rankings(c: Any, job_id: int) -> List[Dict[str, Any]]:
    job = get_job(c, job_id)
    return list((job.get("result") or {}).get("candidate_rankings") or [])
