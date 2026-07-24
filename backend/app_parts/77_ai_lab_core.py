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

_AI_LAB_BACKGROUND_WAKE = threading.Event()
_AI_LAB_BACKGROUND_STOP = threading.Event()
_AI_LAB_BACKGROUND_THREAD = None
_AI_LAB_BACKGROUND_GUARD = threading.Lock()


def _ai_lab_background_config(c, job_id: int, phase: str = '', stop_reason: str = ''):
    row = c.execute(
        'SELECT config_json FROM ai_learning_jobs WHERE id=?',
        (int(job_id),),
    ).fetchone()
    if not row:
        raise KeyError('학습 작업을 찾을 수 없습니다.')
    try:
        config = json.loads(row['config_json'] or '{}')
    except Exception:
        config = {}
    config['background_phase'] = str(phase or '')
    config['background_enabled'] = bool(phase)
    if phase:
        config['last_background_phase'] = str(phase)
    config['background_stop_reason'] = '' if phase else str(stop_reason or '')
    config['background_updated_at'] = now()
    c.execute(
        'UPDATE ai_learning_jobs SET config_json=?,updated_at=? WHERE id=?',
        (json.dumps(config, ensure_ascii=False), now(), int(job_id)),
    )
    c.commit()
    return config


def _ai_lab_background_job(c):
    rows = c.execute(
        "SELECT id,status,created_by,config_json FROM ai_learning_jobs "
        "WHERE status IN ('ready','running','candidates_ready','candidates_testing') "
        "ORDER BY id"
    ).fetchall()
    for row in rows:
        try:
            config = json.loads(row['config_json'] or '{}')
        except Exception:
            config = {}
        phase = str(config.get('background_phase') or '')
        if phase in {'baseline', 'compare'}:
            return {
                'id': int(row['id']),
                'status': str(row['status'] or ''),
                'created_by': int(row['created_by'] or 0),
                'phase': phase,
            }
    return None


def _ai_lab_background_loop():
    while not _AI_LAB_BACKGROUND_STOP.is_set():
        work = None
        try:
            with con() as c:
                work = _ai_lab_background_job(c)
            if not work:
                _AI_LAB_BACKGROUND_WAKE.wait(2.0)
                _AI_LAB_BACKGROUND_WAKE.clear()
                continue
            namespace = 7701 if work['phase'] == 'baseline' else 7702
            with con() as c:
                if not _try_work_lock(c, namespace, work['id']):
                    _AI_LAB_BACKGROUND_WAKE.wait(.35)
                    _AI_LAB_BACKGROUND_WAKE.clear()
                    continue
                try:
                    if work['phase'] == 'baseline':
                        result = ai_lab_process_job_step(
                            c,
                            work['id'],
                            step_size=25,
                            created_by=work['created_by'],
                        )
                    else:
                        result = ai_lab_process_compare_step(
                            c,
                            work['id'],
                            step_size=25,
                            created_by=work['created_by'],
                        )
                    fresh = ai_lab_get_job(c, work['id'])
                    fresh_config = fresh.get('config') or {}
                    if (
                        not fresh_config.get('background_enabled')
                        and not result.get('done')
                    ):
                        stop_reason = str(
                            fresh_config.get('background_stop_reason') or 'pause'
                        )
                        if stop_reason == 'cancel':
                            ai_lab_cancel_job(
                                c,
                                work['id'],
                                created_by=work['created_by'],
                            )
                        else:
                            ai_lab_pause_job(
                                c,
                                work['id'],
                                created_by=work['created_by'],
                            )
                    if result.get('done') or result.get('paused'):
                        _ai_lab_background_config(c, work['id'], '')
                finally:
                    _release_work_lock(c, namespace, work['id'])
        except Exception as exc:
            logger.exception('AI LAB background worker failed: work=%s', work)
            if work:
                try:
                    with con() as c:
                        _ai_lab_background_config(c, work['id'], '')
                        c.execute(
                            "UPDATE ai_learning_jobs SET status='failed',error_message=?,"
                            "completed_at=?,updated_at=? WHERE id=?",
                            (f'{exc.__class__.__name__}: {exc}'[:1000], now(), now(), work['id']),
                        )
                        c.commit()
                except Exception:
                    logger.exception('AI LAB background failure state save failed')
        _AI_LAB_BACKGROUND_WAKE.wait(.05)
        _AI_LAB_BACKGROUND_WAKE.clear()


def _ensure_ai_lab_background_worker():
    global _AI_LAB_BACKGROUND_THREAD
    with _AI_LAB_BACKGROUND_GUARD:
        if _AI_LAB_BACKGROUND_THREAD and _AI_LAB_BACKGROUND_THREAD.is_alive():
            return
        _AI_LAB_BACKGROUND_THREAD = threading.Thread(
            target=_ai_lab_background_loop,
            name='bblotto-ai-lab-worker',
            daemon=True,
        )
        _AI_LAB_BACKGROUND_THREAD.start()




def _ai_lab_latest_admin_backtest(c):
    """Return the newest usable admin backtest, including in-progress runs.

    AI LAB previously linked only ``completed`` runs, so a newly started or
    partially processed backtest appeared disconnected until every round had
    finished.  Keep failed/cancelled runs out, but expose ready/running and
    completed runs together with progress and the currently available summary.
    """
    try:
        row = c.execute(
            "SELECT * FROM backtest_runs "
            "WHERE status NOT IN ('failed','cancelled') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {}

        run = dict(row)
        processed = int(run.get('processed_rounds') or 0)
        total = int(run.get('total_rounds') or 0)
        progress = round((processed / total) * 100, 2) if total > 0 else 0.0

        try:
            summary_data = rc6_get_summary(c, int(run['id'])) or {}
        except Exception:
            logger.exception('AI LAB backtest intermediate summary failed: run_id=%s', run.get('id'))
            summary_data = {}

        return {
            'run': run,
            'status': str(run.get('status') or 'ready'),
            'is_completed': str(run.get('status') or '') == 'completed',
            'processed_rounds': processed,
            'total_rounds': total,
            'progress_percent': progress,
            'summary': summary_data.get('summary', {}),
            'by_window': summary_data.get('by_window', {}),
            'backtest_version': summary_data.get('backtest_version', run.get('backtest_version', '')),
        }
    except Exception:
        logger.exception('AI LAB backtest link lookup failed')
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
                current_result['admin_backtest_link'] = {
                    'run_id': int(linked_backtest.get('run', {}).get('id') or 0),
                    'status': linked_backtest.get('status') or 'ready',
                    'is_completed': bool(linked_backtest.get('is_completed')),
                    'processed_rounds': int(linked_backtest.get('processed_rounds') or 0),
                    'total_rounds': int(linked_backtest.get('total_rounds') or 0),
                    'progress_percent': float(linked_backtest.get('progress_percent') or 0),
                    'started_at': linked_backtest.get('run', {}).get('started_at') or '',
                    'completed_at': linked_backtest.get('run', {}).get('completed_at') or '',
                    'engine_version': linked_backtest.get('run', {}).get('engine_version') or '',
                    'backtest_version': linked_backtest.get('backtest_version') or '',
                    'summary': linked_backtest.get('summary') or {},
                    'by_window': linked_backtest.get('by_window') or {},
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


@router.post('/api/ai-lab/jobs/{job_id}/background-start')
def ai_lab_job_background_start(job_id: int, phase: str = 'baseline', authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    phase = str(phase or 'baseline').strip().lower()
    if phase not in {'baseline', 'compare'}:
        raise HTTPException(400, '백그라운드 단계는 baseline 또는 compare여야 합니다.')
    try:
        with con() as c:
            item = ai_lab_get_job(c, job_id)
            allowed = (
                {'ready', 'running'}
                if phase == 'baseline'
                else {'candidates_ready', 'candidates_testing'}
            )
            if str(item.get('status') or '') not in allowed:
                raise ValueError('현재 작업 상태에서는 해당 백그라운드 실행을 시작할 수 없습니다.')
            _ai_lab_background_config(c, job_id, phase)
            item = ai_lab_get_job(c, job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _ensure_ai_lab_background_worker()
    _AI_LAB_BACKGROUND_WAKE.set()
    return {
        'ok': True,
        'background': True,
        'phase': phase,
        'item': item,
        'message': '브라우저를 닫아도 서버에서 계속 처리합니다.',
    }


@router.post('/api/ai-lab/jobs/{job_id}/step')
def ai_lab_job_step(job_id: int, step_size: int = 2, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            if not _try_work_lock(c, 7701, job_id):
                return {'ok': True, 'busy': True, 'done': False, 'job': ai_lab_get_job(c, job_id), 'message': '같은 AI LAB 기준 측정이 이미 처리 중입니다.'}
            try:
                result = ai_lab_process_job_step(c, job_id, step_size=step_size, created_by=int(admin['id']))
            finally:
                _release_work_lock(c, 7701, job_id)
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
            _ai_lab_background_config(c, job_id, '', 'pause')
            item = ai_lab_pause_job(c, job_id, created_by=int(admin['id']))
            item = ai_lab_get_job(c, job_id)
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
            previous_phase = str((item.get('config') or {}).get('last_background_phase') or 'baseline')
            phase = 'compare' if item.get('status') == 'candidates_testing' else previous_phase
            _ai_lab_background_config(c, job_id, phase)
            item = ai_lab_get_job(c, job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    log_action(admin, 'AI_LAB_JOB_RESUME', f"AI LAB 학습 작업 #{job_id} 재개", request)
    _ensure_ai_lab_background_worker()
    _AI_LAB_BACKGROUND_WAKE.set()
    return {'ok': True, 'item': item}


@router.post('/api/ai-lab/jobs/{job_id}/cancel')
def ai_lab_job_cancel(job_id: int, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            _ai_lab_background_config(c, job_id, '', 'cancel')
            item = ai_lab_cancel_job(c, job_id, created_by=int(admin['id']))
            item = ai_lab_get_job(c, job_id)
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
            if not _try_work_lock(c, 7702, job_id):
                return {'ok': True, 'busy': True, 'done': False, 'job': ai_lab_get_job(c, job_id), 'message': '같은 Candidate 비교 작업이 이미 처리 중입니다.'}
            try:
                result = ai_lab_process_compare_step(c, job_id, step_size=step_size, created_by=int(admin['id']))
            finally:
                _release_work_lock(c, 7702, job_id)
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
    _ensure_ai_lab_background_worker()
except Exception:
    logger.exception('RC6-D1 AI LAB schema initialization failed')
