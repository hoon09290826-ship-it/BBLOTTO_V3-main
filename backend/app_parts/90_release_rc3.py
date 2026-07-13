# Extracted from legacy backend/app.py lines 5412-5978.
@app.get('/api/rc/version')
def sprint6_rc_version():
    return {
        'ok': True,
        'version': SPRINT6_VERSION,
        'base': 'RC2 Sprint 5',
        'time': now(),
        'db_engine': DB_ENGINE
    }


@app.get('/api/rc/db-safety')
def sprint6_db_safety(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    tables = ['admins','members','draws','admin_logs','settings']
    counts = [_s6_table_count(t) for t in tables]
    warnings = []
    if DB_ENGINE == 'sqlite' and not str(DB_DIR).startswith('/data') and not os.getenv('BBLOTTO_DB_DIR'):
        warnings.append('클라우드 운영에서는 SQLite 기본 경로가 재배포 때 초기화될 수 있습니다. DATABASE_URL 또는 BBLOTTO_DB_DIR 설정을 권장합니다.')
    if not DB.exists() and DB_ENGINE == 'sqlite':
        warnings.append('SQLite DB 파일이 아직 생성되지 않았습니다. 최초 실행 후 다시 확인하세요.')
    return {
        'ok': all(x.get('ok') for x in counts),
        'version': SPRINT6_VERSION,
        'engine': DB_ENGINE,
        'db_dir': str(DB_DIR),
        'db_file': str(DB),
        'tables': counts,
        'warnings': warnings,
        'summary': 'DB 초기화 위험과 핵심 테이블 상태를 점검했습니다.'
    }


@app.post('/api/rc/safe-backup')
def sprint6_safe_backup(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    if DB_ENGINE != 'sqlite':
        return {'ok': False, 'version': SPRINT6_VERSION, 'message': 'PostgreSQL 사용 중에는 플랫폼 DB 백업 기능을 사용하세요.'}
    if not DB.exists():
        raise HTTPException(status_code=404, detail='백업할 SQLite DB 파일이 없습니다.')
    target = _s6_safe_backup_name()
    shutil.copy2(DB, target)
    try:
        log_admin(admin.get('username','admin'), 'rc_safe_backup', f'backup={target.name}', '')
    except Exception:
        pass
    return {'ok': True, 'version': SPRINT6_VERSION, 'backup_file': target.name, 'size_bytes': target.stat().st_size}


@app.get('/api/rc/smoke-test')
def sprint6_smoke_test(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    results = []
    checks = [
        ('health', lambda: health()),
        ('ops_health', lambda: sprint4_ops_health(authorization)),
        ('release_readiness', lambda: sprint5_release_readiness(authorization)),
        ('db_safety', lambda: sprint6_db_safety(authorization)),
    ]
    for name, fn in checks:
        try:
            data = fn()
            results.append({'name': name, 'ok': bool(data.get('ok', False)), 'message': data.get('summary','OK')})
        except Exception as e:
            results.append({'name': name, 'ok': False, 'message': str(e)})
    files = [_s6_file_fingerprint(x) for x in ['backend/app.py','frontend/index.html','frontend/app.js','requirements.txt','Procfile','Dockerfile','START_HERE_DEPLOY.md']]
    ok = all(r['ok'] for r in results) and all(f['exists'] for f in files)
    try:
        log_admin(admin.get('username','admin'), 'rc_smoke_test', f'ok={ok}', '')
    except Exception:
        pass
    return {
        'ok': ok,
        'version': SPRINT6_VERSION,
        'checked_by': admin.get('username'),
        'results': results,
        'files': files,
        'summary': 'RC2 Sprint 6 출시 후보 스모크 테스트 결과입니다.'
    }


@app.get('/api/rc/error-policy')
def sprint6_error_policy():
    return {
        'ok': True,
        'version': SPRINT6_VERSION,
        'policy': {
            'success_shape': {'ok': True, 'data': 'endpoint-specific'},
            'error_shape': {'ok': False, 'error': {'type': '...', 'message': '...'}, 'path': '/api/...', 'time': 'YYYY-MM-DD HH:MM:SS'},
            'admin_required': '관리자 API는 Authorization 헤더가 필요합니다.',
            'safe_message': '예상치 못한 오류는 상세 내부정보 대신 안전한 문구로 반환합니다.'
        }
    }


# === RC3-9: DB / 관리자 로그 / 백업 안정화 ===
# 운영 중 가장 많이 문제가 생기는 데이터 유지, 관리자 기록, 백업 상태를 한 화면에서 점검하기 위한 API입니다.

RC3_9_REQUIRED_TABLES = ['admins','members','recommendations','sms_logs','winning_checks','admin_logs','login_logs','backup_history','settings','draws']


def _rc39_table_count(table: str):
    try:
        with con() as c:
            row = c.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()
            return {'table': table, 'ok': True, 'count': int(row['c'] if row else 0)}
    except Exception as e:
        return {'table': table, 'ok': False, 'count': 0, 'error': str(e)}


def _rc39_latest_backup():
    try:
        with con() as c:
            row = c.execute('SELECT * FROM backup_history ORDER BY id DESC LIMIT 1').fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _rc39_backup_files(limit: int = 20):
    out = []
    for pattern in ('BBLOTTO*_BACKUP_*.json','BBLOTTO*_BACKUP_*.db','BBLOTTO_RC3_BACKUP_*.json','rc2_sprint6_*.db'):
        for f in EXPORT_DIR.glob(pattern):
            try:
                out.append({'filename': f.name, 'size_bytes': f.stat().st_size, 'modified_at': datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'), 'format': f.suffix.lstrip('.')})
            except Exception:
                pass
    out.sort(key=lambda x: x.get('modified_at',''), reverse=True)
    return out[:max(1, min(int(limit or 20), 100))]


def _rc39_database_candidates():
    candidates = []
    f = DB
    rel = str(f) if f.is_absolute() else 'database/bblotto_v34.db'
    candidates.append({'path': rel, 'exists': f.exists(), 'size_bytes': f.stat().st_size if f.exists() else 0, 'primary': True})
    return candidates


@app.get('/api/rc3-9/status')
def rc39_status(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    counts = [_rc39_table_count(t) for t in RC3_9_REQUIRED_TABLES]
    warnings = []
    if DB_ENGINE == 'sqlite' and not os.getenv('BBLOTTO_DB_DIR') and not str(DB_DIR).startswith('/data'):
        warnings.append('Railway 운영에서는 PostgreSQL DATABASE_URL 또는 영구 저장소 DB 경로 설정을 권장합니다.')
    if not _rc39_latest_backup():
        warnings.append('최근 백업 기록이 없습니다. /api/rc3-9/backup-create 실행을 권장합니다.')
    failed = [x for x in counts if not x.get('ok')]
    return {
        'ok': len(failed) == 0,
        'version': RC3_9_VERSION,
        'checked_by': admin.get('username'),
        'time': now(),
        'db_engine': DB_ENGINE,
        'db_path': str(DB) if DB_ENGINE == 'sqlite' else 'postgresql',
        'export_dir': str(EXPORT_DIR),
        'tables': counts,
        'failed_tables': failed,
        'latest_backup': _rc39_latest_backup(),
        'backup_files': _rc39_backup_files(10),
        'database_candidates': _rc39_database_candidates(),
        'warnings': warnings,
        'summary': 'RC3-9 DB/백업/운영 로그 안정화 점검 결과입니다.'
    }


@app.post('/api/rc3-9/backup-create')
def rc39_backup_create(request: Request, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    result = create_db_backup('rc3_9_manual', admin)
    log_action(admin, 'RC3_9_BACKUP_CREATE', f'RC3-9 수동 백업 생성: {result.get("filename","")}', request)
    return {'ok': True, 'version': RC3_9_VERSION, 'backup': result}


@app.get('/api/rc3-9/admin-audit')
def rc39_admin_audit(limit: int = 100, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    limit = max(10, min(int(limit or 100), 300))
    with con() as c:
        recent = c.execute('SELECT id,username,action,detail,ip,created_at FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        by_action = c.execute('SELECT action, COUNT(*) c, MAX(created_at) latest FROM admin_logs GROUP BY action ORDER BY c DESC LIMIT 30').fetchall()
        logins = c.execute('SELECT username, success, message, ip, created_at FROM login_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        failed_today = c.execute('SELECT COUNT(*) c FROM login_logs WHERE success=0 AND created_at LIKE ?', (datetime.datetime.now().strftime('%Y-%m-%d')+'%',)).fetchone()['c']
    return {
        'ok': True,
        'version': RC3_9_VERSION,
        'recent_logs': [dict(r) for r in recent],
        'action_counts': [dict(r) for r in by_action],
        'login_logs': [dict(r) for r in logins],
        'failed_login_today': failed_today
    }


@app.get('/api/rc3-9/recommendation-audit')
def rc39_recommendation_audit(limit: int = 100, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    limit = max(10, min(int(limit or 100), 300))
    with con() as c:
        recent = c.execute('SELECT id,member_id,member_name,round_no,mode,count,avg_score,grade,created_at FROM recommendations ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        by_round = c.execute('SELECT round_no, COUNT(*) c, COALESCE(AVG(avg_score),0) avg_score, MAX(created_at) latest FROM recommendations GROUP BY round_no ORDER BY round_no DESC LIMIT 30').fetchall()
        by_grade = c.execute('SELECT COALESCE(grade,"미분류") grade, COUNT(*) c FROM recommendations GROUP BY COALESCE(grade,"미분류") ORDER BY c DESC').fetchall()
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        today_count = c.execute('SELECT COUNT(*) c FROM recommendations WHERE created_at LIKE ?', (today+'%',)).fetchone()['c']
    return {
        'ok': True,
        'version': RC3_9_VERSION,
        'today_recommendations': today_count,
        'recent': [dict(r) for r in recent],
        'by_round': [dict(r) for r in by_round],
        'by_grade': [dict(r) for r in by_grade]
    }


@app.get('/api/rc3-9/db-standard')
def rc39_db_standard(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    return {
        'ok': True,
        'version': RC3_9_VERSION,
        'primary_database': str(DB) if DB_ENGINE == 'sqlite' else 'DATABASE_URL(PostgreSQL)',
        'db_engine': DB_ENGINE,
        'rule': '운영 기준 DB는 bblotto_v34.db 또는 PostgreSQL DATABASE_URL 하나만 사용합니다.',
        'candidates': _rc39_database_candidates(),
        'recommendation': 'Railway 운영에서는 PostgreSQL 연결을 유지하거나, SQLite를 쓸 경우 BBLOTTO_DB_DIR를 영구 볼륨 경로로 설정하세요.'
    }


# === RC3-10: 당첨번호 자동조회 안정화 ===
@app.get('/api/rc3-10/status')
def rc310_status(round_no:int|None=None, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    r = int(round_no or expected_lotto_round())
    saved = get_draw(r)
    checked = resolve_draw_for_check(r, allow_fetch=True)
    return {
        'ok': True,
        'version': RC3_10_VERSION,
        'round_no': r,
        'draw_status': draw_status_for_round(r),
        'saved': saved,
        'resolved': checked,
        'fallback_available': r in OFFICIAL_DRAW_FALLBACKS,
        'summary': 'RC3-10 당첨번호 자동조회/보조캐시/수동입력 연동 상태입니다.'
    }



# === RC3-12: 회원 연동 당첨확인 안정화 ===
@app.get('/api/rc3-12/status')
def rc312_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        members = c.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        recs = c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c']
        linked = c.execute('SELECT COUNT(*) c FROM recommendations WHERE COALESCE(member_id,0)>0').fetchone()['c']
        checks = c.execute('SELECT COUNT(*) c FROM winning_checks').fetchone()['c']
    return {'ok': True, 'version': 'RC3-12', 'members': members, 'recommendations': recs, 'linked_recommendations': linked, 'winning_checks': checks, 'summary': '회원 선택 → 추천번호 생성 → 추천이력 저장 → 회원별 당첨확인 흐름을 보강했습니다.'}

# === RC3-11: BBLOTTO AI Engine V1.0 추천번호 고도화 ===
AI_ENGINE_V1_VERSION = 'BBLOTTO_AI_ENGINE_V1_0_RC3_11'


def _ai_v1_window_stats(st, window=300):
    draws = list(st.get('draws') or [])[:max(10, int(window or 300))]
    freq = {n: 0 for n in range(1, 46)}
    pair_counts = collections.Counter()
    triple_counts = collections.Counter()
    last_seen = {n: 999 for n in range(1, 46)}
    for idx, d in enumerate(draws):
        nums = sorted(parse_nums(d.get('numbers') or d.get('nums') or []))
        if len(nums) != 6:
            continue
        for n in nums:
            freq[n] += 1
            if last_seen[n] == 999:
                last_seen[n] = idx
        for p in itertools.combinations(nums, 2):
            pair_counts[tuple(sorted(p))] += 1
        for t in itertools.combinations(nums, 3):
            triple_counts[tuple(sorted(t))] += 1
    avg = sum(freq.values()) / 45 if freq else 0
    hot = sorted(range(1, 46), key=lambda n: (-(freq[n]), last_seen[n], n))[:15]
    cold = sorted(range(1, 46), key=lambda n: (freq[n], -last_seen[n], n))[:15]
    overdue = sorted(range(1, 46), key=lambda n: (-last_seen[n], freq[n], n))[:15]
    mid = sorted(range(1, 46), key=lambda n: (abs(freq[n] - avg), last_seen[n], n))[:15]
    return {
        'draws_used': len(draws), 'freq300': freq, 'pair300': pair_counts, 'triple300': triple_counts,
        'last_seen300': last_seen, 'hot300': hot, 'cold300': cold, 'overdue300': overdue, 'mid300': mid,
        'avg300': avg,
    }


def _ai_v1_profile(st, mode='balanced'):
    ext = _ai_v1_window_stats(st, 300)
    f10 = st.get('freq10') or {}; f30 = st.get('freq30') or {}; f50 = st.get('freq50') or {}; f100 = st.get('freq100') or {}
    f300 = ext['freq300']; last = ext['last_seen300']; avg = ext['avg300'] or 1
    recent = set(st.get('recent_numbers') or [])
    weights = {}
    for n in range(1, 46):
        hot_flow = f10.get(n, 0) * 2.2 + f30.get(n, 0) * 1.35 + f50.get(n, 0) * 0.72 + f100.get(n, 0) * 0.38 + f300.get(n, 0) * 0.16
        cold_flow = max(0, avg - f300.get(n, 0)) * 1.25 + min(18, last.get(n, 999)) * 0.23
        mid_flow = max(0, 9 - abs(f100.get(n, 0) - (sum(f100.values()) / 45 if f100 else avg))) * 0.42
        band = 0.9 if 11 <= n <= 35 else 0.55
        if mode == 'aggressive':
            w = 1.0 + hot_flow * 1.15 + cold_flow * 0.62 + mid_flow * 0.45 + band
        elif mode == 'conservative':
            w = 1.0 + hot_flow * 0.72 + cold_flow * 1.12 + mid_flow * 0.85 + band
        else:
            w = 1.0 + hot_flow * 0.92 + cold_flow * 0.88 + mid_flow * 0.72 + band
        if n in recent:
            w *= 0.68  # 직전 3회 과다 반복 방지
        weights[n] = max(0.2, round(w, 4))
    return weights, ext


def _ai_v1_signature(combo):
    combo = sorted(parse_nums(combo))
    odd = sum(n % 2 for n in combo)
    zones = [sum(n <= 15 for n in combo), sum(16 <= n <= 30 for n in combo), sum(n >= 31 for n in combo)]
    decades = collections.Counter((n - 1) // 10 for n in combo)
    end_dup = 6 - len(set(n % 10 for n in combo))
    cons = sum(1 for a, b in zip(combo, combo[1:]) if b - a == 1)
    return {'odd': odd, 'even': 6 - odd, 'zones': zones, 'sum': sum(combo), 'ac': ac_value(combo), 'decade_max': max(decades.values() or [0]), 'end_dup': end_dup, 'cons': cons}


def _ai_v1_combo_score(combo, st, mode='balanced', ext=None, profile=None):
    combo = sorted(parse_nums(combo))
    if len(combo) != 6:
        return 0.0
    ext = ext or _ai_v1_window_stats(st, 300)
    profile = profile or _ai_v1_profile(st, mode)[0]
    sig = _ai_v1_signature(combo)
    pairs = st.get('pair_counts') or collections.Counter()
    pair300 = ext.get('pair300') or collections.Counter()
    triple300 = ext.get('triple300') or collections.Counter()
    score = 46.0
    score += {3: 14, 2: 11, 4: 11, 1: 2, 5: 2}.get(sig['odd'], -9)
    score += 14 if 105 <= sig['sum'] <= 175 else (8 if 95 <= sig['sum'] <= 190 else -12)
    score += 13 if max(sig['zones']) <= 3 and min(sig['zones']) >= 1 else (4 if max(sig['zones']) <= 4 and min(sig['zones']) >= 1 else -12)
    score += 8 if 6 <= sig['ac'] <= 10 else (3 if 5 <= sig['ac'] <= 11 else -7)
    score += 7 if sig['end_dup'] <= 1 else (3 if sig['end_dup'] == 2 else -6)
    score += 5 if sig['cons'] == 0 else (2 if sig['cons'] == 1 else -8)
    score += 4 if sig['decade_max'] <= 2 else (-5 if sig['decade_max'] >= 4 else 1)
    # 번호별 가중치: 높을수록 좋지만 한쪽으로만 몰리면 감점
    wsum = sum(profile.get(n, 1) for n in combo)
    score += min(10, wsum / 13)
    hot = set(ext.get('hot300', [])[:12]); cold = set(ext.get('cold300', [])[:12]); overdue = set(ext.get('overdue300', [])[:12]); mid = set(ext.get('mid300', [])[:12])
    hot_hit = len(set(combo) & hot); cold_hit = len(set(combo) & cold); overdue_hit = len(set(combo) & overdue); mid_hit = len(set(combo) & mid)
    score += min(7, hot_hit * 1.8) + min(5.5, cold_hit * 1.55) + min(5.5, overdue_hit * 1.55) + min(3.5, mid_hit * 0.8)
    if hot_hit >= 5:
        score -= 5
    if len(set(combo) & set(st.get('recent_numbers') or [])) >= 4:
        score -= 5
    pair_score = sum((pairs.get(tuple(sorted(p)), 0) * 0.62 + pair300.get(tuple(sorted(p)), 0) * 0.38) for p in itertools.combinations(combo, 2))
    strong_pairs = sum(1 for p in itertools.combinations(combo, 2) if (pairs.get(tuple(sorted(p)), 0) + pair300.get(tuple(sorted(p)), 0)) >= 4)
    triple_score = sum(triple300.get(tuple(sorted(t)), 0) for t in itertools.combinations(combo, 3))
    score += min(8, pair_score / 8.5) + min(5, strong_pairs * 1.1) + min(4.5, triple_score / 3.5)
    if strong_pairs >= 8:
        score -= 4
    if triple_score >= 10:
        score -= 3
    # 작은 난수 대신 결정적 흔들림으로 동점 완화
    score += ((sum(n * n for n in combo) + sig['sum']) % 23 - 11) * 0.08
    return round(max(64.0, min(98.8, score)), 1)


def _ai_v1_reasons(combo, st, ext=None):
    combo = sorted(parse_nums(combo)); ext = ext or _ai_v1_window_stats(st, 300); s = set(combo)
    sig = _ai_v1_signature(combo)
    reasons = []
    if len(s & set(ext.get('hot300', [])[:12])) >= 2:
        reasons.append('최근/장기 핵심수 반영')
    if len(s & set(ext.get('overdue300', [])[:12])) >= 1:
        reasons.append('미출현 보강수 포함')
    if len(s & set(ext.get('cold300', [])[:12])) >= 1:
        reasons.append('저출현 반등 후보 포함')
    if sig['odd'] in (2, 3, 4):
        reasons.append(f'홀짝 {sig["odd"]}:{sig["even"]} 균형')
    if max(sig['zones']) <= 3 and min(sig['zones']) >= 1:
        reasons.append('저·중·고 구간 분산')
    if 6 <= sig['ac'] <= 10:
        reasons.append(f'AC값 {sig["ac"]} 안정권')
    if sig['end_dup'] <= 1:
        reasons.append('끝수 중복 최소화')
    if sig['cons'] <= 1:
        reasons.append('연속수 과다 배제')
    pair_hits = []
    for a, b in itertools.combinations(combo, 2):
        c = (st.get('pair_counts') or {}).get(tuple(sorted((a, b))), 0) + (ext.get('pair300') or {}).get(tuple(sorted((a, b))), 0)
        if c >= 3:
            pair_hits.append({'pair': [a, b], 'count': int(c)})
    return reasons[:6] or ['균형형 후보'], sorted(pair_hits, key=lambda x: -x['count'])[:3]


def _ai_v1_detail(combo, st, mode, ext=None, profile=None):
    ext = ext or _ai_v1_window_stats(st, 300); profile = profile or _ai_v1_profile(st, mode)[0]
    combo = sorted(parse_nums(combo)); sig = _ai_v1_signature(combo); reasons, pair_hits = _ai_v1_reasons(combo, st, ext)
    score = _ai_v1_combo_score(combo, st, mode, ext, profile)
    return {
        'numbers': combo, 'score': score, 'ai_score': score, 'vip_score': score,
        'grade': 'VIP' if score >= 94 else 'PREMIUM' if score >= 88 else 'STANDARD',
        'star': '★★★★★' if score >= 94 else '★★★★☆' if score >= 88 else '★★★★',
        'tags': reasons[:4], 'reasons': reasons, 'reason_text': ' · '.join(reasons[:4]),
        'sum': sig['sum'], 'odd': sig['odd'], 'even': sig['even'], 'zones': sig['zones'], 'ac': sig['ac'],
        'end_digit_dup': sig['end_dup'], 'consecutive': sig['cons'], 'pair_hits': pair_hits,
        'engine_version': AI_ENGINE_V1_VERSION,
        'v2_reason': '최근 10/30/50/100/300회 가중치, 페어·트리플, AC값, 끝수, 구간, 포트폴리오 중복 제한을 종합했습니다.'
    }


def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    """RC3-11 / BBLOTTO AI Engine V1.0: 후보 대량 생성 → 점수화 → 포트폴리오 분산 → 근거 표시."""
    st = latest_stats(300)
    fixed_set = set(parse_nums(fixed)); excluded_set = set(parse_nums(excluded))
    fixed_set = {n for n in fixed_set if n not in excluded_set}
    if len(fixed_set) > 6:
        fixed_set = set(sorted(fixed_set)[:6])
    pool = [n for n in range(1, 46) if n not in excluded_set and n not in fixed_set]
    target = max(1, min(50, int(count or 10)))
    if len(pool) + len(fixed_set) < 6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    profile, ext = _ai_v1_profile(st, mode)
    past = {tuple(d['numbers']) for d in st.get('draws', []) if len(d.get('numbers', [])) == 6}
    buckets = {
        'hot': [n for n in ext['hot300'][:18] if n in pool],
        'cold': [n for n in ext['cold300'][:18] if n in pool],
        'overdue': [n for n in ext['overdue300'][:18] if n in pool],
        'mid': [n for n in ext['mid300'][:18] if n in pool],
        'all': pool[:],
    }
    if mode == 'aggressive':
        plans = [['hot','hot','mid','overdue','all','all'], ['hot','mid','all','all','overdue','cold']]
    elif mode == 'conservative':
        plans = [['cold','overdue','mid','mid','all','all'], ['mid','cold','all','overdue','all','hot']]
    else:
        plans = [['hot','cold','overdue','mid','all','all'], ['hot','mid','cold','overdue','all','all']]
    candidates = []
    seen = set()
    tries = 0
    needed = max(3800, target * 320)
    while len(candidates) < needed and tries < max(85000, needed * 26):
        tries += 1
        nums = set(fixed_set)
        plan = random.choice(plans)[:]
        random.shuffle(plan)
        for b in plan:
            if len(nums) >= 6:
                break
            usable = [n for n in buckets.get(b, pool) if n not in nums]
            if usable:
                nums.update(_weighted_pick(usable, [profile[n] for n in usable], 1))
        while len(nums) < 6:
            usable = [n for n in pool if n not in nums]
            nums.update(_weighted_pick(usable, [profile[n] for n in usable], 1))
        arr = tuple(sorted(nums))
        if len(arr) != 6 or arr in seen or arr in past:
            continue
        sig = _ai_v1_signature(arr)
        if sig['odd'] not in (2, 3, 4):
            continue
        if not (92 <= sig['sum'] <= 190):
            continue
        if max(sig['zones']) > 3 or min(sig['zones']) == 0:
            continue
        if sig['cons'] > 1:
            continue
        if sig['end_dup'] > 2:
            continue
        if not (5 <= sig['ac'] <= 11):
            continue
        seen.add(arr)
        candidates.append((_ai_v1_combo_score(arr, st, mode, ext, profile), list(arr)))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    usage = collections.Counter()
    pair_usage = collections.Counter()
    for score, combo in candidates:
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        if any(usage[n] >= 3 for n in combo if n not in fixed_set):
            continue
        if any(pair_usage[p] >= 1 for p in pairs):
            continue
        if all(len(set(combo) & set(prev)) <= 3 for prev in selected):
            selected.append(combo); usage.update(combo); pair_usage.update(pairs)
        if len(selected) >= target:
            break
    if len(selected) < target:
        for score, combo in candidates:
            if combo in selected:
                continue
            pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
            if any(usage[n] >= 4 for n in combo if n not in fixed_set):
                continue
            if any(pair_usage[p] >= 2 for p in pairs):
                continue
            if all(len(set(combo) & set(prev)) <= 4 for prev in selected):
                selected.append(combo); usage.update(combo); pair_usage.update(pairs)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo)
            if len(selected) >= target:
                break
    details = [_ai_v1_detail(c, st, mode, ext, profile) for c in selected[:target]]
    st.update(ext)
    st['ai_v1_candidates'] = len(candidates)
    st['ai_v1_attempts'] = tries
    st['engine_version'] = AI_ENGINE_V1_VERSION
    return selected[:target], details, st


def _engine_summary(details, st):
    scores = [float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    return {
        'version': AI_ENGINE_V1_VERSION,
        'engine_version': AI_ENGINE_V1_VERSION,
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('ai_v1_candidates') or st.get('s23_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'ai_engine_v1_report': {
            'pipeline': '최근 10/30/50/100/300회 통계 → 번호별 가중치 → 페어·트리플 분석 → 후보 대량 생성 → 패턴 필터 → 포트폴리오 분산 → TOP3 선정',
            'draws_used': int(st.get('draws_used') or len(st.get('draws') or [])),
            'candidate_count': int(st.get('ai_v1_candidates') or 0),
            'attempts': int(st.get('ai_v1_attempts') or 0),
            'filters': '홀짝 2:4~4:2 / 합계 92~190 / 구간 1개 이상 / AC 5~11 / 끝수·연속수 제한',
            'portfolio': '동일 번호 과사용, 동일 페어 반복, 조합 간 4~5개 이상 중복을 제한합니다.',
            'summary': 'BBLOTTO AI Engine V1.0은 단순 랜덤이 아니라 후보 조합을 대량 생성한 뒤 통계 근거와 분산 품질로 최종 선별합니다.'
        },
        'v2_pipeline_report': {
            'pipeline': '최근 10/30/50/100/300회 통계 → 가중치 → 후보 생성 → 점수화 → 분산 선별',
            'stage1_candidates': int(st.get('ai_v1_candidates') or 0),
            'stage2_filters': '페어/트리플/AC/끝수/연속수/구간 필터',
            'stage3_portfolio': '번호·페어 과사용 제한 및 TOP3 우선 표시',
            'summary': 'RC3-11 AI Engine V1.0 적용 완료'
        }
    }


def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    details = details or []
    engine = _engine_summary(details, st)
    best = sorted(details, key=lambda x: -float(x.get('score') or 0))[:3]
    top_nums = []
    for d in best:
        for n in d.get('numbers', []):
            if n not in top_nums:
                top_nums.append(n)
    avg = engine.get('avg_score', 0)
    hot = (st.get('hot300') or st.get('hot') or [])[:6]
    overdue = (st.get('overdue300') or st.get('overdue') or [])[:6]
    mode_name = {'balanced': '균형형', 'aggressive': '공격형', 'conservative': '보수형'}.get(mode, mode or '균형형')
    lines = [
        f'{round_no}회차는 {mode_name} 기준으로 최근 10/30/50/100/300회 흐름을 함께 반영했습니다.',
        f'핵심 흐름은 {", ".join(map(str, hot)) if hot else "자동 분석"} / 보강 흐름은 {", ".join(map(str, overdue)) if overdue else "분산 보강"} 중심입니다.',
        f'TOP3 후보 핵심 번호는 {", ".join(map(str, top_nums[:8])) if top_nums else "생성 결과 기준 자동 산출"}이며 평균 AI 점수는 {avg}점입니다.',
        '페어·트리플 출현, AC값, 끝수, 구간, 홀짝, 조합 간 중복을 동시에 제한했습니다.',
        ''
    ]
    return '\n'.join(lines)


