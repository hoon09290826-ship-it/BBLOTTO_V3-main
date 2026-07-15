from .ai.ai_lab_core import (
    AI_LAB_SCHEMA_VERSION,
    bootstrap as ai_lab_bootstrap,
    create_learning_job as ai_lab_create_job,
    create_profile as ai_lab_create_profile,
    ensure_ai_lab_tables,
    get_job as ai_lab_get_job,
    get_overview as ai_lab_get_overview,
    list_jobs as ai_lab_list_jobs,
    list_notes as ai_lab_list_notes,
    list_profiles as ai_lab_list_profiles,
    list_versions as ai_lab_list_versions,
)
from .ai.ai_lab_runner import (
    RUNNER_VERSION,
    cancel_job_with_run as ai_lab_cancel_job,
    pause_job as ai_lab_pause_job,
    process_job_step as ai_lab_process_job_step,
    resume_job as ai_lab_resume_job,
)
from .recommendation_engine import ENGINE_VERSION


class AiLabProfileReq(BaseModel):
    name: str
    description: str = ''
    weights: dict


class AiLabJobReq(BaseModel):
    range_type: str = 'recent300'
    candidate_limit: int = 12
    random_seed: int = 0


@router.get('/api/ai-lab/overview')
def ai_lab_overview(authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        ai_lab_bootstrap(c, engine_code_version=ENGINE_VERSION, created_by=int(admin['id']))
        data = ai_lab_get_overview(c)
    return {'ok': True, **data}


@router.get('/api/ai-lab/profiles')
def ai_lab_profiles(limit: int = 100, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        return {'ok': True, 'items': ai_lab_list_profiles(c, limit=limit)}


@router.post('/api/ai-lab/profiles')
def ai_lab_profile_create(req: AiLabProfileReq, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            item = ai_lab_create_profile(c, name=req.name, description=req.description, weights=req.weights, created_by=int(admin['id']))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log_action(admin, 'AI_LAB_PROFILE_CREATE', f"AI LAB 가중치 프로필 생성: {item['name']}", request)
    return {'ok': True, 'item': item}


@router.get('/api/ai-lab/versions')
def ai_lab_versions(status: str = '', limit: int = 100, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        return {'ok': True, 'items': ai_lab_list_versions(c, status=status, limit=limit)}


@router.post('/api/ai-lab/jobs')
def ai_lab_job_create(req: AiLabJobReq, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            ai_lab_bootstrap(c, engine_code_version=ENGINE_VERSION, created_by=int(admin['id']))
            item = ai_lab_create_job(c, range_type=req.range_type, candidate_limit=req.candidate_limit, random_seed=req.random_seed, created_by=int(admin['id']))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log_action(admin, 'AI_LAB_JOB_CREATE', f"AI LAB 학습 작업 #{item['id']} 생성", request)
    return {'ok': True, 'item': item, 'message': 'Stable 기준 성능 측정 작업이 준비되었습니다. 운영 엔진은 변경되지 않습니다.'}


@router.get('/api/ai-lab/jobs')
def ai_lab_jobs(limit: int = 50, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        return {'ok': True, 'items': ai_lab_list_jobs(c, limit=limit)}


@router.get('/api/ai-lab/jobs/{job_id}')
def ai_lab_job(job_id: int, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            item = ai_lab_get_job(c, job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'item': item}


@router.post('/api/ai-lab/jobs/{job_id}/step')
def ai_lab_job_step(job_id: int, step_size: int = 2, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            result = ai_lab_process_job_step(c, job_id, step_size=step_size, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception('AI LAB baseline step failed: job_id=%s', job_id)
        raise HTTPException(500, f'Stable 기준 성능 측정 중 오류가 발생했습니다: {exc}')
    return {'ok': True, 'runner_version': RUNNER_VERSION, **result}


@router.post('/api/ai-lab/jobs/{job_id}/pause')
def ai_lab_job_pause(job_id: int, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            item = ai_lab_pause_job(c, job_id, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    log_action(admin, 'AI_LAB_JOB_PAUSE', f"AI LAB 학습 작업 #{job_id} 일시정지", request)
    return {'ok': True, 'item': item}


@router.post('/api/ai-lab/jobs/{job_id}/resume')
def ai_lab_job_resume(job_id: int, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            item = ai_lab_resume_job(c, job_id, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    log_action(admin, 'AI_LAB_JOB_RESUME', f"AI LAB 학습 작업 #{job_id} 재개", request)
    return {'ok': True, 'item': item}


@router.post('/api/ai-lab/jobs/{job_id}/cancel')
def ai_lab_job_cancel(job_id: int, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            item = ai_lab_cancel_job(c, job_id, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    log_action(admin, 'AI_LAB_JOB_CANCEL', f"AI LAB 학습 작업 #{job_id} 중단", request)
    return {'ok': True, 'item': item}


@router.get('/api/ai-lab/notes')
def ai_lab_notes(job_id: int = 0, limit: int = 100, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        return {'ok': True, 'items': ai_lab_list_notes(c, job_id=job_id, limit=limit)}


try:
    with con() as _ai_lab_conn:
        ai_lab_bootstrap(_ai_lab_conn, engine_code_version=ENGINE_VERSION, created_by=0)
except Exception:
    logger.exception('RC6-D1 AI LAB schema initialization failed')
