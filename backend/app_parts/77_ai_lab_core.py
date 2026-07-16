from .ai.ai_lab_core import (
    AI_LAB_SCHEMA_VERSION,
    bootstrap as ai_lab_bootstrap,
    create_learning_job as ai_lab_create_job,
    create_profile as ai_lab_create_profile,
    ensure_ai_lab_tables,
    get_job as ai_lab_get_job,
    get_overview as ai_lab_get_overview,
    recover_orphaned_jobs as ai_lab_recover_orphans,
    list_jobs as ai_lab_list_jobs,
    list_notes as ai_lab_list_notes,
    list_profiles as ai_lab_list_profiles,
    list_versions as ai_lab_list_versions,
)
from .ai.ai_lab_candidates import (
    CANDIDATE_GENERATOR_VERSION,
    generate_candidates as ai_lab_generate_candidates,
    list_job_candidates as ai_lab_list_job_candidates,
)
from .ai.ai_lab_compare import (
    COMPARE_VERSION,
    get_rankings as ai_lab_get_rankings,
    process_compare_step as ai_lab_process_compare_step,
)
from .ai.ai_lab_runner import (
    RUNNER_VERSION,
    cancel_job_with_run as ai_lab_cancel_job,
    pause_job as ai_lab_pause_job,
    process_job_step as ai_lab_process_job_step,
    resume_job as ai_lab_resume_job,
)
from .recommendation_engine import ENGINE_VERSION

from .ai.ai_lab_activation import (
    ACTIVATION_VERSION,
    approve_best_candidate as ai_lab_approve_best_candidate,
    ensure_activation_tables,
    list_activations as ai_lab_list_activations,
    load_stable_profile as ai_lab_load_stable_profile,
    rollback_stable as ai_lab_rollback_stable,
)




def _ai_lab_latest_admin_backtest(c):
    try:
        row=c.execute("SELECT * FROM backtest_runs WHERE status='completed' ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return {}
        run=dict(row)
        try:
            summary=rc6_get_summary(c, int(run['id']))
        except Exception:
            summary={}
        return {'run':run,'summary':summary.get('summary',{}),'by_window':summary.get('by_window',{}),'backtest_version':summary.get('backtest_version',run.get('backtest_version',''))}
    except Exception:
        return {}

@router.get('/api/ai-lab/backtest-link')
def ai_lab_backtest_link(authorization: str | None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        item=_ai_lab_latest_admin_backtest(c)
    return {'ok':True,'linked':bool(item),'item':item}

class AiLabProfileReq(BaseModel):
    name: str
    description: str = ''
    weights: dict


class AiLabJobReq(BaseModel):
    range_type: str = 'recent300'
    candidate_limit: int = 12
    random_seed: int = 0


class AiLabApproveReq(BaseModel):
    job_id: int
    version_id: int
    reason: str = '관리자 승인'


class AiLabRollbackReq(BaseModel):
    target_version_id: int
    reason: str = '관리자 롤백'


@router.get('/api/ai-lab/overview')
def ai_lab_overview(authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    recovered = []
    try:
        with con() as c:
            ai_lab_bootstrap(c, engine_code_version=ENGINE_VERSION, created_by=int(admin['id']))
            recovered = ai_lab_recover_orphans(c, created_by=int(admin['id']))
            data = ai_lab_get_overview(c)
    except Exception as exc:
        logger.exception('AI LAB overview failed')
        # Keep the management screen usable even when legacy AI LAB rows are malformed.
        return {
            'ok': True, 'degraded': True, 'warning': str(exc), 'stable': {},
            'active_job': {}, 'counts': {'versions': 0, 'profiles': 0, 'jobs': 0, 'notes': 0},
            'recovered_job_ids': recovered,
        }
    return {'ok': True, **data, 'recovered_job_ids': recovered}


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
            linked_backtest = _ai_lab_latest_admin_backtest(c)
            if linked_backtest:
                current_result = item.get('result') if isinstance(item, dict) else {}
                if not isinstance(current_result, dict): current_result={}
                current_result['admin_backtest_link']={
                    'run_id':int(linked_backtest.get('run',{}).get('id') or 0),
                    'completed_at':linked_backtest.get('run',{}).get('completed_at') or '',
                    'engine_version':linked_backtest.get('run',{}).get('engine_version') or '',
                    'backtest_version':linked_backtest.get('backtest_version') or '',
                    'summary':linked_backtest.get('summary') or {}
                }
                c.execute('UPDATE ai_learning_jobs SET result_json=?,updated_at=? WHERE id=?',(json.dumps(current_result,ensure_ascii=False),now(),int(item['id'])))
                c.commit()
                item=ai_lab_get_job(c,int(item['id']))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log_action(admin, 'AI_LAB_JOB_CREATE', f"AI LAB 학습 작업 #{item['id']} 생성", request)
    return {'ok': True, 'item': item, 'message': 'Stable 기준 성능 측정 작업이 준비되었습니다. 운영 엔진은 변경되지 않습니다.'}


@router.get('/api/ai-lab/jobs')
def ai_lab_jobs(limit: int = 50, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        recovered = ai_lab_recover_orphans(c, created_by=int(admin['id']))
        return {'ok': True, 'items': ai_lab_list_jobs(c, limit=limit), 'recovered_job_ids': recovered}


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


@router.post('/api/ai-lab/jobs/{job_id}/generate-candidates')
def ai_lab_job_generate_candidates(job_id: int, request: Request, force: bool = False, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            result = ai_lab_generate_candidates(c, job_id, created_by=int(admin['id']), force=bool(force))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception('AI LAB candidate generation failed: job_id=%s', job_id)
        raise HTTPException(500, f'Candidate 가중치 생성 중 오류가 발생했습니다: {exc}')
    log_action(admin, 'AI_LAB_CANDIDATES_GENERATE', f"AI LAB 작업 #{job_id} Candidate {result.get('created_count', 0)}개 생성", request)
    return {'ok': True, 'generator_version': CANDIDATE_GENERATOR_VERSION, **result}


@router.get('/api/ai-lab/jobs/{job_id}/candidates')
def ai_lab_job_candidates(job_id: int, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            items = ai_lab_list_job_candidates(c, job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'items': items, 'count': len(items), 'operating_engine_changed': False}



@router.post('/api/ai-lab/jobs/{job_id}/compare-step')
def ai_lab_job_compare_step(job_id: int, step_size: int = 2, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            result = ai_lab_process_compare_step(c, job_id, step_size=step_size, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception('AI LAB candidate compare failed: job_id=%s', job_id)
        raise HTTPException(500, f'Candidate 비교 중 오류가 발생했습니다: {exc}')
    return {'ok': True, 'compare_version': COMPARE_VERSION, **result}


@router.get('/api/ai-lab/jobs/{job_id}/rankings')
def ai_lab_job_rankings(job_id: int, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            items = ai_lab_get_rankings(c, job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'items': items, 'count': len(items), 'operating_engine_changed': False}



@router.get('/api/ai-lab/stable')
def ai_lab_stable(authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        item = ai_lab_load_stable_profile(c)
    return {'ok': True, 'item': item, 'activation_version': ACTIVATION_VERSION}


@router.post('/api/ai-lab/approve')
def ai_lab_approve(req: AiLabApproveReq, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            result = ai_lab_approve_best_candidate(c, req.job_id, req.version_id, reason=req.reason, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception('AI LAB stable approval failed: job_id=%s version_id=%s', req.job_id, req.version_id)
        raise HTTPException(500, f'Stable 승인 중 오류가 발생했습니다: {exc}')
    log_action(admin, 'AI_LAB_STABLE_APPROVE', f"AI LAB Candidate #{req.version_id} Stable 승인", request)
    return {'ok': True, 'activation_version': ACTIVATION_VERSION, **result}


@router.post('/api/ai-lab/rollback')
def ai_lab_rollback(req: AiLabRollbackReq, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            result = ai_lab_rollback_stable(c, req.target_version_id, reason=req.reason, created_by=int(admin['id']))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception('AI LAB stable rollback failed: target=%s', req.target_version_id)
        raise HTTPException(500, f'Stable 롤백 중 오류가 발생했습니다: {exc}')
    log_action(admin, 'AI_LAB_STABLE_ROLLBACK', f"AI LAB Stable #{req.target_version_id} 롤백", request)
    return {'ok': True, 'activation_version': ACTIVATION_VERSION, **result}


@router.get('/api/ai-lab/activations')
def ai_lab_activations(limit: int = 100, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        items = ai_lab_list_activations(c, limit=limit)
    return {'ok': True, 'items': items, 'count': len(items)}

@router.get('/api/ai-lab/notes')
def ai_lab_notes(job_id: int = 0, limit: int = 100, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        return {'ok': True, 'items': ai_lab_list_notes(c, job_id=job_id, limit=limit)}


try:
    with con() as _ai_lab_conn:
        ai_lab_bootstrap(_ai_lab_conn, engine_code_version=ENGINE_VERSION, created_by=0)
        ensure_activation_tables(_ai_lab_conn)
        _ai_lab_conn.commit()
except Exception:
    logger.exception('RC6-D1 AI LAB schema initialization failed')
