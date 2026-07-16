from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from .ai_lab_core import (
    AI_LAB_SCHEMA_VERSION,
    _fingerprint,
    _json,
    _loads,
    _now,
    _profile_dict,
    _version_dict,
    ensure_ai_lab_tables,
    get_job,
    validate_weights,
)

CANDIDATE_GENERATOR_VERSION = "RC6_D1_3_CANDIDATE_GENERATOR"
_MIN_WEIGHT = 0.02
_MAX_WEIGHT = 0.38
_MAX_ABS_DELTA = 0.08
_TERMINAL_OK = {"baseline_completed", "completed", "candidates_ready"}



def _inserted_id(c, cur, table: str, *, lookup_sql: str = "", lookup_params=()) -> int:
    """Return a committed insert id on both SQLite and PostgreSQL.

    PostgreSQL compatibility normally supplies ``lastrowid`` through
    ``RETURNING id``.  The lookup fallback protects existing deployments or
    custom DB wrappers from ever converting ``None`` to ``int``.
    """
    value = getattr(cur, "lastrowid", None)
    try:
        if value not in (None, ""):
            result = int(value)
            if result > 0:
                return result
    except (TypeError, ValueError):
        pass
    if lookup_sql:
        row = c.execute(lookup_sql, tuple(lookup_params or ())).fetchone()
        if row:
            candidate = row.get("id") if hasattr(row, "get") else row[0]
            try:
                result = int(candidate)
                if result > 0:
                    return result
            except (TypeError, ValueError):
                pass
    raise RuntimeError(f"{table} INSERT 후 생성 ID를 확인하지 못했습니다.")

def _stable_context(c: Any, job: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    version = c.execute(
        "SELECT * FROM ai_engine_versions WHERE id=?",
        (int(job.get("base_version_id") or 0),),
    ).fetchone()
    if not version:
        raise ValueError("학습 작업의 Stable 엔진 버전을 찾을 수 없습니다.")
    version_item = _version_dict(version)
    if version_item.get("status") != "stable":
        raise ValueError("학습 기준 엔진이 Stable 상태가 아닙니다.")

    profile = c.execute(
        "SELECT * FROM ai_weight_profiles WHERE id=?",
        (int(version_item.get("profile_id") or 0),),
    ).fetchone()
    if not profile:
        raise ValueError("Stable 엔진의 가중치 프로필을 찾을 수 없습니다.")
    profile_item = _profile_dict(profile)
    profile_item["weights"] = validate_weights(profile_item.get("weights") or {})
    return version_item, profile_item


def _normalize(raw: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(0.0, float(v)) for v in raw.values())
    if total <= 0:
        raise ValueError("후보 가중치 합계가 0입니다.")
    normalized = {key: max(0.0, float(value)) / total for key, value in raw.items()}

    # 정규화 후 경계값을 벗어나는 항목을 기준값 쪽으로 완화한다.
    for _ in range(8):
        changed = False
        for key, value in list(normalized.items()):
            clipped = min(_MAX_WEIGHT, max(_MIN_WEIGHT, value))
            if abs(clipped - value) > 1e-12:
                normalized[key] = clipped
                changed = True
        total = sum(normalized.values())
        normalized = {key: value / total for key, value in normalized.items()}
        if not changed:
            break

    rounded = {key: round(value, 6) for key, value in normalized.items()}
    diff = round(1.0 - sum(rounded.values()), 6)
    if diff:
        key = max(rounded, key=rounded.get)
        rounded[key] = round(rounded[key] + diff, 6)
    return validate_weights(rounded)


def _mutate(base: Dict[str, float], rng: random.Random, index: int) -> Dict[str, float]:
    keys = list(base.keys())
    if len(keys) < 2:
        raise ValueError("후보 생성을 위해 최소 2개의 가중치 항목이 필요합니다.")

    candidate = dict(base)
    # 한 후보에서 2~4쌍만 이동시켜 운영 기준에서 과도하게 멀어지지 않게 한다.
    pair_count = 2 + (index % min(3, max(1, len(keys) // 2)))
    for _ in range(pair_count):
        source, target = rng.sample(keys, 2)
        movable = min(
            max(0.0, candidate[source] - _MIN_WEIGHT),
            max(0.0, candidate[source] - (base[source] - _MAX_ABS_DELTA)),
        )
        capacity = min(
            max(0.0, _MAX_WEIGHT - candidate[target]),
            max(0.0, (base[target] + _MAX_ABS_DELTA) - candidate[target]),
        )
        ceiling = min(movable, capacity)
        if ceiling < 0.005:
            continue
        amount = rng.uniform(0.005, ceiling)
        candidate[source] -= amount
        candidate[target] += amount

    rounded = {key: round(value, 6) for key, value in candidate.items()}
    diff = round(1.0 - sum(rounded.values()), 6)
    if diff:
        key = max(rounded, key=rounded.get)
        rounded[key] = round(rounded[key] + diff, 6)
    candidate = validate_weights(rounded)
    for key, value in candidate.items():
        if value < _MIN_WEIGHT - 1e-6 or value > _MAX_WEIGHT + 1e-6:
            raise ValueError("후보 가중치가 안전 범위를 벗어났습니다.")
        if abs(value - base[key]) > _MAX_ABS_DELTA + 1e-6:
            raise ValueError("후보 가중치 변화폭이 안전 한도를 초과했습니다.")
    return candidate


def _delta_summary(base: Dict[str, float], candidate: Dict[str, float]) -> List[Dict[str, Any]]:
    rows = []
    for key in base:
        delta = round(candidate[key] - base[key], 6)
        if abs(delta) >= 0.000001:
            rows.append(
                {
                    "key": key,
                    "before": base[key],
                    "after": candidate[key],
                    "delta": delta,
                }
            )
    return sorted(rows, key=lambda item: abs(float(item["delta"])), reverse=True)


def generate_candidates(c: Any, job_id: int, *, created_by: int = 0, force: bool = False) -> Dict[str, Any]:
    ensure_ai_lab_tables(c)
    job = get_job(c, job_id)
    if job.get("status") not in _TERMINAL_OK:
        raise ValueError("Stable 기준 성능 측정이 완료된 작업에서만 후보를 생성할 수 있습니다.")

    result = dict(job.get("result") or {})
    baseline = result.get("summary") or {}
    if not baseline:
        raise ValueError("Stable 기준 성능 결과가 없어 후보를 생성할 수 없습니다.")

    existing_ids = [int(v) for v in (result.get("candidate_version_ids") or []) if int(v or 0) > 0]
    if existing_ids and not force:
        return {
            "job": job,
            "candidate_version_ids": existing_ids,
            "created_count": 0,
            "reused": True,
            "operating_engine_changed": False,
        }

    stable, profile = _stable_context(c, job)
    base_weights = dict(profile["weights"])
    limit = max(2, min(50, int(job.get("candidate_limit") or 12)))
    seed = int(job.get("random_seed") or 0) or (int(job_id) * 1009 + int(stable["id"]) * 97)
    rng = random.Random(seed)

    if force and existing_ids:
        placeholders = ",".join("?" for _ in existing_ids)
        c.execute(
            f"UPDATE ai_engine_versions SET status='discarded',retired_at=? WHERE id IN ({placeholders}) AND status='candidate'",
            (_now(), *existing_ids),
        )

    fingerprints = {str(profile.get("fingerprint") or _fingerprint(base_weights))}
    created_versions: List[int] = []
    created_profiles: List[int] = []
    candidate_rows: List[Dict[str, Any]] = []
    attempts = 0
    max_attempts = limit * 40

    while len(created_versions) < limit and attempts < max_attempts:
        attempts += 1
        weights = _mutate(base_weights, rng, len(created_versions))
        fingerprint = _fingerprint(weights)
        if fingerprint in fingerprints:
            continue
        duplicate = c.execute(
            "SELECT id FROM ai_weight_profiles WHERE fingerprint=? ORDER BY id DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        if duplicate:
            fingerprints.add(fingerprint)
            continue

        number = len(created_versions) + 1
        deltas = _delta_summary(base_weights, weights)
        cur = c.execute(
            "INSERT INTO ai_weight_profiles(name,description,weights_json,fingerprint,source,is_locked,created_by,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                f"Job {job_id} Candidate {number}",
                "Stable 기준에서 안전 범위 내 가중치 이동으로 생성된 검증 대기 후보",
                _json(weights),
                fingerprint,
                "candidate_generator",
                1,
                int(created_by or job.get("created_by") or 0),
                _now(),
                _now(),
            ),
        )
        profile_id = _inserted_id(
            c,
            cur,
            "ai_weight_profiles",
            lookup_sql="SELECT id FROM ai_weight_profiles WHERE fingerprint=? ORDER BY id DESC LIMIT 1",
            lookup_params=(fingerprint,),
        )
        metrics = {
            "candidate_generator_version": CANDIDATE_GENERATOR_VERSION,
            "schema_version": AI_LAB_SCHEMA_VERSION,
            "validation_status": "pending_backtest",
            "baseline_metrics": baseline,
            "weight_deltas": deltas,
            "max_abs_delta": max((abs(float(item["delta"])) for item in deltas), default=0.0),
            "weights_sum": round(sum(weights.values()), 6),
            "operating_engine_changed": False,
        }
        cur = c.execute(
            "INSERT INTO ai_engine_versions(version_name,engine_code_version,profile_id,status,parent_version_id,metrics_json,notes,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                f"{stable.get('engine_code_version') or 'Engine'} Candidate J{job_id}-{number}",
                str(stable.get("engine_code_version") or ""),
                profile_id,
                "candidate",
                int(stable["id"]),
                _json(metrics),
                "RC6-D1 3단계에서 생성됨. 백테스트 전이며 운영 적용 금지.",
                int(created_by or job.get("created_by") or 0),
                _now(),
            ),
        )
        version_id = _inserted_id(
            c,
            cur,
            "ai_engine_versions",
            lookup_sql="SELECT id FROM ai_engine_versions WHERE profile_id=? AND status='candidate' ORDER BY id DESC LIMIT 1",
            lookup_params=(profile_id,),
        )
        created_profiles.append(profile_id)
        created_versions.append(version_id)
        fingerprints.add(fingerprint)
        candidate_rows.append(
            {
                "version_id": version_id,
                "profile_id": profile_id,
                "fingerprint": fingerprint,
                "weights": weights,
                "weight_deltas": deltas,
                "validation_status": "pending_backtest",
            }
        )

    if len(created_versions) < limit:
        raise RuntimeError(f"요청한 후보 {limit}개 중 {len(created_versions)}개만 생성되어 저장을 취소했습니다.")

    config = dict(job.get("config") or {})
    config.update(
        {
            "candidate_generator_version": CANDIDATE_GENERATOR_VERSION,
            "candidate_generation_enabled": True,
            "optimizer_enabled": False,
            "auto_apply": False,
            "operating_engine_unchanged": True,
        }
    )
    result.update(
        {
            "candidate_version_ids": created_versions,
            "candidate_profile_ids": created_profiles,
            "candidate_count": len(created_versions),
            "candidate_seed": seed,
            "candidate_generator_version": CANDIDATE_GENERATOR_VERSION,
            "candidate_validation": "static_pass_backtest_pending",
            "operating_engine_changed": False,
            "optimizer_executed": False,
        }
    )
    c.execute(
        "UPDATE ai_learning_jobs SET status='candidates_ready',config_json=?,result_json=?,best_candidate_version_id=0,updated_at=? WHERE id=?",
        (_json(config), _json(result), _now(), int(job_id)),
    )
    c.execute(
        "INSERT INTO ai_learning_notes(job_id,version_id,note_type,title,body,data_json,created_by,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            int(job_id),
            int(stable["id"]),
            "candidates_generated",
            "Candidate 가중치 생성 완료",
            f"Stable 가중치에서 안전 범위 내 후보 {len(created_versions)}개를 생성했습니다. 운영 엔진은 변경되지 않았습니다.",
            _json(
                {
                    "candidate_version_ids": created_versions,
                    "candidate_count": len(created_versions),
                    "seed": seed,
                    "generator_version": CANDIDATE_GENERATOR_VERSION,
                }
            ),
            int(created_by or job.get("created_by") or 0),
            _now(),
        ),
    )
    c.commit()
    return {
        "job": get_job(c, job_id),
        "items": candidate_rows,
        "candidate_version_ids": created_versions,
        "created_count": len(created_versions),
        "reused": False,
        "operating_engine_changed": False,
    }


def list_job_candidates(c: Any, job_id: int) -> List[Dict[str, Any]]:
    job = get_job(c, job_id)
    ids = [int(v) for v in ((job.get("result") or {}).get("candidate_version_ids") or []) if int(v or 0) > 0]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = c.execute(
        f"SELECT v.*,p.name AS profile_name,p.weights_json,p.fingerprint FROM ai_engine_versions v "
        f"JOIN ai_weight_profiles p ON p.id=v.profile_id WHERE v.id IN ({placeholders}) ORDER BY v.id",
        tuple(ids),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metrics"] = _loads(item.pop("metrics_json", "{}"), {})
        item["weights"] = _loads(item.pop("weights_json", "{}"), {})
        out.append(item)
    return out
