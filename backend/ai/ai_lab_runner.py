from __future__ import annotations

import json
from typing import Any, Dict

from .ai_lab_core import (
    AI_LAB_SCHEMA_VERSION,
    _json,
    _loads,
    _now,
    ensure_ai_lab_tables,
    get_job,
    safe_int,
)
from .ai_lab_activation import load_stable_profile
from .backtest_engine import (
    BACKTEST_VERSION,
    cancel_run,
    create_run,
    get_run,
    get_summary,
    load_draws,
    process_step,
)

RUNNER_VERSION = "RC6_D7_COLDSTART_RUNNER"
_TERMINAL = {"completed", "failed", "cancelled"}


def _write_note(
    c: Any,
    *,
    job_id: int,
    version_id: int,
    note_type: str,
    title: str,
    body: str,
    data: Dict[str, Any] | None = None,
    created_by: int = 0,
) -> None:
    c.execute(
        "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            safe_int(job_id, 0, minimum=1),
            int(version_id or 0),
            str(note_type or "system")[:40],
            str(title or "")[:160],
            str(body or "")[:2000],
            _json(data or {}),
            int(created_by or 0),
            _now(),
        ),
    )


def _save_job_config(c: Any, job_id: int, config: Dict[str, Any]) -> None:
    c.execute(
        "UPDATE ai_learning_jobs SET config_json=?,updated_at=? WHERE id=?",
        (_json(config), _now(), safe_int(job_id, 0, minimum=1)),
    )


def _configure_backtest_range(c: Any, run_id: int, range_type: str) -> Dict[str, Any]:
    run = get_run(c, run_id)
    draws = load_draws(c)
    run_start = safe_int(run.get("start_round"), 1, minimum=1)
    eligible = [safe_int(d.get("round"), 0, minimum=0) for d in draws]
    eligible = [round_no for round_no in eligible if round_no >= run_start]
    if not eligible:
        raise ValueError("학습에 사용할 유효 회차가 없습니다.")

    wanted = 300 if range_type == "recent300" else 500 if range_type == "recent500" else len(eligible)
    selected = eligible[-wanted:]
    start_round = safe_int(selected[0], 1, minimum=1)
    end_round = safe_int(selected[-1], start_round, minimum=start_round)
    c.execute(
        "UPDATE backtest_runs SET start_round=?,end_round=?,next_round=?,total_rounds=?,processed_rounds=0," 
        "success_rounds=0,failed_rounds=0,skipped_rounds=0,status='ready',started_at='',completed_at='',updated_at=?,error_message='' "
        "WHERE id=?",
        (start_round, end_round, start_round, len(selected), _now(), int(run_id)),
    )
    c.execute("DELETE FROM backtest_results WHERE run_id=?", (int(run_id),))
    c.commit()
    return get_run(c, run_id)


def initialize_job(c: Any, job_id: int, *, created_by: int = 0) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    job = get_job(c, job_id)
    if job["status"] in {"completed", "cancelled"}:
        return job
    if job["status"] == "failed":
        c.execute(
            "UPDATE ai_learning_jobs SET status='ready',error_message='',completed_at='',updated_at=? WHERE id=?",
            (_now(), safe_int(job_id, 0)),
        )
        c.commit()
        job = get_job(c, job_id)

    config = dict(job.get("config") or {})
    existing_run_id = safe_int(config.get("baseline_backtest_run_id"), 0, minimum=0)
    if existing_run_id:
        try:
            existing_run = get_run(c, existing_run_id)
            # Runs created by the older 2~latest implementation must not be
            # resumed, otherwise the deployed UI would continue to show 1231
            # targets.  Rebuild the baseline automatically with cold-start v2.
            if str(existing_run.get("backtest_version") or "") == BACKTEST_VERSION:
                return job
            cancel_run(c, existing_run_id)
            config.pop("baseline_backtest_run_id", None)
            config["replaced_legacy_backtest_run_id"] = existing_run_id
        except KeyError:
            config.pop("baseline_backtest_run_id", None)

    run = create_run(
        c,
        created_by=int(created_by or job.get("created_by") or 0),
        combo_count=10,
        mode="balanced",
        min_history=1,
    )
    run = _configure_backtest_range(c, safe_int(run.get("id"), 0, minimum=1), str(job.get("range_type") or "recent300"))
    config.update(
        {
            "runner_version": RUNNER_VERSION,
            "schema_version": AI_LAB_SCHEMA_VERSION,
            "baseline_backtest_run_id": safe_int(run.get("id"), 0, minimum=1),
            "baseline_only": True,
            "optimizer_enabled": False,
            "auto_apply": False,
            "operating_engine_unchanged": True,
        }
    )
    c.execute(
        "UPDATE ai_learning_jobs SET status='ready',target_rounds=?,processed_rounds=0,config_json=?,result_json='{}'," 
        "error_message='',updated_at=? WHERE id=?",
        (safe_int(run.get("total_rounds"), 0, minimum=0), _json(config), _now(), safe_int(job_id, 0, minimum=1)),
    )
    _write_note(
        c,
        job_id=safe_int(job_id, 0, minimum=1),
        version_id=safe_int(job.get("base_version_id"), 0, minimum=0),
        note_type="baseline_initialized",
        title="Stable 기준 성능 측정 준비",
        body=f"{job.get('range_type')} 범위 {run['total_rounds']}회차를 Stable 엔진으로 측정합니다. 운영 엔진은 변경하지 않습니다.",
        data={"backtest_run_id": safe_int(run.get("id"), 0, minimum=1), "start_round": run["start_round"], "end_round": run["end_round"]},
        created_by=created_by,
    )
    c.commit()
    return get_job(c, job_id)


def process_job_step(c: Any, job_id: int, *, step_size: int = 2, created_by: int = 0) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    job = initialize_job(c, job_id, created_by=created_by)
    if job["status"] in _TERMINAL:
        return {"job": job, "processed": 0, "done": job["status"] == "completed"}
    if job["status"] == "paused":
        return {"job": job, "processed": 0, "done": False, "paused": True}

    config = dict(job.get("config") or {})
    run_id = safe_int(config.get("baseline_backtest_run_id"), 0, minimum=0)
    if not run_id:
        raise RuntimeError("기준 백테스트 실행 정보가 없습니다.")

    try:
        stable = load_stable_profile(c) or {}
        stable_label = (
            f"stable:{safe_int(stable.get('version_id'), 0, minimum=0)}:"
            f"{stable.get('profile_name') or 'legacy'}"
        )
        result = process_step(
            c,
            run_id,
            step_size=max(1, min(5, safe_int(step_size, 1, minimum=1, maximum=5))),
            weight_profile=(stable.get('weights') or None),
            profile_label=stable_label,
        )
        run = result["run"]
        status = "baseline_completed" if result.get("done") else "running"
        started_at_sql = "started_at=CASE WHEN started_at='' THEN ? ELSE started_at END,"
        c.execute(
            f"UPDATE ai_learning_jobs SET status=?,processed_rounds=?,target_rounds=?,{started_at_sql}updated_at=?,error_message='' WHERE id=?",
            (
                status,
                safe_int(run.get("processed_rounds"), 0, minimum=0),
                safe_int(run.get("total_rounds"), 0, minimum=0),
                _now(),
                _now(),
                safe_int(job_id, 0, minimum=1),
            ),
        )

        if result.get("done"):
            summary_payload = get_summary(c, run_id)
            summary = summary_payload.get("summary") or {}
            by_window = summary_payload.get("by_window") or {}
            by_strategy = summary_payload.get("by_strategy") or {}
            final_result = {
                "runner_version": RUNNER_VERSION,
                "baseline_backtest_run_id": run_id,
                "range_type": job.get("range_type"),
                "summary": summary,
                "by_window": by_window,
                "by_strategy": by_strategy,
                "operating_engine_changed": False,
                "optimizer_executed": False,
                "stable_profile": {
                    "version_id": safe_int(stable.get("version_id"), 0, minimum=0),
                    "version_name": stable.get("version_name") or "",
                    "profile_id": safe_int(stable.get("profile_id"), 0, minimum=0),
                    "profile_name": stable.get("profile_name") or "",
                    "applied": bool(stable.get("weights")),
                },
            }
            c.execute(
                "UPDATE ai_learning_jobs SET status='baseline_completed',processed_rounds=?,target_rounds=?,result_json=?,completed_at=?,updated_at=? WHERE id=?",
                (
                    safe_int(run.get("processed_rounds"), 0, minimum=0),
                    safe_int(run.get("total_rounds"), 0, minimum=0),
                    _json(final_result),
                    _now(),
                    _now(),
                    safe_int(job_id, 0, minimum=1),
                ),
            )
            version_id = safe_int(job.get("base_version_id"), 0, minimum=0)
            version = c.execute("SELECT metrics_json FROM ai_engine_versions WHERE id=?", (version_id,)).fetchone()
            metrics = _loads(version["metrics_json"] if version else "{}", {})
            metrics["stable_baseline"] = {
                "measured_at": _now(),
                "range_type": job.get("range_type"),
                "summary": summary,
                "by_window": by_window,
                "by_strategy": by_strategy,
                "backtest_run_id": run_id,
            }
            c.execute("UPDATE ai_engine_versions SET metrics_json=? WHERE id=?", (_json(metrics), version_id))
            _write_note(
                c,
                job_id=safe_int(job_id, 0, minimum=1),
                version_id=version_id,
                note_type="baseline_completed",
                title="Stable 기준 성능 측정 완료",
                body=(
                    f"{safe_int(summary.get('evaluated_rounds'), 0, minimum=0)}회차를 평가했습니다. "
                    f"평균 최고 일치 {float(summary.get('avg_best_match') or 0):.4f}, "
                    f"추천 풀 평균 포함 {float(summary.get('avg_pool_match') or 0):.4f}입니다."
                ),
                data=final_result,
                created_by=created_by,
            )
        c.commit()
        updated = get_job(c, job_id)
        return {
            "job": updated,
            "processed": safe_int(result.get("processed"), 0, minimum=0),
            "done": updated["status"] in {"baseline_completed", "completed"},
            "backtest_run": run,
        }
    except Exception as exc:
        c.execute(
            "UPDATE ai_learning_jobs SET status='failed',error_message=?,completed_at=?,updated_at=? WHERE id=?",
            (str(exc)[:1000], _now(), _now(), safe_int(job_id, 0, minimum=1)),
        )
        _write_note(
            c,
            job_id=safe_int(job_id, 0, minimum=1),
            version_id=safe_int(job.get("base_version_id"), 0, minimum=0),
            note_type="baseline_failed",
            title="Stable 기준 성능 측정 실패",
            body=str(exc)[:1800],
            data={"runner_version": RUNNER_VERSION},
            created_by=created_by,
        )
        c.commit()
        raise


def pause_job(c: Any, job_id: int, *, created_by: int = 0) -> Dict[str, Any]:
    job = get_job(c, job_id)
    if job["status"] in _TERMINAL:
        return job
    c.execute("UPDATE ai_learning_jobs SET status='paused',updated_at=? WHERE id=?", (_now(), safe_int(job_id, 0, minimum=1)))
    _write_note(
        c,
        job_id=safe_int(job_id, 0, minimum=1),
        version_id=safe_int(job.get("base_version_id"), 0, minimum=0),
        note_type="job_paused",
        title="학습 작업 일시정지",
        body="관리자가 Stable 기준 성능 측정을 일시정지했습니다.",
        created_by=created_by,
    )
    c.commit()
    return get_job(c, job_id)


def resume_job(c: Any, job_id: int, *, created_by: int = 0) -> Dict[str, Any]:
    job = get_job(c, job_id)
    if job["status"] != "paused":
        return job
    c.execute("UPDATE ai_learning_jobs SET status='ready',updated_at=? WHERE id=?", (_now(), safe_int(job_id, 0, minimum=1)))
    _write_note(
        c,
        job_id=safe_int(job_id, 0, minimum=1),
        version_id=safe_int(job.get("base_version_id"), 0, minimum=0),
        note_type="job_resumed",
        title="학습 작업 재개",
        body="중단 지점부터 Stable 기준 성능 측정을 재개합니다.",
        created_by=created_by,
    )
    c.commit()
    return get_job(c, job_id)


def cancel_job_with_run(c: Any, job_id: int, *, created_by: int = 0) -> Dict[str, Any]:
    job = get_job(c, job_id)
    config = dict(job.get("config") or {})
    run_id = safe_int(config.get("baseline_backtest_run_id"), 0, minimum=0)
    if run_id:
        try:
            cancel_run(c, run_id)
        except KeyError:
            pass
    if job["status"] not in _TERMINAL:
        c.execute(
            "UPDATE ai_learning_jobs SET status='cancelled',completed_at=?,updated_at=? WHERE id=?",
            (_now(), _now(), safe_int(job_id, 0, minimum=1)),
        )
        _write_note(
            c,
            job_id=safe_int(job_id, 0, minimum=1),
            version_id=safe_int(job.get("base_version_id"), 0, minimum=0),
            note_type="job_cancelled",
            title="학습 작업 중단",
            body="관리자가 Stable 기준 성능 측정과 연결된 백테스트를 중단했습니다.",
            data={"backtest_run_id": run_id},
            created_by=created_by,
        )
        c.commit()
    return get_job(c, job_id)
