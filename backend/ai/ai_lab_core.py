from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict, List, Optional

AI_LAB_SCHEMA_VERSION = "RC6_D1_5"
DEFAULT_PROFILE_NAME = "RC4.5 Stable Baseline"
DEFAULT_WEIGHTS: Dict[str, float] = {
    "recent_10": 0.20,
    "recent_30": 0.22,
    "recent_100": 0.18,
    "full_history": 0.12,
    "momentum": 0.08,
    "overdue": 0.07,
    "pair": 0.07,
    "combo_balance": 0.06,
}
ALLOWED_JOB_RANGES = {"recent300", "recent500", "all"}


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else fallback
    except Exception:
        return fallback


def _row(row: Any) -> Dict[str, Any]:
    return dict(row) if row else {}


def safe_int(value: Any, default: int = 0, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    """Convert nullable/invalid DB values to a bounded integer."""
    try:
        result = int(value) if value not in (None, "") else int(default)
    except (TypeError, ValueError, OverflowError):
        result = int(default)
    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def _fingerprint(weights: Dict[str, Any]) -> str:
    return hashlib.sha256(_json(weights).encode("utf-8")).hexdigest()[:16]


def validate_weights(weights: Dict[str, Any]) -> Dict[str, float]:
    if not isinstance(weights, dict) or not weights:
        raise ValueError("가중치 프로필이 비어 있습니다.")
    clean: Dict[str, float] = {}
    for key, value in weights.items():
        name = str(key or "").strip()
        if not name:
            raise ValueError("가중치 항목 이름이 비어 있습니다.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} 가중치는 숫자여야 합니다.")
        if number < 0 or number > 1:
            raise ValueError(f"{name} 가중치는 0~1 범위여야 합니다.")
        clean[name] = round(number, 6)
    total = sum(clean.values())
    if not 0.99 <= total <= 1.01:
        raise ValueError(f"가중치 합계는 1.0이어야 합니다. 현재 {total:.6f}입니다.")
    return clean


def ensure_ai_lab_tables(c: Any) -> None:
    c.execute(
        "CREATE TABLE IF NOT EXISTS ai_weight_profiles("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT DEFAULT '', "
        "weights_json TEXT DEFAULT '{}', fingerprint TEXT DEFAULT '', source TEXT DEFAULT 'manual', "
        "is_locked INTEGER DEFAULT 0, created_by INTEGER DEFAULT 0, created_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS ai_engine_versions("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, version_name TEXT NOT NULL, engine_code_version TEXT DEFAULT '', "
        "profile_id INTEGER DEFAULT 0, status TEXT DEFAULT 'candidate', parent_version_id INTEGER DEFAULT 0, "
        "metrics_json TEXT DEFAULT '{}', notes TEXT DEFAULT '', created_by INTEGER DEFAULT 0, "
        "created_at TEXT DEFAULT '', activated_at TEXT DEFAULT '', retired_at TEXT DEFAULT ''"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS ai_learning_jobs("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'ready', range_type TEXT DEFAULT 'recent300', "
        "base_version_id INTEGER DEFAULT 0, profile_id INTEGER DEFAULT 0, target_rounds INTEGER DEFAULT 300, "
        "processed_rounds INTEGER DEFAULT 0, candidate_limit INTEGER DEFAULT 12, random_seed INTEGER DEFAULT 0, "
        "best_candidate_version_id INTEGER DEFAULT 0, config_json TEXT DEFAULT '{}', result_json TEXT DEFAULT '{}', "
        "error_message TEXT DEFAULT '', created_by INTEGER DEFAULT 0, created_at TEXT DEFAULT '', "
        "started_at TEXT DEFAULT '', completed_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS ai_learning_notes("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER DEFAULT 0, version_id INTEGER DEFAULT 0, "
        "note_type TEXT DEFAULT 'system', title TEXT DEFAULT '', body TEXT DEFAULT '', data_json TEXT DEFAULT '{}', "
        "created_by INTEGER DEFAULT 0, created_at TEXT DEFAULT ''"
        ")"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_versions_status ON ai_engine_versions(status,id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_learning_jobs(status,id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_notes_job ON ai_learning_notes(job_id,id)")
    # 행 기본값 보정은 읽기 변환(_job_dict)에서 처리합니다. 조회 API마다
    # 전체 UPDATE를 실행하면 후보 비교 요청과 PostgreSQL 행 잠금이 교차해
    # deadlock이 발생하므로 스키마 확인 단계에서는 데이터를 갱신하지 않습니다.


def bootstrap(c: Any, *, engine_code_version: str, created_by: int = 0) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    profile = c.execute("SELECT * FROM ai_weight_profiles ORDER BY id LIMIT 1").fetchone()
    if not profile:
        weights = validate_weights(DEFAULT_WEIGHTS)
        cur = c.execute(
            "INSERT INTO ai_weight_profiles(name,description,weights_json,fingerprint,source,is_locked,created_by,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (DEFAULT_PROFILE_NAME, "RC4.5 운영 엔진 기준 가중치 메타데이터", _json(weights), _fingerprint(weights), "bootstrap", 1, created_by, _now(), _now()),
        )
        if cur.lastrowid is not None:
            profile_id = int(cur.lastrowid)
        else:
            saved = c.execute("SELECT id FROM ai_weight_profiles WHERE fingerprint=? AND source='bootstrap' ORDER BY id DESC LIMIT 1", (_fingerprint(weights),)).fetchone()
            if not saved:
                raise RuntimeError("기본 가중치 프로필 저장에 실패했습니다.")
            profile_id = int(saved["id"])
    else:
        profile_id = int(profile["id"])
    stable = c.execute("SELECT * FROM ai_engine_versions WHERE status='stable' ORDER BY id DESC LIMIT 1").fetchone()
    if not stable:
        cur = c.execute(
            "INSERT INTO ai_engine_versions(version_name,engine_code_version,profile_id,status,parent_version_id,metrics_json,notes,created_by,created_at,activated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (f"{engine_code_version} Stable", engine_code_version, profile_id, "stable", 0, "{}", "RC6-D1 도입 시점 운영 엔진", created_by, _now(), _now()),
        )
        if cur.lastrowid is not None:
            stable_id = int(cur.lastrowid)
        else:
            saved = c.execute("SELECT id FROM ai_engine_versions WHERE status='stable' AND engine_code_version=? ORDER BY id DESC LIMIT 1", (engine_code_version,)).fetchone()
            if not saved:
                raise RuntimeError("Stable 엔진 버전 저장에 실패했습니다.")
            stable_id = int(saved["id"])
    else:
        stable_id = int(stable["id"])
    c.commit()
    return {"profile_id": profile_id, "stable_version_id": stable_id, "schema_version": AI_LAB_SCHEMA_VERSION}


def _profile_dict(row: Any) -> Dict[str, Any]:
    item = _row(row)
    if item:
        item["weights"] = _loads(item.pop("weights_json", "{}"), {})
        item["is_locked"] = bool(item.get("is_locked"))
    return item


def _version_dict(row: Any) -> Dict[str, Any]:
    item = _row(row)
    if item:
        item["metrics"] = _loads(item.pop("metrics_json", "{}"), {})
    return item


def _job_dict(row: Any) -> Dict[str, Any]:
    item = _row(row)
    if item:
        item["config"] = _loads(item.pop("config_json", "{}"), {})
        item["result"] = _loads(item.pop("result_json", "{}"), {})
        target = safe_int(item.get("target_rounds"), 0, minimum=1)
        processed = safe_int(item.get("processed_rounds"), 0, minimum=0)
        item["target_rounds"] = safe_int(item.get("target_rounds"), 0, minimum=0)
        item["processed_rounds"] = processed
        item["progress_percent"] = round(min(processed, target) * 100 / target, 2)
        # Frontend/API compatibility: always expose both id and job_id.
        item["id"] = safe_int(item.get("id") or item.get("job_id"), 0, minimum=1)
        item["job_id"] = item["id"]
    return item



def recover_orphaned_jobs(c: Any, *, stale_minutes: int = 30, created_by: int = 0) -> List[int]:
    """Mark stale running jobs as failed after a server restart/crash.

    Ready/paused/baseline-completed jobs are intentionally preserved because
    they can be resumed or cancelled by an administrator. Only a stale
    ``running`` row can falsely block the UI when no worker exists.
    """
    ensure_ai_lab_tables(c)
    minutes = max(5, min(24 * 60, safe_int(stale_minutes, 30, minimum=5)))
    rows = c.execute(
        "SELECT * FROM ai_learning_jobs WHERE status='running' ORDER BY id"
    ).fetchall()
    recovered: List[int] = []
    now = dt.datetime.now()
    for row in rows:
        item = _row(row)
        stamp = str(item.get('updated_at') or item.get('started_at') or item.get('created_at') or '').strip()
        try:
            updated = dt.datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            updated = dt.datetime.min
        if (now - updated).total_seconds() < minutes * 60:
            continue
        job_id = safe_int(item.get('id'), 0, minimum=1)
        message = '서버 재시작 또는 연결 종료로 실행 상태가 남아 자동 복구되었습니다.'
        c.execute(
            "UPDATE ai_learning_jobs SET status='failed',error_message=?,completed_at=?,updated_at=? WHERE id=?",
            (message, _now(), _now(), job_id),
        )
        c.execute(
            "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (job_id, safe_int(item.get('base_version_id'), 0), 'orphan_recovered',
             '고아 학습 작업 자동 복구', message, '{}', int(created_by or 0), _now()),
        )
        recovered.append(job_id)
    if recovered:
        c.commit()
    return recovered

def get_overview(c: Any) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    stable = c.execute("SELECT * FROM ai_engine_versions WHERE status='stable' ORDER BY id DESC LIMIT 1").fetchone()
    counts = {}
    for table, key in (("ai_engine_versions", "versions"), ("ai_weight_profiles", "profiles"), ("ai_learning_jobs", "jobs"), ("ai_learning_notes", "notes")):
        row = c.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
        counts[key] = int(row["cnt"] or 0)
    active = c.execute("SELECT * FROM ai_learning_jobs WHERE status IN ('ready','running','paused','baseline_completed','candidates_ready','candidates_testing') ORDER BY id DESC LIMIT 1").fetchone()
    return {"schema_version": AI_LAB_SCHEMA_VERSION, "stable": _version_dict(stable), "active_job": _job_dict(active), "counts": counts}


def list_profiles(c: Any, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_ai_lab_tables(c)
    rows = c.execute("SELECT * FROM ai_weight_profiles ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
    return [_profile_dict(row) for row in rows]


def create_profile(c: Any, *, name: str, description: str, weights: Dict[str, Any], created_by: int) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    name = str(name or "").strip()
    if len(name) < 2 or len(name) > 80:
        raise ValueError("프로필 이름은 2~80자로 입력하세요.")
    clean = validate_weights(weights)
    cur = c.execute(
        "INSERT INTO ai_weight_profiles(name,description,weights_json,fingerprint,source,is_locked,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (name, str(description or "")[:500], _json(clean), _fingerprint(clean), "manual", 0, created_by, _now(), _now()),
    )
    if cur.lastrowid is not None:
        profile_id = int(cur.lastrowid)
    else:
        saved = c.execute("SELECT id FROM ai_weight_profiles WHERE fingerprint=? AND created_by=? ORDER BY id DESC LIMIT 1", (_fingerprint(clean), created_by)).fetchone()
        if not saved:
            raise RuntimeError("가중치 프로필 저장에 실패했습니다.")
        profile_id = int(saved["id"])
    c.commit()
    return _profile_dict(c.execute("SELECT * FROM ai_weight_profiles WHERE id=?", (profile_id,)).fetchone())


def list_versions(c: Any, status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    ensure_ai_lab_tables(c)
    if status:
        rows = c.execute("SELECT * FROM ai_engine_versions WHERE status=? ORDER BY id DESC LIMIT ?", (status, max(1, min(200, int(limit))))).fetchall()
    else:
        rows = c.execute("SELECT * FROM ai_engine_versions ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
    return [_version_dict(row) for row in rows]


def create_learning_job(c: Any, *, range_type: str, candidate_limit: int, random_seed: int, created_by: int) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    range_type = str(range_type or "recent300").strip().lower()
    if range_type not in ALLOWED_JOB_RANGES:
        raise ValueError("학습 범위는 recent300, recent500, all 중 하나여야 합니다.")
    running = c.execute("SELECT id FROM ai_learning_jobs WHERE status IN ('ready','running','paused','baseline_completed','candidates_ready','candidates_testing') ORDER BY id DESC LIMIT 1").fetchone()
    if running:
        raise ValueError(f"완료되지 않은 학습 작업 #{running['id']}이 있습니다.")
    stable = c.execute("SELECT * FROM ai_engine_versions WHERE status='stable' ORDER BY id DESC LIMIT 1").fetchone()
    if not stable:
        raise ValueError("Stable 엔진이 없습니다.")
    profile_id = int(stable["profile_id"] or 0)
    target = 300 if range_type == "recent300" else 500 if range_type == "recent500" else 0
    config = {"auto_apply": False, "operating_engine_unchanged": True, "optimizer_enabled": False, "baseline_runner_enabled": True, "schema_version": AI_LAB_SCHEMA_VERSION}
    cur = c.execute(
        "INSERT INTO ai_learning_jobs(status,range_type,base_version_id,profile_id,target_rounds,processed_rounds,candidate_limit,random_seed,config_json,result_json,error_message,created_by,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("ready", range_type, int(stable["id"]), profile_id, target, 0, max(1, min(100, int(candidate_limit))), int(random_seed or 0), _json(config), "{}", "", created_by, _now(), _now()),
    )
    if cur.lastrowid is not None:
        job_id = int(cur.lastrowid)
    else:
        saved = c.execute("SELECT id FROM ai_learning_jobs WHERE created_by=? AND base_version_id=? AND status='ready' ORDER BY id DESC LIMIT 1", (created_by, int(stable["id"]))).fetchone()
        if not saved:
            raise RuntimeError("학습 작업 저장에 실패했습니다.")
        job_id = int(saved["id"])
    c.execute(
        "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (job_id, int(stable["id"]), "job_created", "학습 작업 생성", "RC6-D1 2단계에서는 Stable 기준 성능을 측정하며 운영 엔진을 변경하지 않습니다.", _json(config), created_by, _now()),
    )
    c.commit()
    return get_job(c, job_id)


def get_job(c: Any, job_id: int) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    row = c.execute("SELECT * FROM ai_learning_jobs WHERE id=?", (int(job_id),)).fetchone()
    if not row:
        raise KeyError("학습 작업을 찾을 수 없습니다.")
    item = _job_dict(row)
    if item.get("status") == "candidates_testing":
        run_map = (item.get("result") or {}).get("candidate_backtest_runs") or {}
        run_ids = [safe_int(value, 0, minimum=0) for value in run_map.values()]
        run_ids = [value for value in run_ids if value > 0]
        processed = total = completed = 0
        for run_id in run_ids:
            run = c.execute(
                "SELECT status,processed_rounds,total_rounds FROM backtest_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if not run:
                continue
            processed += safe_int(run["processed_rounds"], 0, minimum=0)
            total += safe_int(run["total_rounds"], 0, minimum=0)
            if str(run["status"] or "") == "completed":
                completed += 1
        item["candidate_processed_rounds"] = processed
        item["candidate_total_rounds"] = total
        item["candidate_completed_runs"] = completed
        item["candidate_run_count"] = len(run_ids)
        item["candidate_progress_percent"] = round(processed * 100 / total, 2) if total else 0.0
    return item


def list_jobs(c: Any, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_ai_lab_tables(c)
    rows = c.execute("SELECT * FROM ai_learning_jobs ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
    return [_job_dict(row) for row in rows]


def cancel_job(c: Any, job_id: int, *, created_by: int) -> Dict[str, Any]:
    job = get_job(c, job_id)
    if job["status"] in {"completed", "failed", "cancelled"}:
        return job
    c.execute("UPDATE ai_learning_jobs SET status='cancelled',completed_at=?,updated_at=? WHERE id=?", (_now(), _now(), int(job_id)))
    c.execute(
        "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (int(job_id), int(job.get("base_version_id") or 0), "job_cancelled", "학습 작업 중단", "관리자가 학습 작업을 중단했습니다.", "{}", created_by, _now()),
    )
    c.commit()
    return get_job(c, job_id)


def list_notes(c: Any, job_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_ai_lab_tables(c)
    if job_id:
        rows = c.execute("SELECT * FROM ai_learning_notes WHERE job_id=? ORDER BY id DESC LIMIT ?", (int(job_id), max(1, min(300, int(limit))))).fetchall()
    else:
        rows = c.execute("SELECT * FROM ai_learning_notes ORDER BY id DESC LIMIT ?", (max(1, min(300, int(limit))),)).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["data"] = _loads(item.pop("data_json", "{}"), {})
        out.append(item)
    return out
