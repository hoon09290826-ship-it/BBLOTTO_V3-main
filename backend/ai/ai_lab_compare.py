from __future__ import annotations

from typing import Any, Dict, List

from .ai_lab_core import _json, _loads, _now, ensure_ai_lab_tables, get_job
from .ai_lab_candidates import list_job_candidates
from .backtest_engine import create_run, get_run, get_summary, load_draws, process_step

COMPARE_VERSION = "RC6_D10_BACKGROUND_PERSISTENT_CACHE_COMPARE"
SCREENING_ROUNDS = 300
PRECISION_CANDIDATES = 3


def _run_is_compatible(
    run: Dict[str, Any],
    *,
    range_type: str,
    validation_profile: str,
    profile_fingerprint: str,
    wanted_total: int,
) -> bool:
    """Reuse only results produced under exactly the same validation contract."""
    return bool(
        run
        and run.get("status") == "completed"
        and int(run.get("total_rounds") or 0) >= int(wanted_total)
        and str(run.get("validation_profile") or "") == validation_profile
        and str(run.get("profile_fingerprint") or "") == profile_fingerprint
        and str(run.get("seed_scheme") or "") == "portable_v1"
        and (
            range_type != "recent300"
            or int(run.get("total_rounds") or 0) == SCREENING_ROUNDS
        )
    )


def _candidate_fingerprint(candidate: Dict[str, Any], version_id: int) -> str:
    from .backtest_engine import _profile_fingerprint

    return _profile_fingerprint(
        candidate.get("weights") or {},
        f"candidate:{version_id}",
    )


def _configure_run(c: Any, run_id: int, range_type: str) -> Dict[str, Any]:
    run = get_run(c, run_id)
    draws = load_draws(c)
    eligible = [
        int(draw["round"])
        for draw in draws
        if int(draw["round"]) >= int(run["start_round"])
    ]
    if not eligible:
        raise ValueError("Candidate 검증에 사용할 회차가 없습니다.")
    wanted = (
        SCREENING_ROUNDS
        if range_type == "recent300"
        else 500
        if range_type == "recent500"
        else len(eligible)
    )
    selected = eligible[-wanted:]
    c.execute(
        "UPDATE backtest_runs SET start_round=?,end_round=?,next_round=?,"
        "total_rounds=?,processed_rounds=0,success_rounds=0,failed_rounds=0,"
        "skipped_rounds=0,status='ready',started_at='',completed_at='',"
        "updated_at=?,error_message='' WHERE id=?",
        (selected[0], selected[-1], selected[0], len(selected), _now(), int(run_id)),
    )
    c.execute("DELETE FROM backtest_results WHERE run_id=?", (int(run_id),))
    c.commit()
    return get_run(c, run_id)


def _new_run(
    c: Any,
    *,
    created_by: int,
    range_type: str,
) -> Dict[str, Any]:
    run = create_run(
        c,
        created_by=created_by,
        combo_count=10,
        mode="balanced",
        min_history=1,
    )
    return _configure_run(c, int(run["id"]), range_type)


def _score(summary: Dict[str, Any]) -> float:
    rounds = max(1, int(summary.get("evaluated_rounds") or 0))
    return round(
        float(summary.get("avg_best_match") or 0) * 45.0
        + float(summary.get("avg_pool_match") or 0) * 16.0
        + int(summary.get("rounds_with_3plus") or 0) / rounds * 24.0
        + int(summary.get("rounds_with_4plus") or 0) / rounds * 45.0
        + int(summary.get("rounds_with_5plus") or 0) / rounds * 90.0,
        6,
    )


def _rank_map(
    c: Any,
    run_map: Dict[int, int],
    candidates: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for version_id, run_id in run_map.items():
        summary = get_summary(c, run_id).get("summary") or {}
        rows.append({
            "version_id": int(version_id),
            "version_name": candidates.get(int(version_id), {}).get("version_name"),
            "backtest_run_id": int(run_id),
            "score": _score(summary),
            "summary": summary,
        })
    rows.sort(key=lambda item: (-item["score"], item["version_id"]))
    for rank, item in enumerate(rows, 1):
        item["screening_rank"] = rank
    return rows


def _save_result(c: Any, job_id: int, result: Dict[str, Any]) -> Dict[str, Any]:
    c.execute(
        "UPDATE ai_learning_jobs SET status='candidates_testing',result_json=?,"
        "updated_at=? WHERE id=?",
        (_json(result), _now(), int(job_id)),
    )
    c.commit()
    return get_job(c, job_id)


def initialize_candidate_runs(
    c: Any,
    job_id: int,
    *,
    created_by: int = 0,
) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    job = get_job(c, job_id)
    if job.get("status") not in {
        "candidates_ready",
        "candidates_testing",
        "candidates_ranked",
    }:
        raise ValueError("Candidate 생성이 완료된 작업에서만 비교할 수 있습니다.")
    result = dict(job.get("result") or {})
    if (
        result.get("compare_version") == COMPARE_VERSION
        and result.get("candidate_backtest_runs")
    ):
        return job

    candidates = {
        int(item["id"]): item for item in list_job_candidates(c, job_id)
    }
    old_map = {
        int(key): int(value)
        for key, value in (result.get("candidate_backtest_runs") or {}).items()
    }
    screening_map: Dict[int, int] = {}
    legacy_map: Dict[int, int] = dict(old_map)

    for version_id in sorted(candidates):
        old_run_id = old_map.get(version_id)
        old_run = get_run(c, old_run_id) if old_run_id else {}
        fingerprint = _candidate_fingerprint(candidates[version_id], version_id)
        # 엔진·프로필·범위·시드 방식이 모두 같은 결과만 재사용합니다.
        if _run_is_compatible(
            old_run,
            range_type="recent300",
            validation_profile="screening",
            profile_fingerprint=fingerprint,
            wanted_total=SCREENING_ROUNDS,
        ):
            screening_map[version_id] = int(old_run_id)
        else:
            run = _new_run(
                c,
                created_by=created_by,
                range_type="recent300",
            )
            screening_map[version_id] = int(run["id"])

    result.update({
        "candidate_backtest_runs": {
            str(key): value for key, value in screening_map.items()
        },
        "screening_run_map": {
            str(key): value for key, value in screening_map.items()
        },
        "legacy_candidate_backtest_runs": {
            str(key): value for key, value in legacy_map.items()
        },
        "compare_version": COMPARE_VERSION,
        "compare_stage": "screening",
        "screening_rounds": SCREENING_ROUNDS,
        "precision_candidate_count": PRECISION_CANDIDATES,
        "operating_engine_changed": False,
    })
    return _save_result(c, job_id, result)


def _start_precision_stage(
    c: Any,
    job: Dict[str, Any],
    candidates: Dict[int, Dict[str, Any]],
    *,
    created_by: int,
) -> Dict[str, Any]:
    result = dict(job.get("result") or {})
    screening_map = {
        int(key): int(value)
        for key, value in (result.get("screening_run_map") or {}).items()
    }
    screening_rankings = _rank_map(c, screening_map, candidates)
    top_ids = [
        int(item["version_id"])
        for item in screening_rankings[:PRECISION_CANDIDATES]
    ]
    result["screening_rankings"] = screening_rankings
    result["precision_candidate_ids"] = top_ids

    original_range = str(job.get("range_type") or "recent300")
    if original_range == "recent300":
        result["candidate_backtest_runs"] = {
            str(version_id): screening_map[version_id]
            for version_id in top_ids
        }
        result["compare_stage"] = "precision"
        return _save_result(c, int(job["id"]), result)

    legacy_map = {
        int(key): int(value)
        for key, value in (
            result.get("legacy_candidate_backtest_runs") or {}
        ).items()
    }
    precision_map: Dict[int, int] = {}
    for version_id in top_ids:
        legacy_run_id = legacy_map.get(version_id)
        legacy_run = get_run(c, legacy_run_id) if legacy_run_id else {}
        wanted_total = (
            500
            if original_range == "recent500"
            else len(load_draws(c))
        )
        fingerprint = _candidate_fingerprint(candidates[version_id], version_id)
        if _run_is_compatible(
            legacy_run,
            range_type=original_range,
            validation_profile="precision",
            profile_fingerprint=fingerprint,
            wanted_total=wanted_total,
        ):
            precision_map[version_id] = int(legacy_run_id)
        else:
            run = _new_run(
                c,
                created_by=created_by,
                range_type=original_range,
            )
            precision_map[version_id] = int(run["id"])

    result.update({
        "candidate_backtest_runs": {
            str(key): value for key, value in precision_map.items()
        },
        "precision_run_map": {
            str(key): value for key, value in precision_map.items()
        },
        "compare_stage": "precision",
    })
    return _save_result(c, int(job["id"]), result)


def process_compare_step(
    c: Any,
    job_id: int,
    *,
    step_size: int = 2,
    created_by: int = 0,
) -> Dict[str, Any]:
    job = initialize_candidate_runs(c, job_id, created_by=created_by)
    result = dict(job.get("result") or {})
    candidates = {
        int(item["id"]): item for item in list_job_candidates(c, job_id)
    }
    run_map = {
        int(key): int(value)
        for key, value in (result.get("candidate_backtest_runs") or {}).items()
    }

    active: List[tuple[int, Dict[str, Any]]] = []
    for version_id, run_id in run_map.items():
        run = get_run(c, run_id)
        if run.get("status") not in {"completed", "cancelled"}:
            active.append((version_id, run))

    if active:
        # 후보를 하나씩 끝내지 않고 가장 덜 진행된 후보부터 교대로 처리합니다.
        # 동일 회차 분석 캐시가 바로 다음 후보에서 재사용됩니다.
        version_id, run = min(
            active,
            key=lambda item: (
                int(item[1].get("processed_rounds") or 0),
                int(item[0]),
            ),
        )
        candidate = candidates[version_id]
        stepped = process_step(
            c,
            int(run["id"]),
            step_size=max(1, min(25, int(step_size))),
            weight_profile=candidate.get("weights") or {},
            profile_label=f"candidate:{version_id}",
            validation_profile=(
                "precision"
                if result.get("compare_stage") == "precision"
                else "screening"
            ),
        )
        return {
            "job": get_job(c, job_id),
            "candidate_version_id": version_id,
            "backtest_run": stepped["run"],
            "processed": stepped.get("processed", 0),
            "done": False,
            "compare_stage": result.get("compare_stage") or "screening",
            "operating_engine_changed": False,
        }

    if result.get("compare_stage") == "screening":
        staged_job = _start_precision_stage(
            c,
            job,
            candidates,
            created_by=created_by,
        )
        # 최근 300회 작업은 1차 결과 자체가 정밀검증 결과입니다.
        if str(job.get("range_type") or "") != "recent300":
            return {
                "job": staged_job,
                "processed": 0,
                "done": False,
                "stage_changed": True,
                "compare_stage": "precision",
                "operating_engine_changed": False,
            }
        job = staged_job

    rankings = finalize_rankings(c, job_id, created_by=created_by)
    return {
        "job": get_job(c, job_id),
        "rankings": rankings,
        "processed": 0,
        "done": True,
        "compare_stage": "completed",
        "operating_engine_changed": False,
    }


def finalize_rankings(
    c: Any,
    job_id: int,
    *,
    created_by: int = 0,
) -> List[Dict[str, Any]]:
    job = get_job(c, job_id)
    result = dict(job.get("result") or {})
    baseline = result.get("summary") or {}
    baseline_score = _score(baseline)
    candidates = {
        int(item["id"]): item for item in list_job_candidates(c, job_id)
    }
    run_map = {
        int(key): int(value)
        for key, value in (result.get("candidate_backtest_runs") or {}).items()
    }
    screening_by_id = {
        int(item["version_id"]): item
        for item in (result.get("screening_rankings") or [])
    }
    rows: List[Dict[str, Any]] = []
    for version_id, run_id in run_map.items():
        summary = get_summary(c, run_id).get("summary") or {}
        score = _score(summary)
        improvement = round(score - baseline_score, 6)
        item = {
            "version_id": version_id,
            "version_name": candidates[version_id].get("version_name"),
            "backtest_run_id": run_id,
            "score": score,
            "baseline_score": baseline_score,
            "improvement": improvement,
            "summary": summary,
            "screening_rank": screening_by_id.get(version_id, {}).get(
                "screening_rank"
            ),
            "weight_deltas": (
                candidates[version_id].get("metrics") or {}
            ).get("weight_deltas", []),
            "recommendation": "승인 검토" if improvement > 0 else "보류",
        }
        rows.append(item)
    rows.sort(key=lambda item: (-item["score"], item["version_id"]))
    for rank, item in enumerate(rows, 1):
        item["rank"] = rank
        version = c.execute(
            "SELECT metrics_json FROM ai_engine_versions WHERE id=?",
            (item["version_id"],),
        ).fetchone()
        metrics = _loads(version["metrics_json"] if version else "{}", {})
        metrics.update({
            "validation_status": "two_stage_backtest_completed",
            "candidate_rank": rank,
            "screening_rank": item.get("screening_rank"),
            "candidate_score": item["score"],
            "stable_score": baseline_score,
            "improvement": item["improvement"],
            "backtest_summary": item["summary"],
            "backtest_run_id": item["backtest_run_id"],
            "compare_version": COMPARE_VERSION,
            "operating_engine_changed": False,
        })
        c.execute(
            "UPDATE ai_engine_versions SET metrics_json=?,notes=? WHERE id=?",
            (
                _json(metrics),
                f"2단계 후보 비교 정밀검증 {rank}위. Stable 자동 적용 금지.",
                item["version_id"],
            ),
        )
    best = (
        rows[0]["version_id"]
        if rows and rows[0]["improvement"] > 0
        else 0
    )
    result.update({
        "candidate_rankings": rows,
        "best_candidate_version_id": best,
        "compare_version": COMPARE_VERSION,
        "compare_stage": "completed",
        "operating_engine_changed": False,
    })
    c.execute(
        "UPDATE ai_learning_jobs SET status='candidates_ranked',"
        "best_candidate_version_id=?,result_json=?,updated_at=? WHERE id=?",
        (best, _json(result), _now(), int(job_id)),
    )
    body = "2단계 Candidate 비교가 완료되었습니다. " + (
        f"정밀검증 1위 후보는 버전 #{best}입니다."
        if best
        else "Stable을 넘어선 후보가 없어 운영 엔진을 유지합니다."
    )
    c.execute(
        "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,"
        "data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            int(job_id),
            int(best or job.get("base_version_id") or 0),
            "candidate_ranking_completed",
            "2단계 Candidate 비교·순위 완료",
            body,
            _json({"rankings": rows, "operating_engine_changed": False}),
            int(created_by),
            _now(),
        ),
    )
    c.commit()
    return rows


def get_rankings(c: Any, job_id: int) -> List[Dict[str, Any]]:
    job = get_job(c, job_id)
    return list((job.get("result") or {}).get("candidate_rankings") or [])
