# Extracted from legacy backend/app.py lines 4850-5411.
@router.get('/api/engine/insights')
def engine_insights(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    ensure_sprint23_schema()
    st=latest_stats(120)
    profile=_s23_weighted_number_profile(st, 'balanced')
    top_weighted=sorted(profile.keys(), key=lambda n:(-profile[n], n))[:12]
    with con() as c:
        recent_runs=c.execute('SELECT * FROM engine_runs ORDER BY id DESC LIMIT 20').fetchall()
        rec_rows=c.execute('SELECT avg_score,engine_json,created_at FROM recommendations ORDER BY id DESC LIMIT 30').fetchall()
    scores=[]
    for r in rec_rows:
        try:
            if r['avg_score']: scores.append(float(r['avg_score']))
            else:
                ej=json.loads(r['engine_json'] or '{}'); scores.append(float(ej.get('avg_score') or 0))
        except Exception: pass
    return {
        'engine_version':SPRINT23_ENGINE_VERSION,
        'latest_round':st.get('latest_round'),
        'hot':st.get('hot',[])[:12],
        'cold':st.get('cold',[])[:12],
        'overdue':st.get('overdue',[])[:12],
        'top_weighted':top_weighted,
        'avg_recent_score':round(sum(scores)/len(scores),1) if scores else 0,
        'runs':[dict(r) for r in recent_runs],
        'summary':'최근 100회 통계와 추천 생성 이력을 기준으로 엔진 상태를 표시합니다.'
    }

@router.get('/api/dashboard_v2')
def dashboard_v2(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    ensure_sprint23_schema()
    base=dashboard_summary(authorization)
    with con() as c:
        today=now()[:10]
        today_recs=c.execute('SELECT COUNT(*) c FROM recommendations WHERE created_at LIKE ?', (today+'%',)).fetchone()['c']
        today_sms=c.execute('SELECT COUNT(*) c FROM sms_logs WHERE created_at LIKE ?', (today+'%',)).fetchone()['c']
        avg=c.execute('SELECT COALESCE(AVG(avg_score),0) a, COALESCE(MAX(avg_score),0) m FROM recommendations WHERE avg_score IS NOT NULL').fetchone()
        recent_runs=c.execute('SELECT * FROM engine_runs ORDER BY id DESC LIMIT 5').fetchall()
    base.update({
        'engine_version':SPRINT23_ENGINE_VERSION,
        'today_recommendations':today_recs,
        'today_sms':today_sms,
        'avg_ai_score':round(float(avg['a'] or 0),1),
        'max_ai_score':round(float(avg['m'] or 0),1),
        'recent_engine_runs':[dict(r) for r in recent_runs]
    })
    return base

# generate 라우트가 만든 recommendations 저장 직후 engine_runs에도 보조 기록되도록 DB insert를 후킹하지 않고,
# 추천 상세 조회 시 누락된 실행 이력을 보강하는 안전 API를 제공합니다.
@router.post('/api/engine/backfill_runs')
def backfill_engine_runs(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    ensure_sprint23_schema()
    inserted=0
    with con() as c:
        rows=c.execute('SELECT id,member_id,round_no,mode,count,avg_score,engine_json,created_by,created_at FROM recommendations ORDER BY id DESC LIMIT 300').fetchall()
        for r in rows:
            exists=c.execute('SELECT id FROM engine_runs WHERE recommendation_id=?',(r['id'],)).fetchone()
            if exists: continue
            try: ej=json.loads(r['engine_json'] or '{}')
            except Exception: ej={}
            c.execute('INSERT INTO engine_runs(recommendation_id,round_no,member_id,mode,count,candidate_count,selected_count,avg_score,max_score,min_score,engine_version,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                r['id'],r['round_no'] or 0,r['member_id'] or 0,r['mode'] or 'balanced',r['count'] or 0,ej.get('candidate_count') or 0,ej.get('selected_count') or r['count'] or 0,r['avg_score'] or ej.get('avg_score') or 0,ej.get('max_score') or 0,ej.get('min_score') or 0,ej.get('engine_version') or ej.get('version') or SPRINT23_ENGINE_VERSION,r['created_by'] or admin['id'],r['created_at'] or now()))
            inserted+=1
        c.commit()
    return {'ok':True,'inserted':inserted}




# ===== RC4-4: Admin / Stats / AI / Members / Auto Update =====
RC4_4_VERSION = 'V2_STABLE_RC4_4_ADMIN_DASHBOARD'

def _rc44_safe_count(c, sql, params=()):
    try:
        r = c.execute(sql, params).fetchone()
        return int((r['c'] if r and 'c' in r.keys() else r[0]) or 0)
    except Exception:
        return 0

def _rc44_rows(c, sql, params=(), limit=20):
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()[:limit]]
    except Exception:
        return []

def _rc44_today_like():
    return datetime.datetime.now().strftime('%Y-%m-%d') + '%'

@router.get('/api/rc4-4/admin-dashboard')
def rc44_admin_dashboard(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    today = _rc44_today_like()
    with con() as c:
        scope_sql, scope_args = member_scope_condition(admin, 'm')
        mem_where = (' WHERE ' + scope_sql.replace('m.', '')) if scope_sql else ''
        rec_join = ' LEFT JOIN members m ON m.id=r.member_id'
        rec_scope = (' AND ' + scope_sql) if scope_sql else ''
        rec_scope_where = (' WHERE ' + scope_sql) if scope_sql else ''
        total_members = _rc44_safe_count(c, 'SELECT COUNT(*) c FROM members' + mem_where, scope_args)
        active_members = _rc44_safe_count(c, "SELECT COUNT(*) c FROM members" + (mem_where + " AND " if mem_where else " WHERE ") + "COALESCE(status,'활성')='활성'", scope_args)
        vip_members = _rc44_safe_count(c, "SELECT COUNT(*) c FROM members" + (mem_where + " AND " if mem_where else " WHERE ") + "COALESCE(grade,'일반') IN ('1등','2등','VIP','다이아','프리미엄')", scope_args)
        priority_members = _rc44_safe_count(c, "SELECT COUNT(*) c FROM members" + (mem_where + " AND " if mem_where else " WHERE ") + "COALESCE(priority,'보통') IN ('높음','최우선')", scope_args)
        rec_total = _rc44_safe_count(c, 'SELECT COUNT(*) c FROM recommendations r' + rec_join + rec_scope_where, scope_args)
        rec_today = _rc44_safe_count(c, 'SELECT COUNT(*) c FROM recommendations r' + rec_join + ' WHERE r.created_at LIKE ?' + rec_scope, (today, *scope_args))
        sms_today = _rc44_safe_count(c, 'SELECT COUNT(*) c FROM sms_logs WHERE created_at LIKE ?', (today,))
        wins_today = _rc44_safe_count(c, "SELECT COUNT(*) c FROM winning_checks WHERE created_at LIKE ? AND COALESCE(rank,'낙첨')<>'낙첨'", (today,))
        login_today = _rc44_safe_count(c, "SELECT COUNT(*) c FROM admin_logs WHERE action IN ('LOGIN','LOGIN_SUCCESS') AND created_at LIKE ?", (today,))
        activity_today = _rc44_safe_count(c, 'SELECT COUNT(*) c FROM admin_logs WHERE created_at LIKE ?', (today,))
        latest_draw = c.execute('SELECT round_no,draw_date,numbers,bonus FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
        avg = c.execute('SELECT COALESCE(AVG(avg_score),0) a, COALESCE(MAX(avg_score),0) m FROM recommendations WHERE avg_score IS NOT NULL').fetchone()
        prize_row = c.execute('SELECT COALESCE(SUM(prize),0) prize, COUNT(*) c FROM winning_checks').fetchone()
        recent_members = _rc44_rows(c, 'SELECT id,name,phone,grade,status,priority,created_at FROM members' + mem_where + ' ORDER BY id DESC LIMIT 8', scope_args)
        recent_logs = _rc44_rows(c, 'SELECT username,action,detail,created_at FROM admin_logs ORDER BY id DESC LIMIT 10')
        recent_recs = _rc44_rows(c, 'SELECT r.id,r.member_id,r.member_name,r.round_no,r.mode,r.count,r.avg_score,r.created_at FROM recommendations r' + rec_join + rec_scope_where + ' ORDER BY r.id DESC LIMIT 10', scope_args)
        recent_wins = _rc44_rows(c, "SELECT w.member_name,w.round_no,w.rank,w.prize,w.created_at FROM winning_checks w LEFT JOIN members m ON m.id=w.member_id WHERE COALESCE(w.rank,'낙첨')<>'낙첨'" + rec_scope + ' ORDER BY w.id DESC LIMIT 8', scope_args)
    alerts=[]
    if not latest_draw:
        alerts.append({'type':'warning','message':'저장된 당첨번호가 없습니다. 자동 업데이트를 실행하세요.'})
    else:
        alerts.append({'type':'success','message':f"최근 저장 회차 {latest_draw['round_no']}회 기준으로 운영 중입니다."})
    if rec_today:
        alerts.append({'type':'info','message':f'오늘 추천번호 {rec_today}건 생성되었습니다.'})
    if wins_today:
        alerts.append({'type':'success','message':f'오늘 적중 결과 {wins_today}건이 확인되었습니다.'})
    return {
        'ok': True, 'version': RC4_4_VERSION,
        'kpi': {
            'total_members': total_members, 'active_members': active_members, 'vip_members': vip_members,
            'priority_members': priority_members, 'recommendations_total': rec_total, 'recommendations_today': rec_today,
            'sms_today': sms_today, 'wins_today': wins_today, 'login_today': login_today, 'activity_today': activity_today,
            'avg_ai_score': round(float(avg['a'] or 0),1) if avg else 0, 'max_ai_score': round(float(avg['m'] or 0),1) if avg else 0,
            'total_prize': int(prize_row['prize'] or 0) if prize_row else 0, 'checked_total': int(prize_row['c'] or 0) if prize_row else 0
        },
        'latest_draw': dict(latest_draw) if latest_draw else None,
        'recent_members': recent_members, 'recent_logs': recent_logs, 'recent_recommendations': recent_recs,
        'recent_wins': recent_wins, 'alerts': alerts
    }

@router.get('/api/rc4-4/ai-status')
def rc44_ai_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    today = _rc44_today_like()
    with con() as c:
        by_grade = _rc44_rows(c, """SELECT COALESCE(m.grade,'일반') grade, COUNT(r.id) c, COALESCE(AVG(r.avg_score),0) avg_score
                                     FROM recommendations r LEFT JOIN members m ON m.id=r.member_id
                                     GROUP BY COALESCE(m.grade,'일반') ORDER BY c DESC""", limit=20)
        by_mode = _rc44_rows(c, "SELECT COALESCE(mode,'balanced') mode, COUNT(*) c, COALESCE(AVG(avg_score),0) avg_score FROM recommendations GROUP BY COALESCE(mode,'balanced') ORDER BY c DESC", limit=20)
        today_rows = _rc44_rows(c, "SELECT id,member_name,round_no,mode,count,avg_score,created_at FROM recommendations WHERE created_at LIKE ? ORDER BY id DESC LIMIT 20", (today,), limit=20)
        recent_runs = _rc44_rows(c, 'SELECT recommendation_id,round_no,mode,count,avg_score,engine_version,created_at FROM engine_runs ORDER BY id DESC LIMIT 20', limit=20)
    return {'ok': True, 'version': RC4_4_VERSION, 'by_grade': by_grade, 'by_mode': by_mode, 'today': today_rows, 'recent_runs': recent_runs}

@router.get('/api/rc4-4/member-dashboard')
def rc44_member_dashboard(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        grade = _rc44_rows(c, "SELECT COALESCE(grade,'일반') label, COUNT(*) c FROM members GROUP BY COALESCE(grade,'일반') ORDER BY c DESC", limit=20)
        status = _rc44_rows(c, "SELECT COALESCE(status,'활성') label, COUNT(*) c FROM members GROUP BY COALESCE(status,'활성') ORDER BY c DESC", limit=20)
        priority = _rc44_rows(c, "SELECT COALESCE(priority,'보통') label, COUNT(*) c FROM members GROUP BY COALESCE(priority,'보통') ORDER BY c DESC", limit=20)
        top = _rc44_rows(c, """SELECT m.id,m.name,m.grade,m.status,m.priority,COUNT(r.id) rec_count,COALESCE(MAX(r.created_at),'') latest_recommendation
                              FROM members m LEFT JOIN recommendations r ON r.member_id=m.id
                              GROUP BY m.id,m.name,m.grade,m.status,m.priority
                              ORDER BY rec_count DESC, m.id DESC LIMIT 10""", limit=10)
    return {'ok': True, 'version': RC4_4_VERSION, 'grade': grade, 'status': status, 'priority': priority, 'top_members': top}

@router.post('/api/rc4-4/auto-update')
def rc44_auto_update(backfill:int=12, request:Request=None, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    result = {'ok': True, 'version': RC4_4_VERSION, 'steps': []}
    try:
        sync = _s3_sync_recent_draws(backfill)
        result['steps'].append({'name':'최신회차 동기화','ok':True,'data':sync})
    except Exception as e:
        result['steps'].append({'name':'최신회차 동기화','ok':False,'error':str(e)[:180]})
    try:
        st = latest_stats(100)
        result['steps'].append({'name':'최근 100회 통계 갱신','ok':True,'latest_round':st.get('latest_round'),'sample_size':len(st.get('draws',[]) or [])})
    except Exception as e:
        result['steps'].append({'name':'최근 100회 통계 갱신','ok':False,'error':str(e)[:180]})
    try:
        with con() as c:
            latest = c.execute('SELECT round_no FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
        if latest:
            auto = _auto_check_round(admin, AutoWinReq(round_no=int(latest['round_no'])), request)
            result['steps'].append({'name':'회원 적중 자동계산','ok':True,'data':auto})
        else:
            result['steps'].append({'name':'회원 적중 자동계산','ok':False,'error':'저장된 회차 없음'})
    except Exception as e:
        result['steps'].append({'name':'회원 적중 자동계산','ok':False,'error':str(e)[:180]})
    try:
        log_action(admin, 'RC4_4_AUTO_UPDATE', json.dumps(result, ensure_ascii=False), request)
    except Exception:
        _log_suppressed_exception("80_dashboards_operations.py:197")
    result['success_count'] = sum(1 for s in result['steps'] if s.get('ok'))
    result['failed_count'] = sum(1 for s in result['steps'] if not s.get('ok'))
    return result


# ===== RC2 Sprint 3: draw automation / 100-round stats / mobile status =====
SPRINT3_VERSION = 'RC2-Sprint3-DrawStats-Mobile'

def _s3_row_to_draw(r):
    if not r:
        return None
    return {
        'round_no': int(r['round_no']),
        'draw_date': r['draw_date'] or draw_date_for_round(int(r['round_no'])),
        'numbers': parse_nums(r['numbers']),
        'bonus': int(r['bonus'] or 0),
        'source': r['source'] if 'source' in r.keys() else 'db',
        'updated_at': r['updated_at'] if 'updated_at' in r.keys() else ''
    }

def _s3_save_draw(draw, replace=True):
    if not draw or len(parse_nums(draw.get('numbers'))) != 6:
        return None
    with con() as c:
        if replace:
            c.execute('INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)', (
                int(draw['round_no']), draw.get('draw_date') or draw_date_for_round(int(draw['round_no'])),
                json.dumps(sorted(parse_nums(draw.get('numbers'))), ensure_ascii=False), int(draw.get('bonus') or 0),
                draw.get('source') or 'official', now()
            ))
        else:
            c.execute('INSERT OR IGNORE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)', (
                int(draw['round_no']), draw.get('draw_date') or draw_date_for_round(int(draw['round_no'])),
                json.dumps(sorted(parse_nums(draw.get('numbers'))), ensure_ascii=False), int(draw.get('bonus') or 0),
                draw.get('source') or 'official', now()
            ))
        c.commit()
    return draw

def _s3_sync_recent_draws(backfill=12):
    expected = expected_lotto_round()
    start = max(1, expected - max(1, min(int(backfill or 12), 60)) + 1)
    inserted=[]; skipped=[]; failed=[]
    for round_no in range(start, expected + 1):
        status = draw_status_for_round(round_no)
        existing = get_draw(round_no)
        if existing and len(existing.get('numbers') or []) == 6:
            skipped.append(round_no); continue
        if status in ('future','scheduled'):
            skipped.append(round_no); continue
        fetched = fetch_official_lotto(round_no)
        if fetched:
            _s3_save_draw(fetched, replace=True); inserted.append(round_no)
        else:
            failed.append(round_no)
    latest = None
    with con() as c:
        latest = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
    return {
        'ok': True, 'version': SPRINT3_VERSION, 'expected_round': expected,
        'inserted_rounds': inserted, 'skipped_rounds': skipped, 'failed_rounds': failed,
        'latest_draw': _s3_row_to_draw(latest),
        'message': '동행복권 공개 데이터 기준으로 최근 회차 자동 동기화를 시도했습니다.'
    }

@router.post('/api/draws/sync')
def sprint3_sync_draws(backfill:int=12, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    result=_s3_sync_recent_draws(backfill)
    try: log_action(admin.get('username') or admin.get('name') or 'admin', 'DRAW_SYNC', json.dumps(result, ensure_ascii=False))
    except Exception: pass
    return result

@router.get('/api/draws/status_v2')
def sprint3_draw_status_v2(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    expected = expected_lotto_round()
    current = resolve_draw_for_check(expected, allow_fetch=True)
    previous = resolve_draw_for_check(max(1, expected-1), allow_fetch=True)
    with con() as c:
        total = c.execute('SELECT COUNT(*) c FROM draws').fetchone()['c']
        latest = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
    return {
        'version': SPRINT3_VERSION, 'expected_round': expected, 'total_draws': total,
        'current': current, 'previous': previous, 'latest_draw': _s3_row_to_draw(latest),
        'next_draw_date': draw_date_for_round(expected),
        'summary': '현재 관리 회차와 당첨번호 저장 상태를 자동으로 판정합니다.'
    }

@router.get('/api/stats/round100')
def sprint3_stats_round100(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    st = latest_stats(100)
    draws = st.get('draws', [])[:100]
    trend=[]
    for d in draws[:20]:
        nums=d.get('numbers') or []
        trend.append({
            'round_no': d.get('round_no'), 'draw_date': d.get('draw_date'), 'sum': sum(nums),
            'odd': sum(n%2 for n in nums), 'even': 6-sum(n%2 for n in nums),
            'low': sum(n<=22 for n in nums), 'high': sum(n>=23 for n in nums),
            'numbers': nums, 'bonus': d.get('bonus')
        })
    freq100=st.get('freq100') or {}
    return {
        'version': SPRINT3_VERSION, 'latest_round': st.get('latest_round'), 'sample_size': len(draws),
        'hot': st.get('hot', [])[:15], 'cold': st.get('cold', [])[:15], 'overdue': st.get('overdue', [])[:15],
        'top_pairs': st.get('top_pairs', [])[:15], 'zone_counts': st.get('zone_counts'), 'end_counts': st.get('end_counts'),
        'sum_avg': st.get('sum_avg'), 'odd_ratio': st.get('odd_ratio'),
        'frequency_top': sorted([{'number':int(n),'count':int(c)} for n,c in freq100.items()], key=lambda x:(-x['count'], x['number']))[:20],
        'recent_trend': trend,
        'summary': '최근 100회 기준 빈도/미출현/동반출현/구간/끝수/합계 흐름을 통합 계산했습니다.'
    }

@router.get('/api/mobile/status')
def sprint3_mobile_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        members=c.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        recs=c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c']
        latest=c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
    return {
        'version': SPRINT3_VERSION, 'ok': True, 'members': members, 'recommendations': recs,
        'latest_draw': _s3_row_to_draw(latest),
        'pwa': {'manifest': False, 'service_worker': False, 'mobile_layout': True},
        'summary': '모바일 접속용 핵심 상태 점검이 정상입니다.'
    }

# ===== RC2 Sprint 4: operations hardening / health / backup cleanup =====
SPRINT4_VERSION = 'RC2-Sprint4-OpsHardening'

def _s4_table_count(conn, table):
    try:
        return int(conn.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()['c'])
    except Exception:
        return 0

def _s4_latest_backup():
    latest = None
    try:
        with con() as c:
            latest = c.execute('SELECT * FROM backup_history ORDER BY id DESC LIMIT 1').fetchone()
            if latest:
                return dict(latest)
    except Exception:
        _log_suppressed_exception("80_dashboards_operations.py:343")
    try:
        files = sorted(EXPORT_DIR.glob('*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            f = files[0]
            return {'filename': f.name, 'reason': 'file', 'size_bytes': f.stat().st_size, 'created_at': datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}
    except Exception:
        _log_suppressed_exception("80_dashboards_operations.py:350")
    return None

def _s4_disk_status():
    try:
        usage = shutil.disk_usage(str(DB_DIR))
        return {'total': usage.total, 'used': usage.used, 'free': usage.free, 'free_mb': round(usage.free/1024/1024, 2)}
    except Exception as e:
        return {'error': str(e)}

def _s4_required_files():
    required = ['backend/app.py','frontend/index.html','frontend/js/00_core.js','frontend/login.html','frontend/login.js','requirements.txt','Dockerfile','Procfile']
    rows=[]
    for rel in required:
        p = BASE / rel
        rows.append({'path': rel, 'exists': p.exists(), 'size_bytes': p.stat().st_size if p.exists() else 0})
    return rows

@router.get('/api/ops/health')
def sprint4_ops_health(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    counts = {}
    table_status = []
    required_tables = ['admins','sessions','admin_logs','members','recommendations','draws','settings','backup_history','sms_logs','winning_checks']
    with con() as c:
        for t in required_tables:
            try:
                counts[t] = _s4_table_count(c, t)
                table_status.append({'table': t, 'ok': True, 'count': counts[t]})
            except Exception as e:
                table_status.append({'table': t, 'ok': False, 'error': str(e)})
        try:
            recent_errors = c.execute("SELECT action,detail,created_at FROM admin_logs WHERE action LIKE '%ERROR%' ORDER BY id DESC LIMIT 10").fetchall()
        except Exception:
            recent_errors = []
    db_exists = DB.exists()
    response = {
        'ok': True,
        'version': SPRINT4_VERSION,
        'checked_by': admin.get('username'),
        'time': now(),
        'db': {'engine': DB_ENGINE, 'path': str(DB), 'exists': db_exists, 'size_bytes': DB.stat().st_size if db_exists else 0, 'dir': str(DB_DIR)},
        'disk': _s4_disk_status(),
        'counts': counts,
        'tables': table_status,
        'latest_backup': _s4_latest_backup(),
        'required_files': _s4_required_files(),
        'recent_errors': [dict(r) for r in recent_errors],
        'summary': '운영에 필요한 DB, 백업, 필수 파일, 저장공간 상태를 통합 점검했습니다.'
    }
    return response

@router.post('/api/ops/backup/create')
def sprint4_ops_backup_create(request:Request, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    b = create_db_backup('sprint4_manual', admin)
    try: log_action(admin, 'OPS_BACKUP_CREATE', f'Sprint4 운영 백업 생성: {b.get("filename")}', request)
    except Exception: pass
    return {'ok': True, 'version': SPRINT4_VERSION, 'backup': b}

@router.post('/api/ops/backups/cleanup')
def sprint4_ops_backups_cleanup(keep:int=10, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization); require_super_admin(admin)
    keep = max(3, min(int(keep or 10), 50))
    files = sorted(EXPORT_DIR.glob('*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
    removed=[]
    for f in files[keep:]:
        try:
            removed.append({'filename': f.name, 'size_bytes': f.stat().st_size})
            f.unlink()
        except Exception:
            _log_suppressed_exception("80_dashboards_operations.py:421")
    return {'ok': True, 'version': SPRINT4_VERSION, 'keep': keep, 'removed': removed, 'remaining': len(files)-len(removed)}

@router.get('/api/ops/audit/recent')
def sprint4_ops_audit_recent(limit:int=100, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    limit = max(10, min(int(limit or 100), 500))
    with con() as c:
        logs = c.execute('SELECT id,username,action,detail,ip,created_at FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return {'ok': True, 'version': SPRINT4_VERSION, 'logs': [dict(r) for r in logs]}

@router.get('/api/ops/validation')
def sprint4_ops_validation(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    files = _s4_required_files()
    missing_files = [f['path'] for f in files if not f['exists']]
    health = sprint4_ops_health(authorization)
    failed_tables = [t['table'] for t in health.get('tables', []) if not t.get('ok')]
    warnings=[]
    if not health['latest_backup']:
        warnings.append('백업 파일이 아직 없습니다. /api/ops/backup/create 로 백업을 생성하세요.')
    if health.get('disk', {}).get('free_mb', 9999) < 200:
        warnings.append('저장공간이 200MB 미만입니다. 백업 파일 정리가 필요합니다.')
    return {
        'ok': not missing_files and not failed_tables,
        'version': SPRINT4_VERSION,
        'missing_files': missing_files,
        'failed_tables': failed_tables,
        'warnings': warnings,
        'summary': 'Sprint 4 최종 운영 검증 결과입니다.'
    }


# === RC2 Sprint 5: Release / Deployment Readiness ===
SPRINT5_VERSION = 'RC2-Sprint5-Release-Ready'

def _s5_env_status():
    keys = ['PORT','DATABASE_URL','BBLOTTO_DB_DIR','BBLOTTO_EXPORT_DIR','BBLOTTO_SECRET_KEY','ADMIN_USERNAME']
    rows=[]
    for k in keys:
        v=os.getenv(k,'')
        rows.append({'key': k, 'set': bool(str(v).strip()), 'masked': ('***' if str(v).strip() else '')})
    return rows

def _s5_deploy_files():
    required = ['Dockerfile','Procfile','railway.json','requirements.txt','runtime.txt','frontend/index.html','backend/app.py','.gitignore','.dockerignore']
    optional = ['render.yaml','docker-compose.yml','deploy/ubuntu_run.sh','deploy/oracle_cloud_setup.sh','.env.example','START_HERE_DEPLOY.md']
    out=[]
    for rel in required:
        f=BASE/rel
        out.append({'path': rel, 'required': True, 'exists': f.exists(), 'size_bytes': f.stat().st_size if f.exists() else 0})
    for rel in optional:
        f=BASE/rel
        out.append({'path': rel, 'required': False, 'exists': f.exists(), 'size_bytes': f.stat().st_size if f.exists() else 0})
    return out

def _s5_requirements_check():
    req = BASE/'requirements.txt'
    needed = ['fastapi','uvicorn','python-multipart']
    if DB_ENGINE == 'postgresql' or os.getenv('DATABASE_URL'):
        needed.append('psycopg2-binary')
    content = req.read_text(encoding='utf-8', errors='ignore').lower() if req.exists() else ''
    return [{'package': n, 'ok': n.lower() in content} for n in needed]

@router.get('/api/release/readiness')
def sprint5_release_readiness(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    files = _s5_deploy_files()
    missing_required = [x['path'] for x in files if x['required'] and not x['exists']]
    reqs = _s5_requirements_check()
    missing_packages = [x['package'] for x in reqs if not x['ok']]
    health = {'ok': False}
    try:
        health = sprint4_ops_health(authorization)
    except Exception as e:
        health = {'ok': False, 'error': str(e)}
    warnings=[]
    if DB_ENGINE == 'sqlite' and not os.getenv('BBLOTTO_DB_DIR'):
        warnings.append('클라우드 배포에서는 BBLOTTO_DB_DIR 또는 DATABASE_URL 설정을 권장합니다.')
    if not os.getenv('BBLOTTO_SECRET_KEY'):
        warnings.append('운영 환경에서는 BBLOTTO_SECRET_KEY를 설정하는 것이 좋습니다.')
    return {
        'ok': not missing_required and not missing_packages and bool(health.get('ok', False)),
        'version': SPRINT5_VERSION,
        'checked_by': admin.get('username'),
        'time': now(),
        'deployment': {'platform_ready': True, 'recommended_start': 'uvicorn backend.app:app --host 0.0.0.0 --port $PORT'},
        'files': files,
        'missing_required_files': missing_required,
        'requirements': reqs,
        'missing_packages': missing_packages,
        'environment': _s5_env_status(),
        'health_summary': {'ok': health.get('ok'), 'db_engine': DB_ENGINE, 'db_dir': str(DB_DIR)},
        'warnings': warnings,
        'summary': 'Sprint 5 출시/배포 준비 상태 점검 결과입니다.'
    }

@router.get('/api/release/checklist')
def sprint5_release_checklist(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    return {
        'ok': True,
        'version': SPRINT5_VERSION,
        'items': [
            {'step': 1, 'title': 'GitHub 업로드', 'detail': 'ZIP 압축 해제 후 내용물을 저장소 최상위에 업로드'},
            {'step': 2, 'title': '환경변수 설정', 'detail': 'PORT는 플랫폼 자동값 사용, 운영 DB는 DATABASE_URL 또는 BBLOTTO_DB_DIR 지정'},
            {'step': 3, 'title': '배포 시작 명령', 'detail': 'uvicorn backend.app:app --host 0.0.0.0 --port $PORT'},
            {'step': 4, 'title': '상태 확인', 'detail': '/api/health 접속 후 정상 응답 확인'},
            {'step': 5, 'title': '관리자 로그인', 'detail': '관리자 로그인 후 /api/release/readiness 로 최종 점검'},
            {'step': 6, 'title': '백업 생성', 'detail': '운영 전 /api/ops/backup/create 실행 권장'}
        ]
    }


# === RC2 Sprint 6: Release Candidate Stabilization ===
SPRINT6_VERSION = 'RC2-Sprint6-Release-Candidate-Stable'


def _s6_table_count(table):
    try:
        with con() as c:
            row = c.execute(f'SELECT COUNT(*) AS cnt FROM {table}').fetchone()
            return {'table': table, 'ok': True, 'count': int(row['cnt'] if hasattr(row, 'keys') and 'cnt' in row.keys() else row[0])}
    except Exception as e:
        return {'table': table, 'ok': False, 'error': str(e)}


def _s6_file_fingerprint(rel):
    f = BASE / rel
    if not f.exists():
        return {'path': rel, 'exists': False, 'size_bytes': 0}
    h = hashlib.sha256()
    with f.open('rb') as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b''):
            h.update(chunk)
    return {'path': rel, 'exists': True, 'size_bytes': f.stat().st_size, 'sha256_12': h.hexdigest()[:12]}


def _s6_safe_backup_name(label='rc2_sprint6'):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return EXPORT_DIR / f'{label}_{ts}.db'


