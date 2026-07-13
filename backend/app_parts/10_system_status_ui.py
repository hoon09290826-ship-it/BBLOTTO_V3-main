# Extracted from legacy backend/app.py lines 1493-2108.
@router.get('/api/rc6-10/status')
def rc6_10_status():
    return {'ok': True, 'version': 'RC6-10_SQL_PERCENT_STABLE', 'fix': 'postgres percent placeholder stable'}

@router.get('/api/health')
def health():
    return {'ok': True, 'app': APP_VERSION, 'phase': RC_VERSION, 'rc_version': RC_VERSION, 'time': now(), 'db_engine': DB_ENGINE, 'database_url_set': bool(DATABASE_URL), 'db_path': str(DB), 'persistent_dir': str(DB_DIR)}



@router.get('/api/rc5-12/status')
def rc5_12_status():
    """RC5-12: GitHub/Railway 배포 안정성 및 회원검색 상태 진단."""
    checks = []
    def add(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
    add('frontend_exists', FRONT.exists(), str(FRONT))
    add('database_dir_writable', os.access(str(DB_DIR), os.W_OK), str(DB_DIR))
    add('export_dir_writable', os.access(str(EXPORT_DIR), os.W_OK), str(EXPORT_DIR))
    add('db_file_ready', DB.exists(), str(DB))
    try:
        with con() as c:
            tables = {r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            add('members_table', 'members' in tables, '회원관리 테이블')
            add('admins_table', 'admins' in tables, '관리자 테이블')
            member_count = c.execute('SELECT COUNT(*) c FROM members').fetchone()['c'] if 'members' in tables else 0
            admin_count = c.execute('SELECT COUNT(*) c FROM admins').fetchone()['c'] if 'admins' in tables else 0
    except Exception as e:
        add('database_open', False, str(e))
        member_count = 0
        admin_count = 0
    return {
        'ok': all(x['ok'] for x in checks),
        'app': APP_VERSION,
        'rc_version': RC_VERSION,
        'time': now(),
        'counts': {'members': member_count, 'admins': admin_count},
        'checks': checks,
        'next': '회원검색은 /api/members?q=검색어 로 진단할 수 있습니다.'
    }


@router.get('/api/rc5-13/status')
def rc5_13_status():
    """RC5-13: GitHub/Railway 배포 전 최종 진단 및 핵심 테이블 상태 점검."""
    checks = []
    counts = {}
    def add(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    required_files = [
        ('start.py', BASE / 'start.py'),
        ('requirements.txt', BASE / 'requirements.txt'),
        ('runtime.txt', BASE / 'runtime.txt'),
        ('frontend/index.html', FRONT / 'index.html'),
        ('frontend/app.js', FRONT / 'app.js'),
        ('frontend/login.html', FRONT / 'login.html'),
        ('frontend/login.js', FRONT / 'login.js'),
    ]
    for name, path in required_files:
        add(f'file:{name}', path.exists(), path)

    add('database_dir_writable', DB_DIR.exists() and os.access(str(DB_DIR), os.W_OK), DB_DIR)
    add('export_dir_writable', EXPORT_DIR.exists() and os.access(str(EXPORT_DIR), os.W_OK), EXPORT_DIR)
    add('db_engine_ready', DB_ENGINE in ('sqlite', 'postgresql'), DB_ENGINE)

    required_tables = ['admins', 'members', 'recommendations', 'sms_logs', 'winning_checks', 'draws', 'settings', 'admin_logs']
    try:
        with con() as c:
            for table in required_tables:
                try:
                    row = c.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()
                    counts[table] = int(row['c'] if hasattr(row, 'keys') else row[0])
                    add(f'table:{table}', True, f'{counts[table]} rows')
                except Exception as e:
                    counts[table] = 0
                    add(f'table:{table}', False, str(e)[:180])
    except Exception as e:
        add('database_connection', False, str(e)[:180])

    # GitHub에 올리면 안 되는 산출물/캐시가 남아있는지 간단 점검
    blocked = []
    for root, dirs, files in os.walk(BASE):
        rel_root = os.path.relpath(root, BASE)
        if '.git' in rel_root.split(os.sep):
            continue
        for d in list(dirs):
            if d == '__pycache__':
                blocked.append(os.path.join(rel_root, d))
        for f in files:
            if f.endswith(('.pyc', '.pyo', '.bak', '.tmp')):
                blocked.append(os.path.join(rel_root, f))
    add('github_clean_cache', len(blocked) == 0, ', '.join(blocked[:10]) if blocked else 'clean')

    return {
        'ok': all(x['ok'] for x in checks),
        'app': APP_VERSION,
        'rc_version': RC_VERSION,
        'time': now(),
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'paths': {'base': str(BASE), 'db_dir': str(DB_DIR), 'export_dir': str(EXPORT_DIR)},
        'counts': counts,
        'checks': checks,
        'message': 'RC5-13 배포 전 최종 점검입니다. ok가 true이면 GitHub/Railway 업로드 준비 상태입니다.'
    }


@router.get('/api/rc5-14/status')
def rc5_14_status():
    """RC5-14: GitHub/Railway 최종 업로드 전 파일/DB/환경 점검."""
    checks = []
    counts = {}
    def add(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})

    required_files = [
        ('start.py', BASE / 'start.py'),
        ('requirements.txt', BASE / 'requirements.txt'),
        ('runtime.txt', BASE / 'runtime.txt'),
        ('railway.json', BASE / 'railway.json'),
        ('Dockerfile', BASE / 'Dockerfile'),
        ('.env.example', BASE / '.env.example'),
        ('.gitignore', BASE / '.gitignore'),
        ('frontend/index.html', FRONT / 'index.html'),
        ('frontend/app.js', FRONT / 'app.js'),
        ('frontend/style.css', FRONT / 'style.css'),
    ]
    for name, path in required_files:
        add(f'file:{name}', path.exists(), path)

    add('database_dir_ready', DB_DIR.exists() and os.access(str(DB_DIR), os.W_OK), DB_DIR)
    add('export_dir_ready', EXPORT_DIR.exists() and os.access(str(EXPORT_DIR), os.W_OK), EXPORT_DIR)
    add('db_engine_valid', DB_ENGINE in ('sqlite', 'postgresql'), DB_ENGINE)

    required_tables = ['admins', 'members', 'recommendations', 'sms_logs', 'winning_checks', 'draws', 'settings', 'admin_logs']
    try:
        with con() as c:
            for table in required_tables:
                try:
                    row = c.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()
                    counts[table] = int(row['c'] if hasattr(row, 'keys') else row[0])
                    add(f'table:{table}', True, f'{counts[table]} rows')
                except Exception as e:
                    counts[table] = 0
                    add(f'table:{table}', False, str(e))
    except Exception as e:
        add('database_connection', False, str(e))

    blocked = []
    secret_files = []
    backup_files = []
    for root, dirs, files in os.walk(BASE):
        rel_root = os.path.relpath(root, BASE)
        parts = set(rel_root.split(os.sep))
        if '.git' in parts:
            continue
        for d in list(dirs):
            if d in ('__pycache__', '.pytest_cache', '.mypy_cache'):
                blocked.append(os.path.join(rel_root, d))
        for f in files:
            p = os.path.join(rel_root, f)
            if f.endswith(('.pyc', '.pyo', '.tmp')):
                blocked.append(p)
            if f in ('.env', 'env.txt'):
                secret_files.append(p)
            if f.endswith(('.bak', '.backup', '.old')) or 'backup' in f.lower():
                backup_files.append(p)
    add('no_python_cache_files', len(blocked) == 0, ', '.join(blocked[:10]) if blocked else 'clean')
    add('no_secret_env_files', len(secret_files) == 0, ', '.join(secret_files[:10]) if secret_files else 'clean')
    add('no_backup_artifacts', len(backup_files) == 0, ', '.join(backup_files[:10]) if backup_files else 'clean')

    return {
        'ok': all(x['ok'] for x in checks),
        'app': APP_VERSION,
        'rc_version': RC_VERSION,
        'time': now(),
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'paths': {'base': str(BASE), 'db_dir': str(DB_DIR), 'export_dir': str(EXPORT_DIR)},
        'counts': counts,
        'checks': checks,
        'message': 'RC5-14 업로드 전 최종 점검입니다. ok가 true이면 GitHub/Railway 배포 준비 상태입니다.'
    }


@router.get('/api/rc5-15/status')
def rc5_15_status():
    """RC5-15: 배포 직전 GitHub/Railway 실행 안정성 점검."""
    checks = []
    counts = {}
    def add(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:500]})

    required_files = [
        ('start.py', BASE / 'start.py'),
        ('requirements.txt', BASE / 'requirements.txt'),
        ('runtime.txt', BASE / 'runtime.txt'),
        ('railway.json', BASE / 'railway.json'),
        ('Procfile', BASE / 'Procfile'),
        ('Dockerfile', BASE / 'Dockerfile'),
        ('.env.example', BASE / '.env.example'),
        ('.gitignore', BASE / '.gitignore'),
        ('frontend/index.html', FRONT / 'index.html'),
        ('frontend/app.js', FRONT / 'app.js'),
        ('frontend/style.css', FRONT / 'style.css'),
    ]
    for name, path in required_files:
        add(f'file:{name}', path.exists(), path)

    # Railway/Render에서 가장 자주 나는 문제: PORT 미사용, 시작 명령 불일치, 로컬 주소 하드코딩
    try:
        start_text = (BASE / 'start.py').read_text(encoding='utf-8')
        add('start_uses_port_env', 'PORT' in start_text and '0.0.0.0' in start_text, 'start.py must bind 0.0.0.0:$PORT')
    except Exception as e:
        add('start_uses_port_env', False, str(e))

    try:
        railway_text = (BASE / 'railway.json').read_text(encoding='utf-8')
        add('railway_start_command_ready', 'python start.py' in railway_text or 'start.py' in railway_text, railway_text[:200])
    except Exception as e:
        add('railway_start_command_ready', False, str(e))

    try:
        app_js = (FRONT / 'app.js').read_text(encoding='utf-8')
        login_js = (FRONT / 'login.js').read_text(encoding='utf-8') if (FRONT / 'login.js').exists() else ''
        hardcoded = []
        for token in ('localhost:', '127.0.0.1:', 'http://localhost', 'http://127.0.0.1'):
            if token in app_js or token in login_js:
                hardcoded.append(token)
        add('frontend_no_localhost_api', not hardcoded, ', '.join(hardcoded) if hardcoded else 'clean')
    except Exception as e:
        add('frontend_no_localhost_api', False, str(e))

    add('database_dir_ready', DB_DIR.exists() and os.access(str(DB_DIR), os.W_OK), DB_DIR)
    add('export_dir_ready', EXPORT_DIR.exists() and os.access(str(EXPORT_DIR), os.W_OK), EXPORT_DIR)
    add('db_engine_valid', DB_ENGINE in ('sqlite', 'postgresql'), DB_ENGINE)

    required_tables = ['admins', 'members', 'recommendations', 'sms_logs', 'winning_checks', 'draws', 'settings', 'admin_logs']
    try:
        with con() as c:
            for table in required_tables:
                try:
                    row = c.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()
                    counts[table] = int(row['c'] if hasattr(row, 'keys') else row[0])
                    add(f'table:{table}', True, f'{counts[table]} rows')
                except Exception as e:
                    counts[table] = 0
                    add(f'table:{table}', False, str(e))
    except Exception as e:
        add('database_connection', False, str(e))

    blocked = []
    secret_files = []
    backup_files = []
    large_files = []
    for root, dirs, files in os.walk(BASE):
        rel_root = os.path.relpath(root, BASE)
        parts = set(rel_root.split(os.sep))
        if '.git' in parts:
            continue
        for d in list(dirs):
            if d in ('__pycache__', '.pytest_cache', '.mypy_cache'):
                blocked.append(os.path.join(rel_root, d))
        for f in files:
            p = os.path.join(rel_root, f)
            fp = Path(root) / f
            if f.endswith(('.pyc', '.pyo', '.tmp')):
                blocked.append(p)
            if f in ('.env', 'env.txt'):
                secret_files.append(p)
            if f.endswith(('.bak', '.backup', '.old')) or 'backup' in f.lower():
                backup_files.append(p)
            try:
                if fp.stat().st_size > 20 * 1024 * 1024:
                    large_files.append(p)
            except Exception:
                _log_suppressed_exception("10_system_status_ui.py:279")
    add('no_python_cache_files', len(blocked) == 0, ', '.join(blocked[:10]) if blocked else 'clean')
    add('no_secret_env_files', len(secret_files) == 0, ', '.join(secret_files[:10]) if secret_files else 'clean')
    add('no_backup_artifacts', len(backup_files) == 0, ', '.join(backup_files[:10]) if backup_files else 'clean')
    add('no_large_artifacts_over_20mb', len(large_files) == 0, ', '.join(large_files[:10]) if large_files else 'clean')

    return {
        'ok': all(x['ok'] for x in checks),
        'app': APP_VERSION,
        'rc_version': RC_VERSION,
        'time': now(),
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'paths': {'base': str(BASE), 'db_dir': str(DB_DIR), 'export_dir': str(EXPORT_DIR)},
        'counts': counts,
        'checks': checks,
        'message': 'RC5-15 배포 직전 안정성 점검입니다. ok가 true이면 GitHub/Railway 업로드 준비 상태입니다.'
    }


@router.get('/api/rc5-16/status')
def rc5_16_status():
    """RC5-16: GitHub 보안/정리 상태 점검."""
    checks = []
    def add(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:500]})

    for name in ['.gitignore', '.env.example', 'README.md', 'requirements.txt', 'start.py', 'Procfile', 'runtime.txt']:
        add(f'file:{name}', (BASE / name).exists(), BASE / name)

    cache_items, secret_items, db_items, backup_items = [], [], [], []
    for root, dirs, files in os.walk(BASE):
        rel_root = os.path.relpath(root, BASE)
        if '.git' in set(rel_root.split(os.sep)):
            continue
        for d in dirs:
            if d == '__pycache__':
                cache_items.append(os.path.join(rel_root, d))
        for f in files:
            rel = os.path.join(rel_root, f)
            low = f.lower()
            if low.endswith(('.pyc', '.pyo', '.pyd')):
                cache_items.append(rel)
            if f == '.env' or f.startswith('.env.') and f != '.env.example':
                secret_items.append(rel)
            if low.endswith(('.db', '.sqlite', '.sqlite3')):
                db_items.append(rel)
            if low.endswith(('.bak', '.backup', '.old')) or 'backup' in low:
                backup_items.append(rel)

    add('no_python_cache', not cache_items, ', '.join(cache_items[:10]) if cache_items else 'clean')
    add('no_env_secret_files', not secret_items, ', '.join(secret_items[:10]) if secret_items else 'clean')
    add('no_database_files_in_repo', not db_items, ', '.join(db_items[:10]) if db_items else 'clean')
    add('no_backup_artifacts', not backup_items, ', '.join(backup_items[:10]) if backup_items else 'clean')

    try:
        app_text = (BASE / 'backend' / 'app.py').read_text(encoding='utf-8')
        add('no_admin1234_hardcode', 'admin1234' not in app_text, 'hardcoded admin password removed')
        add('env_admin_password_supported', 'BBLOTTO_ADMIN_PASSWORD' in app_text, 'BBLOTTO_ADMIN_PASSWORD')
    except Exception as e:
        add('source_check', False, str(e))

    return {
        'ok': all(x['ok'] for x in checks),
        'app': APP_VERSION,
        'rc_version': RC_VERSION,
        'time': now(),
        'checks': checks,
        'message': 'RC5-16 GitHub 보안/정리 점검입니다. ok가 true이면 업로드 안전 상태입니다.'
    }

@router.get('/api/persistence_status')
def persistence_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        counts = {
            'members': c.execute('SELECT COUNT(*) c FROM members').fetchone()['c'],
            'recommendations': c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c'],
            'sms_logs': c.execute('SELECT COUNT(*) c FROM sms_logs').fetchone()['c'],
            'winning_checks': c.execute('SELECT COUNT(*) c FROM winning_checks').fetchone()['c'],
            'draws': c.execute('SELECT COUNT(*) c FROM draws').fetchone()['c'],
        }
    return {
        'ok': True,
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'db_path': str(DB),
        'db_dir': str(DB_DIR),
        'export_dir': str(EXPORT_DIR),
        'db_exists': DB.exists(),
        'db_size_bytes': DB.stat().st_size if DB.exists() else 0,
        'using_render_disk': str(DB).startswith('/data/'),
        'counts': counts,
        'message': 'BBLOTTO_DB_DIR 또는 /data Render Disk를 사용하면 재접속/재배포 후에도 데이터가 유지됩니다.'
    }


RC3_VERSION = 'RC3_3_MEMBER_DB_POSTGRES'

RC3_MIGRATION_TABLES = [
    'admins', 'sessions', 'admin_logs', 'login_logs', 'backup_history', 'members',
    'recommendations', 'sms_logs', 'winning_checks', 'draws', 'settings',
    'consultations', 'sms_templates', 'engine_runs', 'dashboard_snapshots'
]

def _sqlite_source_path():
    return Path(os.getenv('BBLOTTO_SQLITE_SOURCE_PATH', str(BASE / 'database' / 'bblotto_v34.db')))

def _table_exists_sqlite(path: Path, table: str) -> bool:
    if not path.exists():
        return False
    try:
        sc = sqlite3.connect(path)
        row = sc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        sc.close()
        return bool(row)
    except Exception:
        return False

def _pg_set_sequence(c, table: str):
    if DB_ENGINE != 'postgresql' or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', table):
        return
    try:
        c.execute('SAVEPOINT rc3_seq')
        c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), GREATEST(COALESCE((SELECT MAX(id) FROM {table}),0),1), true)")
        c.execute('RELEASE SAVEPOINT rc3_seq')
    except Exception:
        try:
            c.execute('ROLLBACK TO SAVEPOINT rc3_seq')
            c.execute('RELEASE SAVEPOINT rc3_seq')
        except Exception:
            _log_suppressed_exception("10_system_status_ui.py:410")

def rc3_migrate_sqlite_to_current_db(source_path: Path | None = None):
    """기존 SQLite DB 데이터를 현재 DB(PostgreSQL 권장)로 1회성 복사합니다."""
    source_path = source_path or _sqlite_source_path()
    if DB_ENGINE != 'postgresql':
        return {'ok': False, 'version': RC3_VERSION, 'message': '현재는 PostgreSQL 모드가 아닙니다.', 'db_engine': DB_ENGINE}
    if not source_path.exists():
        return {'ok': False, 'version': RC3_VERSION, 'message': '이전 SQLite DB 파일을 찾을 수 없습니다.', 'source_path': str(source_path)}

    migrated = []
    skipped = []
    errors = []
    sc = sqlite3.connect(source_path)
    sc.row_factory = sqlite3.Row
    with con() as c:
        for table in RC3_MIGRATION_TABLES:
            if not _table_exists_sqlite(source_path, table):
                skipped.append({'table': table, 'reason': 'source table missing'})
                continue
            try:
                source_cols = [r[1] for r in sc.execute(f'PRAGMA table_info({table})').fetchall()]
                target_cols = table_cols(c, table)
                cols = [x for x in source_cols if x in target_cols]
                if not cols:
                    skipped.append({'table': table, 'reason': 'no common columns'})
                    continue
                rows = sc.execute(f'SELECT {", ".join(cols)} FROM {table}').fetchall()
                if not rows:
                    migrated.append({'table': table, 'rows': 0})
                    continue
                placeholders = ','.join(['?'] * len(cols))
                col_sql = ','.join(cols)
                sql = f'INSERT INTO {table}({col_sql}) VALUES({placeholders}) ON CONFLICT DO NOTHING'
                count = 0
                for row in rows:
                    vals = [row[col] for col in cols]
                    c.execute(sql, vals)
                    count += 1
                _pg_set_sequence(c, table)
                migrated.append({'table': table, 'rows': count})
            except Exception as e:
                errors.append({'table': table, 'error': str(e)[:300]})
                try: c.rollback()
                except Exception: pass
        c.commit()
    sc.close()
    return {'ok': len(errors) == 0, 'version': RC3_VERSION, 'source_path': str(source_path), 'migrated': migrated, 'skipped': skipped, 'errors': errors}

@router.get('/api/rc3/database/status')
def rc3_database_status():
    counts = {}
    warnings = []
    try:
        with con() as c:
            for t in ['admins','members','recommendations','winning_checks','draws','settings']:
                try:
                    counts[t] = c.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c']
                except Exception as e:
                    counts[t] = f'error: {str(e)[:120]}'
    except Exception as e:
        warnings.append('DB 연결 실패: ' + str(e)[:200])
    if DB_ENGINE != 'postgresql':
        warnings.append('현재 web 서비스에 DATABASE_URL 또는 Postgres 변수 참조가 연결되지 않았습니다.')
    return {
        'ok': DB_ENGINE == 'postgresql' and not warnings,
        'version': RC3_VERSION,
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'sqlite_source_path': str(_sqlite_source_path()),
        'sqlite_source_exists': _sqlite_source_path().exists(),
        'counts': counts,
        'warnings': warnings,
        'message': 'Railway에서는 web 서비스 Variables에 DATABASE_URL=${{Postgres.DATABASE_URL}} 를 연결해야 PostgreSQL을 사용합니다.'
    }

@router.post('/api/rc3/migrate/sqlite-to-postgres')
def rc3_migrate_sqlite_to_postgres(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    result = rc3_migrate_sqlite_to_current_db()
    try:
        log_action(admin, 'RC3_MIGRATE_SQLITE_TO_POSTGRES', json.dumps(result, ensure_ascii=False)[:500])
    except Exception:
        _log_suppressed_exception("10_system_status_ui.py:493")
    return result


@router.post('/api/rc3/member-db/ensure')
def rc3_member_db_ensure(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    init_db()
    try:
        log_action(admin, 'RC3_3_ENSURE_MEMBER_DB', '회원/관리자 PostgreSQL 스키마 점검 및 보강')
    except Exception:
        _log_suppressed_exception("10_system_status_ui.py:504")
    return rc3_member_db_status(authorization)

@router.get('/api/rc3/member-db/status')
def rc3_member_db_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    tables = ['admins','sessions','login_logs','admin_logs','members','recommendations','sms_logs','winning_checks','settings']
    counts = {}
    columns = {}
    with con() as c:
        for t in tables:
            try:
                counts[t] = c.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c']
                columns[t] = table_cols(c, t)
            except Exception as e:
                counts[t] = 'error: ' + str(e)[:160]
                columns[t] = []
        admin_roles = c.execute("SELECT COALESCE(role,'전체권한') label, COUNT(*) c FROM admins GROUP BY COALESCE(role,'전체권한')").fetchall()
        member_status = c.execute("SELECT COALESCE(status,'활성') label, COUNT(*) c FROM members GROUP BY COALESCE(status,'활성')").fetchall()
    required = {
        'admins': ['id','username','name','password_hash','is_active','role','last_login_at','last_ip'],
        'members': ['id','name','phone','grade','status','priority','source','created_by','created_at','updated_at'],
        'login_logs': ['id','admin_id','username','success','ip','user_agent','message','created_at'],
        'admin_logs': ['id','admin_id','username','action','detail','ip','created_at']
    }
    missing = {t:[col for col in req if col not in columns.get(t, [])] for t, req in required.items()}
    return {
        'ok': DB_ENGINE == 'postgresql' and not any(missing.values()),
        'version': RC3_VERSION,
        'db_engine': DB_ENGINE,
        'database_url_set': bool(DATABASE_URL),
        'counts': counts,
        'missing_columns': missing,
        'admin_roles': {r['label']: r['c'] for r in admin_roles},
        'member_status': {r['label']: r['c'] for r in member_status},
        'message': 'RC3-3 회원관리 DB 상태입니다. ok가 false이면 /api/rc3/member-db/ensure 를 1회 실행하세요.'
    }

@router.get('/api/rc3/member-db/login-logs')
def rc3_member_db_login_logs(limit:int=100, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    limit=max(1, min(int(limit or 100), 500))
    with con() as c:
        rows=c.execute('SELECT id,admin_id,username,success,ip,user_agent,message,created_at FROM login_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return {'ok': True, 'items': [dict(r) for r in rows]}

@router.get('/api/version')
def version():
    return {'app': 'BBLOTTO PRO', 'version': 'V2 STABLE', 'phase': RC_VERSION, 'rc_version': RC_VERSION, 'features': ['server_foundation','members','recommendations','stats100','top3','score_grade','recommendation_history','admin_logs','db_health','cloud_deploy','backup_restore_guard','admin_audit','db_standardization','draw_auto_fetch_fallback','official_cache','ai_engine_v1_0','pair_triple_analysis','reason_based_scoring','member_linked_recommendations','member_linked_win_check','orphan_recommendation_repair','member_detail_message_history','member_detail_winning_history','member_detail_recommendation_hidden'], 'time': now()}

@router.get('/api/rc3-8/health')
def rc38_health(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    snap = rc38_db_health_snapshot()
    required = {'admins':['id','username','password_hash'], 'members':['id','name','status'], 'recommendations':['id','member_id','round_no','numbers','created_at'], 'admin_logs':['id','action','created_at']}
    missing = {t:[col for col in cols if col not in snap['tables'].get(t,{}).get('columns',[])] for t, cols in required.items()}
    snap['ok'] = not any(missing.values())
    snap['missing_required_columns'] = missing
    snap['message'] = 'RC3-8 상태 점검입니다. ok=true이면 핵심 테이블과 컬럼이 준비된 상태입니다.'
    return snap

@router.get('/api/rc3-8/recommendation-summary')
def rc38_recommendation_summary(limit:int=20, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    limit=max(1, min(int(limit or 20), 100))
    with con() as c:
        recent=c.execute('SELECT id,member_id,member_name,round_no,mode,count,avg_score,created_at FROM recommendations ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        by_round=c.execute('SELECT round_no, COUNT(*) c, AVG(avg_score) avg_score FROM recommendations GROUP BY round_no ORDER BY round_no DESC LIMIT 20').fetchall()
        by_member=c.execute('SELECT COALESCE(member_name,"미지정") member_name, COUNT(*) c, MAX(created_at) latest FROM recommendations GROUP BY COALESCE(member_name,"미지정") ORDER BY c DESC, latest DESC LIMIT 20').fetchall()
    return {'ok': True, 'version': RC3_8_VERSION, 'recent':[dict(r) for r in recent], 'by_round':[dict(r) for r in by_round], 'by_member':[dict(r) for r in by_member]}



@router.get('/api/rc6-7/status')
def rc67_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    checks=[]
    with con() as c:
        for table in ['admins','members','recommendations','sms_logs','draws','settings']:
            try:
                cnt=c.execute(f'SELECT COUNT(*) c FROM {table}').fetchone()['c']
                checks.append({'table':table,'ok':True,'count':cnt})
            except Exception as e:
                checks.append({'table':table,'ok':False,'error':str(e)[:200]})
    return {'ok': all(x.get('ok') for x in checks), 'version':'RC6-10_SQL_PERCENT_STABLE', 'db_engine':DB_ENGINE, 'checks':checks, 'time':now()}


@router.get('/')
def login_page(): return FileResponse(FRONT/'login.html')

@router.get('/dashboard')
def dashboard_page(): return FileResponse(FRONT/'index.html')


@router.get('/style.css')
def style_css():
    return FileResponse(FRONT/'style.css', media_type='text/css', headers={'Cache-Control':'no-store, max-age=0'})

@router.get('/app.js')
def app_js():
    return FileResponse(FRONT/'app.js', media_type='application/javascript', headers={'Cache-Control':'no-store, max-age=0'})



@router.get('/api/ui-health')
def ui_health():
    return {'ok': True, 'version': 'STABLE-CORE-1', 'event_owner': 'app.js', 'fallback_file': None, 'single_event_owner': True}

@router.get('/login.js')
def login_js():
    return FileResponse(FRONT/'login.js', media_type='application/javascript')



