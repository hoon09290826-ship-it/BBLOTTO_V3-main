from .ai.ai_lab_activation import load_stable_profile as ai_lab_load_stable_profile
from .ai.backtest_engine import (
    BACKTEST_VERSION,
    cancel_run as rc6_cancel_run,
    create_run as rc6_create_run,
    ensure_backtest_tables,
    get_results as rc6_get_results,
    get_run as rc6_get_run,
    get_summary as rc6_get_summary,
    list_runs as rc6_list_runs,
    process_step as rc6_process_step,
)


class BacktestStartReq(BaseModel):
    combo_count: int = 10
    mode: str = 'balanced'
    min_history: int = 1


def _try_work_lock(c, namespace: int, work_id: int) -> bool:
    """Prevent two Railway workers/tabs from processing the same job."""
    if DB_ENGINE != 'postgresql':
        return True
    row = c.execute(
        'SELECT pg_try_advisory_lock(?,?) AS locked',
        (int(namespace), int(work_id)),
    ).fetchone()
    try:
        return bool(row['locked'])
    except Exception:
        return bool(row[0]) if row else False


def _release_work_lock(c, namespace: int, work_id: int) -> None:
    if DB_ENGINE == 'postgresql':
        c.execute('SELECT pg_advisory_unlock(?,?)', (int(namespace), int(work_id)))


@router.post('/api/backtest/runs')
def backtest_start(req: BacktestStartReq, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            run = rc6_create_run(c, created_by=int(admin['id']), combo_count=req.combo_count, mode=req.mode, min_history=req.min_history)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log_action(admin, 'BACKTEST_START', f"전체 회차 백테스트 #{run['id']} 시작", request)
    return {'ok': True, 'backtest_version': BACKTEST_VERSION, 'run': run}


@router.post('/api/backtest/runs/{run_id}/step')
def backtest_step(run_id: int, step_size: int = 2, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            if not _try_work_lock(c, 7501, run_id):
                return {'ok': True, 'busy': True, 'done': False, 'run': rc6_get_run(c, run_id), 'message': '같은 백테스트 작업이 이미 처리 중입니다.'}
            try:
                stable = ai_lab_load_stable_profile(c) or {}
                profile_label = (
                    f"stable:{int(stable.get('version_id') or 0)}:"
                    f"{stable.get('profile_name') or 'legacy'}"
                )
                result = rc6_process_step(
                    c,
                    run_id,
                    step_size=step_size,
                    weight_profile=(stable.get('weights') or None),
                    profile_label=profile_label,
                )
                result['stable_profile'] = {
                    'version_id': int(stable.get('version_id') or 0),
                    'version_name': stable.get('version_name') or '',
                    'profile_id': int(stable.get('profile_id') or 0),
                    'profile_name': stable.get('profile_name') or '',
                    'applied': bool(stable.get('weights')),
                }
            finally:
                _release_work_lock(c, 7501, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'backtest_version': BACKTEST_VERSION, **result}


@router.post('/api/backtest/runs/{run_id}/cancel')
def backtest_cancel(run_id: int, request: Request, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            run = rc6_cancel_run(c, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    log_action(admin, 'BACKTEST_CANCEL', f"전체 회차 백테스트 #{run_id} 중단", request)
    return {'ok': True, 'run': run}


@router.get('/api/backtest/runs')
def backtest_runs(limit: int = 20, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        rows = rc6_list_runs(c, limit=limit)
    return {'ok': True, 'backtest_version': BACKTEST_VERSION, 'items': rows}


@router.get('/api/backtest/runs/{run_id}')
def backtest_run(run_id: int, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            run = rc6_get_run(c, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    total = max(1, int(run.get('total_rounds') or 0))
    run['progress_percent'] = round(int(run.get('processed_rounds') or 0) * 100 / total, 2)
    return {'ok': True, 'run': run}


@router.get('/api/backtest/runs/{run_id}/summary')
def backtest_summary(run_id: int, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            data = rc6_get_summary(c, run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'backtest_version': BACKTEST_VERSION, **data}


@router.get('/api/backtest/runs/{run_id}/results')
def backtest_results(run_id: int, page: int = 1, page_size: int = 30, authorization: str | None = Header(default=None)):
    admin = require_admin(authorization)
    require_super_admin(admin)
    try:
        with con() as c:
            data = rc6_get_results(c, run_id, page=page, page_size=page_size)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, **data}


# Ensure schema exists during normal application initialization as well.
try:
    with con() as _rc6_conn:
        ensure_backtest_tables(_rc6_conn)
        _rc6_conn.commit()
except Exception:
    logger.exception('RC6-A backtest schema initialization failed')
