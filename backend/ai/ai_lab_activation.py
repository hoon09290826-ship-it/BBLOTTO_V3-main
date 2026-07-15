from __future__ import annotations

from typing import Any, Dict, List, Optional

from .ai_lab_core import _json, _loads, _now, ensure_ai_lab_tables, get_job

ACTIVATION_VERSION = "RC6_D1_5_STABLE_APPROVAL"


def ensure_activation_tables(c: Any) -> None:
    ensure_ai_lab_tables(c)
    c.execute(
        "CREATE TABLE IF NOT EXISTS ai_engine_activations("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER DEFAULT 0, "
        "from_version_id INTEGER DEFAULT 0, to_version_id INTEGER DEFAULT 0, "
        "action TEXT DEFAULT 'approve', reason TEXT DEFAULT '', metrics_json TEXT DEFAULT '{}', "
        "created_by INTEGER DEFAULT 0, created_at TEXT DEFAULT ''"
        ")"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_activations_created ON ai_engine_activations(id)")


def _version_with_profile(c: Any, version_id: int) -> Dict[str, Any]:
    row = c.execute(
        "SELECT v.*,p.name AS profile_name,p.weights_json,p.fingerprint,p.is_locked "
        "FROM ai_engine_versions v JOIN ai_weight_profiles p ON p.id=v.profile_id WHERE v.id=?",
        (int(version_id),),
    ).fetchone()
    if not row:
        raise KeyError("엔진 버전을 찾을 수 없습니다.")
    item = dict(row)
    item["metrics"] = _loads(item.pop("metrics_json", "{}"), {})
    item["weights"] = _loads(item.pop("weights_json", "{}"), {})
    item["is_locked"] = bool(item.get("is_locked"))
    return item


def load_stable_profile(c: Any) -> Dict[str, Any]:
    """Return the currently approved Stable profile. Empty dict means safe legacy fallback."""
    ensure_activation_tables(c)
    row = c.execute(
        "SELECT v.id AS version_id,v.version_name,v.engine_code_version,v.profile_id,p.name AS profile_name,p.weights_json,p.fingerprint "
        "FROM ai_engine_versions v JOIN ai_weight_profiles p ON p.id=v.profile_id "
        "WHERE v.status='stable' ORDER BY v.id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {}
    item = dict(row)
    weights = _loads(item.pop("weights_json", "{}"), {})
    if not isinstance(weights, dict) or not weights:
        return {}
    item["weights"] = weights
    item["activation_version"] = ACTIVATION_VERSION
    return item


def approve_best_candidate(c: Any, job_id: int, version_id: int, *, reason: str, created_by: int) -> Dict[str, Any]:
    ensure_activation_tables(c)
    job = get_job(c, int(job_id))
    if job.get("status") != "candidates_ranked":
        raise ValueError("Candidate 비교·순위가 완료된 작업만 승인할 수 있습니다.")
    best_id = int(job.get("best_candidate_version_id") or 0)
    if best_id <= 0:
        raise ValueError("Stable보다 개선된 승인 후보가 없습니다.")
    if int(version_id) != best_id:
        raise ValueError(f"안전을 위해 1위 Candidate #{best_id}만 승인할 수 있습니다.")

    candidate = _version_with_profile(c, int(version_id))
    if candidate.get("status") != "candidate":
        raise ValueError("승인 가능한 Candidate 상태가 아닙니다.")
    metrics = candidate.get("metrics") or {}
    if metrics.get("validation_status") != "backtest_completed" or float(metrics.get("improvement") or 0) <= 0:
        raise ValueError("백테스트 개선이 확인된 Candidate만 승인할 수 있습니다.")

    stable_row = c.execute("SELECT * FROM ai_engine_versions WHERE status='stable' ORDER BY id DESC LIMIT 1").fetchone()
    if not stable_row:
        raise ValueError("현재 Stable 엔진이 없습니다.")
    stable_id = int(stable_row["id"])
    if int(candidate.get("parent_version_id") or 0) != stable_id:
        raise ValueError("현재 Stable을 기준으로 생성된 Candidate가 아닙니다. 새 학습 작업을 실행하세요.")

    now = _now()
    reason_text = str(reason or "관리자 승인").strip()[:500]
    try:
        c.execute("UPDATE ai_engine_versions SET status='retired',retired_at=? WHERE id=? AND status='stable'", (now, stable_id))
        c.execute(
            "UPDATE ai_engine_versions SET status='stable',activated_at=?,retired_at='',notes=? WHERE id=? AND status='candidate'",
            (now, f"RC6-D1 5단계 관리자 승인. {reason_text}", int(version_id)),
        )
        c.execute("UPDATE ai_weight_profiles SET is_locked=1,updated_at=? WHERE id=?", (now, int(candidate["profile_id"])))
        cur = c.execute(
            "INSERT INTO ai_engine_activations(job_id,from_version_id,to_version_id,action,reason,metrics_json,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (int(job_id), stable_id, int(version_id), "approve", reason_text, _json(metrics), int(created_by), now),
        )
        activation_id = int(cur.lastrowid or 0)
        result = dict(job.get("result") or {})
        result.update({
            "approved_version_id": int(version_id),
            "previous_stable_version_id": stable_id,
            "approved_at": now,
            "operating_engine_changed": True,
            "activation_version": ACTIVATION_VERSION,
        })
        c.execute(
            "UPDATE ai_learning_jobs SET status='approved',result_json=?,completed_at=?,updated_at=? WHERE id=?",
            (_json(result), now, now, int(job_id)),
        )
        c.execute(
            "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (int(job_id), int(version_id), "stable_approved", "Candidate Stable 승인", f"Candidate #{version_id}를 새 Stable로 승인했습니다. 이전 Stable은 #{stable_id}입니다.", _json({"reason": reason_text, "activation_id": activation_id, "metrics": metrics}), int(created_by), now),
        )
        c.commit()
    except Exception:
        c.rollback()
        raise
    return {"activation_id": activation_id, "previous_stable": _version_with_profile(c, stable_id), "stable": _version_with_profile(c, int(version_id)), "job": get_job(c, int(job_id))}


def rollback_stable(c: Any, target_version_id: int, *, reason: str, created_by: int) -> Dict[str, Any]:
    ensure_activation_tables(c)
    current_row = c.execute("SELECT * FROM ai_engine_versions WHERE status='stable' ORDER BY id DESC LIMIT 1").fetchone()
    if not current_row:
        raise ValueError("현재 Stable 엔진이 없습니다.")
    current_id = int(current_row["id"])
    target_id = int(target_version_id)
    if target_id == current_id:
        raise ValueError("이미 현재 Stable 엔진입니다.")
    target = _version_with_profile(c, target_id)
    if target.get("status") not in {"retired", "candidate"}:
        raise ValueError("롤백 가능한 엔진 버전이 아닙니다.")

    # Only allow a version that was previously Stable (activation source or bootstrap Stable).
    prior = c.execute(
        "SELECT id FROM ai_engine_activations WHERE from_version_id=? OR to_version_id=? ORDER BY id DESC LIMIT 1",
        (target_id, target_id),
    ).fetchone()
    if not prior and not target.get("activated_at"):
        raise ValueError("이전에 Stable로 사용된 이력이 있는 버전만 롤백할 수 있습니다.")

    now = _now()
    reason_text = str(reason or "관리자 롤백").strip()[:500]
    try:
        c.execute("UPDATE ai_engine_versions SET status='retired',retired_at=? WHERE id=? AND status='stable'", (now, current_id))
        c.execute("UPDATE ai_engine_versions SET status='stable',activated_at=?,retired_at='',notes=? WHERE id=?", (now, f"RC6-D1 5단계 롤백. {reason_text}", target_id))
        c.execute("UPDATE ai_weight_profiles SET is_locked=1,updated_at=? WHERE id=?", (now, int(target["profile_id"])))
        cur = c.execute(
            "INSERT INTO ai_engine_activations(job_id,from_version_id,to_version_id,action,reason,metrics_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (0, current_id, target_id, "rollback", reason_text, _json({"activation_version": ACTIVATION_VERSION}), int(created_by), now),
        )
        activation_id = int(cur.lastrowid or 0)
        c.execute(
            "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (0, target_id, "stable_rollback", "Stable 엔진 롤백", f"Stable 엔진을 #{current_id}에서 #{target_id}로 롤백했습니다.", _json({"reason": reason_text, "activation_id": activation_id}), int(created_by), now),
        )
        c.commit()
    except Exception:
        c.rollback()
        raise
    return {"activation_id": activation_id, "previous_stable": _version_with_profile(c, current_id), "stable": _version_with_profile(c, target_id)}


def list_activations(c: Any, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_activation_tables(c)
    rows = c.execute(
        "SELECT a.*,fv.version_name AS from_version_name,tv.version_name AS to_version_name "
        "FROM ai_engine_activations a "
        "LEFT JOIN ai_engine_versions fv ON fv.id=a.from_version_id "
        "LEFT JOIN ai_engine_versions tv ON tv.id=a.to_version_id "
        "ORDER BY a.id DESC LIMIT ?",
        (max(1, min(300, int(limit))),),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metrics"] = _loads(item.pop("metrics_json", "{}"), {})
        out.append(item)
    return out
