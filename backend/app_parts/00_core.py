# Extracted from legacy backend/app.py lines 1-1492.
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import sqlite3, json, random, re, itertools, datetime, secrets, hashlib, hmac, io, csv, collections, shutil, os, urllib.request, urllib.parse, time, threading, logging
from backend.runtime_config import (
    load_runtime_settings,
    validate_startup_environment,
    require_bootstrap_admin_password,
)

RUNTIME_SETTINGS = load_runtime_settings()
validate_startup_environment(RUNTIME_SETTINGS)
APP_ENV = RUNTIME_SETTINGS.app_env
IS_PRODUCTION = RUNTIME_SETTINGS.is_production
BBLOTTO_SECRET_KEY = RUNTIME_SETTINGS.secret_key

BASE = Path(__file__).resolve().parents[1]

# STAGE3: 운영 중 숨겨진 예외를 표준 출력 로그에 남깁니다.
# 기존 기능의 fallback 동작은 유지하되, 원인 추적이 가능하도록 traceback을 기록합니다.
logger = logging.getLogger("bblotto")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(getattr(logging, os.getenv("BBLOTTO_LOG_LEVEL", "INFO").upper(), logging.INFO))
logger.propagate = False

def _log_suppressed_exception(context: str, level: int = logging.WARNING):
    logger.log(level, "suppressed exception: %s", context, exc_info=True)


# PHASE21: 데이터 초기화 방지 / 영구저장 경로 고정
# 우선순위
# 1) BBLOTTO_DB_DIR 환경변수
# 2) Render Disk 권장 마운트 경로 /data
# 3) 로컬 개발용 프로젝트 database 폴더
def resolve_db_dir():
    env_dir = os.getenv('BBLOTTO_DB_DIR', '').strip()
    if env_dir:
        return Path(env_dir)
    render_disk = Path('/data')
    if render_disk.exists() and os.access(str(render_disk), os.W_OK):
        return render_disk / 'bblotto_database'
    return BASE / 'database'

DB_DIR = resolve_db_dir(); DB_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR = Path(os.getenv('BBLOTTO_EXPORT_DIR', str(DB_DIR / 'exports'))); EXPORT_DIR.mkdir(parents=True, exist_ok=True)
DB = DB_DIR / 'bblotto_v34.db'
FRONT = BASE / 'frontend'

RC_VERSION = 'STABLE_CORE_CLEAN_BUILD'
APP_VERSION = 'BBLOTTO V3 STABLE'
app = FastAPI(title=f'{APP_VERSION} {RC_VERSION}', docs_url=None, redoc_url=None, openapi_url=None)
RC3_8_VERSION = 'V2_STABLE_RC3_15'
RC3_9_VERSION = 'V2_STABLE_RC3_15'
RC3_10_VERSION = 'V2_STABLE_RC3_15'
app.mount('/static', StaticFiles(directory=str(FRONT)), name='static')

# RC11.3: 운영 보안 보조 함수
_RC11_MAX_BODY_BYTES = 2 * 1024 * 1024
_RC11_ALLOWED_METHODS_WITH_BODY = {'POST', 'PUT', 'PATCH'}

def _rc113_client_ip(request: Request) -> str:
    # Railway/Render 같은 역방향 프록시 환경에서는 Forwarded 헤더를 우선 사용합니다.
    forwarded = str(request.headers.get('x-forwarded-for', '') or '').split(',')[0].strip()
    if forwarded and len(forwarded) <= 64 and re.fullmatch(r'[0-9a-fA-F:.]+', forwarded):
        return forwarded
    return request.client.host if request.client else 'unknown'

def _rc113_validate_origin(request: Request):
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'} or not request.url.path.startswith('/api/'):
        return
    origin = str(request.headers.get('origin', '') or '').strip()
    if not origin:
        return
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'.rstrip('/')
    forwarded_proto = str(request.headers.get('x-forwarded-proto', '') or '').split(',')[0].strip()
    if forwarded_proto:
        expected = f'{forwarded_proto}://{request.headers.get("host", "")}'.rstrip('/')
    if origin.rstrip('/') != expected:
        raise HTTPException(403, '허용되지 않은 요청 출처입니다.')

def validate_admin_username(username: str) -> str:
    value = str(username or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9._-]{4,40}', value):
        raise HTTPException(400, '관리자 아이디는 영문, 숫자, 점, 밑줄, 하이픈을 사용해 4~40자로 입력해주세요.')
    return value

# RC11: 기본 보안 헤더. 외부 리소스 없이 자체 파일만 사용하는 현재 구조에 맞춘 정책입니다.
@app.middleware('http')
async def rc11_security_headers(request: Request, call_next):
    try:
        _rc113_validate_origin(request)
        if request.method in _RC11_ALLOWED_METHODS_WITH_BODY:
            length = request.headers.get('content-length')
            if length:
                try:
                    if int(length) > _RC11_MAX_BODY_BYTES:
                        raise HTTPException(413, '요청 데이터가 너무 큽니다.')
                except ValueError:
                    raise HTTPException(400, '잘못된 Content-Length입니다.')
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={'ok':False,'error':{'type':'SecurityValidation','status_code':exc.status_code,'message':exc.detail},'path':str(request.url.path),'time':datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    if request.url.scheme == 'https' or str(request.headers.get('x-forwarded-proto','')).lower().startswith('https'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith('/api/') or request.url.path in {'/','/dashboard','/app.js','/login.js','/style.css'}:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# RC11: 로그인 무차별 대입 방지(서버 프로세스 단위). DB 로그와 함께 동작합니다.
_RC11_LOGIN_LOCK = threading.Lock()
_RC11_LOGIN_ATTEMPTS = collections.defaultdict(list)
_RC11_LOGIN_WINDOW_SECONDS = 15 * 60
_RC11_LOGIN_MAX_FAILURES = 7

def _rc11_login_key(request: Request, username: str) -> str:
    ip = _rc113_client_ip(request)
    return f'{ip}|{str(username or "").strip().lower()[:80]}'

def _rc11_check_login_limit(request: Request, username: str):
    key = _rc11_login_key(request, username)
    current = time.time()
    with _RC11_LOGIN_LOCK:
        recent = [t for t in _RC11_LOGIN_ATTEMPTS.get(key, []) if current - t < _RC11_LOGIN_WINDOW_SECONDS]
        _RC11_LOGIN_ATTEMPTS[key] = recent
        if len(recent) >= _RC11_LOGIN_MAX_FAILURES:
            retry = max(1, int(_RC11_LOGIN_WINDOW_SECONDS - (current - recent[0])))
            raise HTTPException(429, f'로그인 시도가 너무 많습니다. 약 {max(1, retry // 60)}분 후 다시 시도해주세요.')

def _rc11_record_login_failure(request: Request, username: str):
    key = _rc11_login_key(request, username)
    with _RC11_LOGIN_LOCK:
        _RC11_LOGIN_ATTEMPTS[key].append(time.time())

def _rc11_clear_login_failures(request: Request, username: str):
    key = _rc11_login_key(request, username)
    with _RC11_LOGIN_LOCK:
        _RC11_LOGIN_ATTEMPTS.pop(key, None)


# RC2 Sprint 6: 표준 오류 응답 핸들러
@app.exception_handler(HTTPException)
def rc2_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        'ok': False,
        'error': {'type': 'HTTPException', 'status_code': exc.status_code, 'message': exc.detail},
        'path': str(request.url.path),
        'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.exception_handler(Exception)
def rc2_unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled request error path=%s method=%s", request.url.path, request.method, exc_info=exc)
    return JSONResponse(status_code=500, content={
        'ok': False,
        'error': {'type': exc.__class__.__name__, 'message': '서버 처리 중 오류가 발생했습니다.'},
        'path': str(request.url.path),
        'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

DEFAULT_DRAWS = [
 (1230,'2026.06.27',[3,8,9,22,28,42],45),(1229,'2026.06.20',[12,13,29,34,37,42],16),(1228,'2026.06.13',[24,29,30,31,35,44],1),
 (1227,'2026.06.06',[1,14,16,34,41,44],13),(1226,'2026.05.30',[4,6,13,17,26,28],41),(1225,'2026.05.23',[8,9,19,25,41,42],33),
 (1224,'2026.05.16',[9,18,21,27,44,45],28),(1223,'2026.05.09',[16,18,20,32,33,39],26),(1222,'2026.05.02',[4,11,17,22,32,41],34),
 (1221,'2026.04.25',[6,13,18,28,30,36],9),(1220,'2026.04.18',[2,22,25,28,34,43],16),(1219,'2026.04.11',[1,2,15,28,39,45],31),
]
try:
    from .data import DRAWS as FULL_DRAWS
    DEFAULT_DRAWS = [(int(x['r']), x.get('d',''), list(x.get('n',[])), int(x.get('b',0))) for x in FULL_DRAWS]
except Exception:
    _log_suppressed_exception("00_core.py:179")

PRIZE_TABLE = {'1등': 2000000000, '2등': 50000000, '3등': 1500000, '4등': 50000, '5등': 5000, '낙첨': 0}
COST_PER_COMBO = 1000

# PHASE30: PostgreSQL 영구저장 지원
# Render Free에서 SQLite 파일이 초기화되는 문제를 해결하기 위해 DATABASE_URL이 있으면 PostgreSQL을 사용합니다.
# DATABASE_URL이 없으면 기존처럼 SQLite를 사용하므로 로컬 실행도 그대로 가능합니다.
def _normalize_database_url(url: str) -> str:
    url = (url or '').strip()
    if not url or url.startswith('${{'):
        return ''
    if url.startswith('postgres://'):
        return 'postgresql://' + url[len('postgres://'):]
    return url

def _build_database_url_from_pg_vars() -> str:
    host = os.getenv('PGHOST', '').strip()
    port = os.getenv('PGPORT', '5432').strip() or '5432'
    user = os.getenv('PGUSER', '').strip() or os.getenv('POSTGRES_USER', '').strip()
    password = os.getenv('PGPASSWORD', '').strip() or os.getenv('POSTGRES_PASSWORD', '').strip()
    dbname = os.getenv('PGDATABASE', '').strip() or os.getenv('POSTGRES_DB', '').strip()
    if host and user and dbname:
        return f"postgresql://{urllib.parse.quote(user)}:{urllib.parse.quote(password)}@{host}:{port}/{dbname}"
    return ''

# RC3 Database Migration: Railway/PostgreSQL 자동 감지
# 우선순위: DATABASE_URL > POSTGRES_URL > PGHOST/PGUSER/PGDATABASE 조합 > SQLite
DATABASE_URL = _normalize_database_url(
    os.getenv('DATABASE_URL', '')
    or os.getenv('POSTGRES_URL', '')
    or _build_database_url_from_pg_vars()
)
DB_ENGINE = 'postgresql' if DATABASE_URL else 'sqlite'

class CompatRow:
    def __init__(self, columns, values):
        self._columns = list(columns or [])
        self._values = list(values or [])
        self._map = {str(k): self._values[i] for i, k in enumerate(self._columns) if i < len(self._values)}
    def __getitem__(self, key):
        if isinstance(key, int): return self._values[key]
        return self._map.get(key)
    def get(self, key, default=None): return self._map.get(key, default)
    def keys(self): return self._map.keys()
    def items(self): return self._map.items()
    def __iter__(self): return iter(self._map)
    def __len__(self): return len(self._values)
    def __dict__(self): return dict(self._map)

class PgCursorCompat:
    def __init__(self, conn):
        self.conn = conn
        self.cur = conn._conn.cursor()
        self.rowcount = -1
        self.lastrowid = None
        self._last_rows = None
        self._last_columns = None
    def _convert_sql(self, sql):
        s = str(sql)
        s = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', s, flags=re.I)
        s = s.replace('INSERT OR IGNORE INTO', 'INSERT INTO')
        s = s.replace('INSERT OR REPLACE INTO', 'INSERT INTO')
        s = s.replace('DEFAULT ""', "DEFAULT ''")
        s = s.replace('DEFAULT "관리자"', "DEFAULT '관리자'")
        s = s.replace('DEFAULT "전체권한"', "DEFAULT '전체권한'")
        s = s.replace('DEFAULT "일반"', "DEFAULT '일반'")
        s = s.replace('DEFAULT "활성"', "DEFAULT '활성'")
        s = s.replace('DEFAULT "보통"', "DEFAULT '보통'")
        s = s.replace('DEFAULT "직접등록"', "DEFAULT '직접등록'")
        s = s.replace('DEFAULT "balanced"', "DEFAULT 'balanced'")
        s = s.replace('DEFAULT "[]"', "DEFAULT '[]'")
        s = s.replace('DEFAULT "{}"', "DEFAULT '{}'")
        s = s.replace('DEFAULT "mock"', "DEFAULT 'mock'")
        s = s.replace('DEFAULT "saved"', "DEFAULT 'saved'")
        s = s.replace('COALESCE(NULLIF(name,""),"관리자")', "COALESCE(NULLIF(name,''),'관리자')")
        s = s.replace('COALESCE(status,"활성")', "COALESCE(status,'활성')")
        s = s.replace('COALESCE(priority,"보통")', "COALESCE(priority,'보통')")
        s = s.replace('COALESCE(grade,"일반")', "COALESCE(grade,'일반')")
        s = s.replace('COALESCE(last_contact_at,"")', "COALESCE(last_contact_at,'')")
        s = s.replace('COALESCE(source,"직접등록")', "COALESCE(source,'직접등록')")
        for lit in ['활성','VIP','다이아','높음','최우선','보통','일반','직접등록','manual','manual_auto','starter100','balanced']:
            s = s.replace(f'"{lit}"', f"'{lit}'")
        s = s.replace('COALESCE(source,"")', "COALESCE(source,'')")
        s = s.replace('COALESCE(priority,"")', "COALESCE(priority,'')")
        s = re.sub(r'\s+COLLATE\s+NOCASE', '', s, flags=re.I)
        s = s.replace('COALESCE(last_contact_at,"")=""', "COALESCE(last_contact_at,'')=''")
        # sqlite의 ? 파라미터를 psycopg2의 %s로 변환한다.
        # 단, SQL 안의 LIKE '%super%' 같은 리터럴에 들어있는 %s를
        # 파라미터로 착각하지 않도록 ?를 먼저 안전 토큰으로 바꾼다.
        pg_param_token = '__BBLOTTO_PG_PARAM__'
        out=[]; in_str=False; quote=''
        for ch in s:
            if ch in ("'", '"'):
                if not in_str:
                    in_str=True; quote=ch
                elif quote==ch:
                    in_str=False; quote=''
            if ch=='?' and not in_str:
                out.append(pg_param_token)
            else:
                out.append(ch)
        s=''.join(out)
        # psycopg2는 SQL 문자열 안의 %도 포맷 기호로 해석한다.
        # 실제 파라미터 토큰은 보호하고, 나머지 %만 %%로 이스케이프한다.
        if '%' in s:
            s = s.replace('%', '%%')
        s = s.replace(pg_param_token, '%s')
        # PostgreSQL upsert/ignore 호환
        if re.match(r'\s*INSERT\s+INTO\s+draws\s*\(', s, re.I) and 'ON CONFLICT' not in s:
            s += ' ON CONFLICT (round_no) DO UPDATE SET draw_date=EXCLUDED.draw_date, numbers=EXCLUDED.numbers, bonus=EXCLUDED.bonus, source=EXCLUDED.source, updated_at=EXCLUDED.updated_at'
        elif re.match(r'\s*INSERT\s+INTO\s+settings\s*\(', s, re.I) and 'ON CONFLICT' not in s:
            s += ' ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at'
        elif re.match(r'\s*INSERT\s+INTO\s+admins\s*\(', s, re.I) and 'ON CONFLICT' not in s and 'RETURNING' not in s:
            # 기본 관리자 생성 또는 관리자 추가에서 username 중복 방지
            if 'password_hash' in s and 'VALUES' in s:
                s += ' ON CONFLICT (username) DO NOTHING'
        return s
    def _table_info_rows(self, table):
        q = "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position"
        self.cur.execute(q, (table,))
        rows = self.cur.fetchall()
        # sqlite PRAGMA table_info 호환: r[1]이 컬럼명
        self._last_columns = ['cid','name','type','notnull','dflt_value','pk']
        self._last_rows = [CompatRow(self._last_columns, [i, r[0], '', 0, None, 0]) for i, r in enumerate(rows)]
        return self
    def execute(self, sql, params=None):
        params = tuple(params or ())
        raw = str(sql).strip()
        m = re.match(r'PRAGMA\s+table_info\(([^)]+)\)', raw, re.I)
        if m:
            return self._table_info_rows(m.group(1).strip().strip('"'))
        s = self._convert_sql(sql)
        # lastrowid가 필요한 주요 INSERT는 RETURNING id 추가
        if re.match(r'\s*INSERT\s+INTO\s+(members|recommendations|sms_logs)\s*\(', s, re.I) and 'RETURNING' not in s and 'ON CONFLICT' not in s:
            s += ' RETURNING id'
        try:
            self.cur.execute(s, params)
        except Exception as e:
            # ALTER TABLE ADD COLUMN 중복은 안전하게 무시
            if raw.upper().startswith('ALTER TABLE') and ('already exists' in str(e).lower() or 'duplicate column' in str(e).lower()):
                self.conn._conn.rollback(); return self
            raise
        self.rowcount = self.cur.rowcount
        self._last_rows = None; self._last_columns = None; self.lastrowid = None
        if self.cur.description:
            cols = [d[0] for d in self.cur.description]
            rows = self.cur.fetchall()
            self._last_columns = cols
            self._last_rows = [CompatRow(cols, r) for r in rows]
            if len(rows)==1 and 'id' in cols:
                try: self.lastrowid = self._last_rows[0]['id']
                except Exception: pass
        return self
    def fetchone(self):
        if not self._last_rows: return None
        return self._last_rows[0]
    def fetchall(self): return self._last_rows or []

class PgConnCompat:
    def __init__(self):
        import psycopg2
        self._conn = psycopg2.connect(DATABASE_URL)
        self._conn.autocommit = False
    def cursor(self): return PgCursorCompat(self)
    def execute(self, sql, params=None):
        cur = self.cursor(); return cur.execute(sql, params)
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        if exc_type: self.rollback()
        else: self.commit()
        self.close()

def con():
    if DB_ENGINE == 'postgresql':
        return PgConnCompat()
    c = sqlite3.connect(DB, timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('PRAGMA foreign_keys=ON')
    return c

def now(): return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def normalize_date_text(value, fallback=''):
    text = str(value or '').strip()
    if not text:
        return fallback
    # HTML date input(YYYY-MM-DD) 또는 기존 created_at(YYYY-MM-DD HH:MM:SS) 모두 허용
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    m = re.match(r'^(\d{4})[./](\d{1,2})[./](\d{1,2})', text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return fallback

def add_months_date(date_text, months=12):
    base = normalize_date_text(date_text, datetime.datetime.now().strftime('%Y-%m-%d'))
    try:
        d = datetime.datetime.strptime(base, '%Y-%m-%d').date()
        months = int(months or 12)
        if months not in (6, 12, 24, 36):
            months = 12
        y = d.year + ((d.month - 1 + months) // 12)
        m = ((d.month - 1 + months) % 12) + 1
        # 대상 월의 마지막 일자보다 큰 날은 말일로 보정합니다.
        import calendar
        day = min(d.day, calendar.monthrange(y, m)[1])
        return datetime.date(y, m, day).strftime('%Y-%m-%d')
    except Exception:
        return ''

def add_one_year_date(date_text):
    return add_months_date(date_text, 12)


def clean_template_text(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        obj = value
    else:
        text = str(value)
        for _ in range(3):
            t = text.strip()
            if not ((t.startswith('{') and t.endswith('}')) or (t.startswith('[') and t.endswith(']'))):
                break
            try:
                obj = json.loads(t)
            except Exception:
                break
            extracted = clean_template_text(obj)
            if not extracted or extracted == text:
                break
            text = extracted
        return text.replace('\\n', '\n').replace('\\t', '\t')
    if isinstance(obj, list):
        return '\n'.join(clean_template_text(x) for x in obj if clean_template_text(x))
    for key in ('body','value','text','message','sms_template','template','content'):
        if key in obj and obj[key] is not None:
            return clean_template_text(obj[key])
    return ''

def hash_password(password: str, salt: str|None=None, iterations: int=260000) -> str:
    salt = salt or secrets.token_hex(16)
    iterations = max(120000, int(iterations or 260000))
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
    return f'pbkdf2_sha256${iterations}${salt}${dk.hex()}'

def verify_password(password: str, stored: str) -> bool:
    try:
        stored = str(stored or '')
        # RC11 방식: 알고리즘$반복횟수$salt$digest
        if stored.startswith('pbkdf2_sha256$'):
            parts = stored.split('$')
            if len(parts) == 4:
                _, iterations, salt, digest = parts
                calc = hash_password(password, salt, int(iterations)).split('$', 3)[3]
                return hmac.compare_digest(calc, digest)
            # RC10 이하 방식: 알고리즘$salt$digest (120,000회)
            if len(parts) == 3:
                _, salt, digest = parts
                dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 120000).hex()
                return hmac.compare_digest(dk, digest)
        # 구버전 호환: salt$digest
        if '$' in stored:
            salt, digest = stored.split('$', 1)
            dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 120000).hex()
            return hmac.compare_digest(dk, digest)
        # 아주 초기 DB만 1회 로그인 허용하며 성공 즉시 RC11 해시로 교체합니다.
        return bool(stored) and hmac.compare_digest(stored, password)
    except Exception:
        return False

def password_needs_rehash(stored: str) -> bool:
    try:
        parts = str(stored or '').split('$')
        return not (len(parts) == 4 and parts[0] == 'pbkdf2_sha256' and int(parts[1]) >= 260000)
    except Exception:
        return True

def validate_password_strength(password: str):
    value = str(password or '')
    if len(value) < 10:
        raise HTTPException(400, '비밀번호는 10자 이상으로 설정해주세요.')
    groups = sum(bool(re.search(pattern, value)) for pattern in (r'[A-Z]', r'[a-z]', r'\d', r'[^A-Za-z0-9]'))
    if groups < 3:
        raise HTTPException(400, '비밀번호에는 영문 대·소문자, 숫자, 특수문자 중 3종류 이상을 사용해주세요.')

def parse_nums(value):
    if value is None: return []
    if isinstance(value, (list, tuple)):
        nums = [int(x) for x in value if 1 <= int(x) <= 45]
    else:
        text = str(value)
        try:
            data = json.loads(text)
            if isinstance(data, list):
                nums = [int(x) for x in data if 1 <= int(x) <= 45]
            else:
                nums = [int(x) for x in re.findall(r'\d+', text) if 1 <= int(x) <= 45]
        except Exception:
            nums = [int(x) for x in re.findall(r'\d+', text) if 1 <= int(x) <= 45]
    return sorted(list(dict.fromkeys(nums)))[:6]

def table_cols(c, table):
    try: return [r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()]
    except Exception: return []


# === RC3-15: 당첨번호 회차 무결성 보조 ===
def _rc315_expected_round_and_completed(now_dt=None):
    """현재 한국시간 기준 추천 회차와 실제 추첨 완료 회차를 분리합니다.
    예: 1232회 추천 기간이어도 추첨 전이면 완료 회차는 1231회입니다.
    """
    try:
        dt = now_dt or (datetime.datetime.utcnow() + datetime.timedelta(hours=9))
        first = datetime.date(2002, 12, 7)
        today = dt.date() if isinstance(dt, datetime.datetime) else dt
        expected = int(((today - first).days // 7) + 1) if today >= first else 1
        draw_dt = datetime.datetime.combine(first + datetime.timedelta(days=(expected-1)*7), datetime.time(20, 35))
        completed = expected if dt >= draw_dt else max(1, expected - 1)
        return expected, completed
    except Exception:
        return 0, 0


def _rc315_clean_future_draws_in_conn(c):
    """추첨 전/미래 회차에 잘못 저장된 당첨번호를 제거합니다.
    RC3-15 핵심: 추천 회차(다음 회차)와 당첨 확인 회차(최근 추첨 완료 회차)를 분리합니다.
    """
    expected, completed = _rc315_expected_round_and_completed()
    removed = 0
    suspicious = []
    try:
        rows = c.execute('SELECT round_no,numbers,bonus,source,updated_at FROM draws WHERE round_no>? ORDER BY round_no DESC', (completed,)).fetchall()
        for row in rows:
            suspicious.append(dict(row) if hasattr(row, 'keys') else {'round_no': row[0]})
        c.execute('DELETE FROM draws WHERE round_no>?', (completed,))
        removed = int(getattr(c, 'rowcount', 0) or 0)
    except Exception:
        removed = 0
    return {'expected_round': expected, 'completed_round': completed, 'removed': removed, 'suspicious': suspicious}


def _rc315_validate_draw_payload(round_no, numbers, bonus, allow_completed_only=True):
    nums = parse_nums(numbers)
    if len(nums) != 6:
        raise HTTPException(400, '당첨번호 6개가 필요합니다.')
    if len(set(nums)) != 6 or any(n < 1 or n > 45 for n in nums):
        raise HTTPException(400, '당첨번호는 1~45 사이의 서로 다른 6개 숫자여야 합니다.')
    try:
        b = int(bonus)
    except Exception:
        b = 0
    if not (1 <= b <= 45):
        raise HTTPException(400, '보너스 번호는 1~45 사이여야 합니다.')
    if b in nums:
        raise HTTPException(400, '보너스 번호는 당첨번호 6개와 달라야 합니다.')
    expected, completed = _rc315_expected_round_and_completed()
    r = int(round_no or 0)
    if allow_completed_only and completed and r > completed:
        raise HTTPException(400, f'{r}회는 아직 추첨 완료 전입니다. 현재 저장 가능한 최신 당첨번호는 {completed}회입니다.')
    return r, nums, b, expected, completed

def init_db():
    with con() as c:
        if DB_ENGINE == 'sqlite':
            # WAL allows reads while another request writes; NORMAL avoids excessive fsync cost.
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA synchronous=NORMAL')
        c.execute('CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, name TEXT DEFAULT "관리자", password_hash TEXT NOT NULL, is_active INTEGER DEFAULT 1, created_at TEXT, last_login_at TEXT)')
        # V34 Priority4: 관리자 운영 컬럼을 기존 DB에 안전하게 추가
        admin_cols = table_cols(c, 'admins')
        for col, ddl in {
            'name':'TEXT DEFAULT "관리자"',
            'is_active':'INTEGER DEFAULT 1',
            'last_login_at':'TEXT DEFAULT ""',
            'role':'TEXT DEFAULT "전체권한"',
            'memo':'TEXT DEFAULT ""',
            'updated_at':'TEXT DEFAULT ""',
            'last_ip':'TEXT DEFAULT ""',
            'phone':'TEXT DEFAULT ""'
        }.items():
            if col not in admin_cols:
                c.execute(f'ALTER TABLE admins ADD COLUMN {col} {ddl}')
        c.execute('UPDATE admins SET name=COALESCE(NULLIF(name,""),"관리자"), is_active=COALESCE(is_active,1)')
        c.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, admin_id INTEGER, created_at TEXT, expires_at TEXT)')
        session_cols = table_cols(c, 'sessions')
        for col, ddl in {
            'last_seen_at':'TEXT DEFAULT ""',
            'ip':'TEXT DEFAULT ""',
            'user_agent':'TEXT DEFAULT ""'
        }.items():
            if col not in session_cols:
                c.execute(f'ALTER TABLE sessions ADD COLUMN {col} {ddl}')
        c.execute('CREATE TABLE IF NOT EXISTS admin_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT, created_at TEXT)')
        # RC3-3: 로그인 이력은 관리자 활동 로그와 별도 테이블로 영구 저장합니다.
        c.execute('CREATE TABLE IF NOT EXISTS login_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER DEFAULT 0, username TEXT DEFAULT "", success INTEGER DEFAULT 0, ip TEXT DEFAULT "", user_agent TEXT DEFAULT "", message TEXT DEFAULT "", created_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS backup_history(id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, reason TEXT DEFAULT "manual", size_bytes INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT DEFAULT "", grade TEXT DEFAULT "일반", memo TEXT DEFAULT "", created_by INTEGER, created_at TEXT)')
        c.execute("CREATE TABLE IF NOT EXISTS member_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, note TEXT DEFAULT '', note_type TEXT DEFAULT '상담', created_by INTEGER DEFAULT 0, created_by_name TEXT DEFAULT '', created_at TEXT)")
        # V34 Final Member Phase3: 기존 DB와 충돌 없이 필요한 컬럼만 추가
        member_cols = table_cols(c, 'members')
        if 'status' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN status TEXT DEFAULT "활성"')
        if 'last_contact_at' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN last_contact_at TEXT DEFAULT ""')
        if 'updated_at' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN updated_at TEXT DEFAULT ""')
        if 'priority' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN priority TEXT DEFAULT "보통"')
        if 'source' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN source TEXT DEFAULT "직접등록"')
        if 'created_by' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN created_by INTEGER DEFAULT 0')
        if 'preferred_count' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN preferred_count INTEGER DEFAULT 10')
        if 'contract_end_at' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN contract_end_at TEXT DEFAULT ""')
        if 'contract_months' not in member_cols:
            c.execute('ALTER TABLE members ADD COLUMN contract_months INTEGER DEFAULT 12')
        c.execute('CREATE TABLE IF NOT EXISTS recommendations(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, member_name TEXT, round_no INTEGER, mode TEXT, count INTEGER, numbers TEXT, analysis TEXT, sms TEXT, created_by INTEGER, created_at TEXT)')
        # V40 Phase1: 기존 Render SQLite가 오래된 스키마여도 자동 복구합니다.
        rec_cols = table_cols(c, 'recommendations')
        for col, ddl in {
            'member_id':'INTEGER',
            'member_name':'TEXT DEFAULT ""',
            'round_no':'INTEGER DEFAULT 0',
            'mode':'TEXT DEFAULT "balanced"',
            'count':'INTEGER DEFAULT 0',
            'numbers':'TEXT DEFAULT "[]"',
            'analysis':'TEXT DEFAULT ""',
            'sms':'TEXT DEFAULT ""',
            'created_by':'INTEGER DEFAULT 0',
            'created_at':'TEXT DEFAULT ""',
            'avg_score':'REAL DEFAULT 0',
            'engine_json':'TEXT DEFAULT "{}"',
            'details_json':'TEXT DEFAULT "[]"',
            'explicit_saved':'INTEGER DEFAULT 0'
        }.items():
            if col not in rec_cols:
                c.execute(f'ALTER TABLE recommendations ADD COLUMN {col} {ddl}')
        c.execute('CREATE TABLE IF NOT EXISTS sms_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, member_name TEXT, round_no INTEGER, body TEXT, combos TEXT DEFAULT "[]", created_by INTEGER, created_at TEXT)')
        sms_cols = table_cols(c, 'sms_logs')
        for col, ddl in {
            'phone':'TEXT DEFAULT ""',
            'provider':'TEXT DEFAULT "mock"',
            'status':'TEXT DEFAULT "saved"',
            'result_message':'TEXT DEFAULT ""',
            'sent_at':'TEXT DEFAULT ""'
        }.items():
            if col not in sms_cols:
                c.execute(f'ALTER TABLE sms_logs ADD COLUMN {col} {ddl}')
        c.execute('CREATE TABLE IF NOT EXISTS winning_checks(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, member_name TEXT, round_no INTEGER, target_numbers TEXT, win_numbers TEXT, bonus INTEGER, match_count INTEGER, bonus_match INTEGER, rank TEXT, prize INTEGER DEFAULT 0, cost INTEGER DEFAULT 1000, profit INTEGER DEFAULT 0, roi REAL DEFAULT 0, created_by INTEGER, created_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS draws(round_no INTEGER PRIMARY KEY, draw_date TEXT DEFAULT "", numbers TEXT, bonus INTEGER, source TEXT DEFAULT "manual", updated_at TEXT)')
        draw_cols = table_cols(c, 'draws')
        if 'source' not in draw_cols:
            c.execute('ALTER TABLE draws ADD COLUMN source TEXT DEFAULT "manual"')
        if 'updated_at' not in draw_cols:
            c.execute('ALTER TABLE draws ADD COLUMN updated_at TEXT DEFAULT ""')
        c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)')
        if c.execute('SELECT COUNT(*) FROM admins').fetchone()[0] == 0:
            init_username = RUNTIME_SETTINGS.admin_username
            init_password = require_bootstrap_admin_password(RUNTIME_SETTINGS)
            if not init_password:
                init_password = secrets.token_urlsafe(18)
                logger.warning(
                    'development bootstrap administrator password generated username=%s password=%s',
                    init_username, init_password
                )
            c.execute('INSERT INTO admins(username,name,password_hash,is_active,created_at) VALUES(?,?,?,?,?)', (init_username,'대표 관리자',hash_password(init_password),1,now()))
        # 기본 당첨번호 DB는 비어 있을 때만 넣는 방식이 아니라, 누락 회차를 항상 보강합니다.
        # 그래서 기존 DB에 20회차만 남아 있어도 최근 100회 통계가 바로 동작합니다.
        for r,d,n,b in DEFAULT_DRAWS:
            c.execute('INSERT OR IGNORE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)', (r,d,json.dumps(n),b,'starter100',now()))
        default_sms = '안녕하세요 {회원명}님, BBLOTTO입니다.\n{회차}회차 추천번호 및 이번회차 분석입니다.\n\n[이번회차 핵심 분석]\n{분석}\n\n[추천번호]\n{추천번호}\n\n좋은 결과 있으시길 바랍니다.'
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_template', default_sms, now()))
        current_sms = c.execute('SELECT value FROM settings WHERE key=?', ('sms_template',)).fetchone()
        if current_sms:
            cleaned = clean_template_text(current_sms['value'])
            if cleaned and cleaned != current_sms['value']:
                c.execute('UPDATE settings SET value=?, updated_at=? WHERE key=?', (cleaned, now(), 'sms_template'))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_provider', 'mock', now()))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_sender', '', now()))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_api_url', '', now()))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_api_key', '', now()))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('session_timeout_minutes', '600', now()))
        # PHASE25: 기존 DB에 480분 이하로 남아 있던 자동 로그아웃 값을 10시간(600분)으로 보정
        try:
            old_timeout = c.execute('SELECT value FROM settings WHERE key=?', ('session_timeout_minutes',)).fetchone()
            old_val = int((old_timeout or {'value':'600'})['value'] or 600)
            if old_val < 600:
                c.execute('UPDATE settings SET value=?, updated_at=? WHERE key=?', ('600', now(), 'session_timeout_minutes'))
        except Exception:
            c.execute('UPDATE settings SET value=?, updated_at=? WHERE key=?', ('600', now(), 'session_timeout_minutes'))
        c.execute('INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('auto_logout_warning_minutes', '5', now()))
        # Frequently used lookup/sort indexes. CREATE IF NOT EXISTS is safe on every boot.
        for index_sql in (
            'CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)',
            'CREATE INDEX IF NOT EXISTS idx_sessions_admin_created ON sessions(admin_id, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)',
            'CREATE INDEX IF NOT EXISTS idx_members_admin_created ON members(created_by, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_members_name ON members(name)',
            'CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone)',
            'CREATE INDEX IF NOT EXISTS idx_recommendations_member_created ON recommendations(member_id, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_winning_checks_member_round ON winning_checks(member_id, round_no)',
            'CREATE INDEX IF NOT EXISTS idx_sms_logs_member_created ON sms_logs(member_id, created_at)',
            'CREATE INDEX IF NOT EXISTS idx_draws_round ON draws(round_no)',
        ):
            try:
                c.execute(index_sql)
            except Exception:
                _log_suppressed_exception('00_core.py:create_index')
        # RC3-15: 운영 DB에 1232회처럼 추첨 전 회차가 잘못 저장되어 있으면 시작 시 자동 정리
        _rc315_clean_future_draws_in_conn(c)
        c.commit()

def log_action(admin, action, detail='', request: Request|None=None):
    ip = _rc113_client_ip(request) if request else ''
    with con() as c:
        c.execute('INSERT INTO admin_logs(admin_id,username,action,detail,ip,created_at) VALUES(?,?,?,?,?,?)', (admin.get('id') if admin else None, admin.get('username') if admin else '', action, detail, ip, now()))
        c.commit()

def log_login_event(admin_id=0, username='', success=0, message='', request: Request|None=None):
    """RC3-3: 로그인 성공/실패 이력을 PostgreSQL/SQLite에 공통 저장합니다."""
    ip = _rc113_client_ip(request) if request else ''
    ua = request.headers.get('user-agent','')[:240] if request else ''
    try:
        with con() as c:
            c.execute('INSERT INTO login_logs(admin_id,username,success,ip,user_agent,message,created_at) VALUES(?,?,?,?,?,?,?)', (int(admin_id or 0), username or '', 1 if success else 0, ip, ua, message or '', now()))
            c.commit()
    except Exception:
        # 로그인 자체가 실패하지 않도록 로그 저장 오류는 무시합니다.
        _log_suppressed_exception("00_core.py:689")


# RC3-4: PostgreSQL/SQLite 공통 운영 백업 테이블 목록
RC3_BACKUP_TABLES = [
    'admins', 'members', 'settings', 'draws', 'recommendations', 'winning_checks',
    'sms_logs', 'admin_logs', 'login_logs', 'backup_history', 'sessions',
    'engine_runs', 'dashboard_snapshots'
]


def _safe_backup_filename(ext='json', label='BBLOTTO_RC3_BACKUP'):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    ext = str(ext or 'json').lstrip('.')
    return f'{label}_{stamp}.{ext}'


def _json_default(value):
    try:
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
    except Exception:
        _log_suppressed_exception("00_core.py:711")
    return str(value)


def _backup_export_json(reason='manual', admin=None):
    """PostgreSQL/SQLite 공통 JSON 백업 생성. DB 엔진과 무관하게 모든 운영 테이블을 보관합니다."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_backup_filename('json')
    dest = EXPORT_DIR / filename
    payload = {
        'app': 'BBLOTTO PRO',
        'version': 'RC3-4',
        'engine': DB_ENGINE,
        'created_at': now(),
        'reason': reason,
        'tables': {},
    }
    with con() as c:
        for table in RC3_BACKUP_TABLES:
            try:
                rows = c.execute(f'SELECT * FROM {table}').fetchall()
                payload['tables'][table] = [dict(r) for r in rows]
            except Exception:
                payload['tables'][table] = []
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding='utf-8')
    size = dest.stat().st_size if dest.exists() else 0
    try:
        with con() as c:
            c.execute('INSERT INTO backup_history(filename,reason,size_bytes,created_by,created_at) VALUES(?,?,?,?,?)', (filename, reason, size, admin.get('id') if admin else None, now()))
            c.commit()
    except Exception:
        _log_suppressed_exception("00_core.py:742")
    return {'filename': filename, 'format': 'json', 'engine': DB_ENGINE, 'reason': reason, 'size_bytes': size, 'created_at': now()}


def create_db_backup(reason='manual', admin=None):
    """RC3-4 운영 백업.
    - PostgreSQL: JSON 덤프 파일 생성
    - SQLite: 기존 .db 복사 + JSON 백업 생성 가능 구조 유지
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if DB_ENGINE == 'postgresql':
        return _backup_export_json(reason, admin)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'BBLOTTO_V34_BACKUP_{stamp}.db'
    dest = EXPORT_DIR / filename
    shutil.copy2(DB, dest)
    size = dest.stat().st_size if dest.exists() else 0
    try:
        with con() as c:
            c.execute('INSERT INTO backup_history(filename,reason,size_bytes,created_by,created_at) VALUES(?,?,?,?,?)', (filename, reason, size, admin.get('id') if admin else None, now()))
            c.commit()
    except Exception:
        _log_suppressed_exception("00_core.py:764")
    return {'filename': filename, 'format': 'sqlite_db', 'engine': DB_ENGINE, 'reason': reason, 'size_bytes': size, 'created_at': now()}


def _validate_backup_json(path: Path):
    if not path.exists() or path.suffix.lower() != '.json':
        raise HTTPException(400, 'JSON 백업 파일만 복원할 수 있습니다.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise HTTPException(400, '백업 JSON 파일을 읽을 수 없습니다.')
    if not isinstance(data, dict) or not isinstance(data.get('tables'), dict):
        raise HTTPException(400, 'BBLOTTO 백업 형식이 아닙니다.')
    return data


def _restore_json_backup(path: Path, admin=None, request: Request|None=None):
    data = _validate_backup_json(path)
    tables = data.get('tables') or {}
    restore_order = [t for t in reversed(RC3_BACKUP_TABLES) if t in tables]
    inserted = {}
    with con() as c:
        for table in restore_order:
            try:
                c.execute(f'DELETE FROM {table}')
            except Exception:
                _log_suppressed_exception("00_core.py:790")
        for table in RC3_BACKUP_TABLES:
            rows = tables.get(table) or []
            if not rows:
                inserted[table] = 0
                continue
            cols = table_cols(c, table)
            allowed = [col for col in rows[0].keys() if col in cols]
            if not allowed:
                inserted[table] = 0
                continue
            marks = ','.join(['?'] * len(allowed))
            col_sql = ','.join(allowed)
            count = 0
            for row in rows:
                vals = [row.get(col) for col in allowed]
                try:
                    c.execute(f'INSERT INTO {table}({col_sql}) VALUES({marks})', vals)
                    count += 1
                except Exception:
                    _log_suppressed_exception("00_core.py:810")
            inserted[table] = count
        c.commit()
    try:
        log_action(admin or {}, 'RESTORE_BACKUP', f'복원 완료: {path.name}', request)
    except Exception:
        _log_suppressed_exception("00_core.py:816")
    return {'ok': True, 'restored_from': path.name, 'engine': DB_ENGINE, 'inserted': inserted, 'restored_at': now()}

def ensure_daily_backup():
    """하루 1회 자동 백업. 실행 시 충돌 없이 보관만 합니다."""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        with con() as c:
            r = c.execute('SELECT COUNT(*) c FROM backup_history WHERE reason=? AND created_at LIKE ?', ('auto_daily', today+'%')).fetchone()
        if not r or r['c'] == 0:
            create_db_backup('auto_daily', None)
    except Exception:
        _log_suppressed_exception("00_core.py:828")

init_db()
ensure_daily_backup()

from .repositories.session_repository import (
    delete_session as _repo_delete_session,
    get_active_admin_by_token as _repo_get_active_admin_by_token,
    touch_session_if_due as _repo_touch_session_if_due,
)

def current_admin(authorization: str|None):
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(401, '로그인이 필요합니다.')
    token = authorization.split(' ',1)[1].strip()
    row = _repo_get_active_admin_by_token(con, token)
    if not row:
        raise HTTPException(401, '세션이 만료되었습니다.')
    current_time = now()
    if row['expires_at'] < current_time:
        _repo_delete_session(con, token)
        raise HTTPException(401, '세션이 만료되었습니다.')
    try:
        # 여러 화면 API가 동시에 호출돼도 세션 쓰기는 최대 60초에 한 번만 수행합니다.
        _repo_touch_session_if_due(con, token, row['last_seen_at'] if 'last_seen_at' in row.keys() else '', current_time, 60)
    except Exception:
        _log_suppressed_exception("00_core.py:session_touch")
    return dict(row)

def require_admin(authorization: str|None = Header(default=None)):
    return current_admin(authorization)

def require_admin_any(authorization: str|None = None, token: str|None = None):
    if authorization:
        return current_admin(authorization)
    if token:
        return current_admin('Bearer ' + token)
    raise HTTPException(401, '로그인이 필요합니다.')

def is_super_admin(admin: dict|sqlite3.Row|None):
    if not admin:
        return False
    if hasattr(admin, 'get'):
        username = str(admin.get('username','') or '').strip().lower()
        role = str(admin.get('role','') or '').replace(' ', '').lower()
        name = str(admin.get('name','') or '').replace(' ', '').lower()
    else:
        keys = admin.keys()
        username = str(admin['username'] if 'username' in keys else '').strip().lower()
        role = str(admin['role'] if 'role' in keys else '').replace(' ', '').lower()
        name = str(admin['name'] if 'name' in keys else '').replace(' ', '').lower()
    return (username == 'admin' or '최고관리자' in role or '대표관리자' in role or '전체권한' in role or role in {'대표','최고','전체','전체권한'} or 'super' in role or 'owner' in role or '최고관리자' in name or '대표관리자' in name or '전체권한' in name or name in {'대표','최고','전체','전체권한'})

def require_super_admin(admin):
    if not is_super_admin(admin):
        raise HTTPException(403, '최고 관리자만 처리할 수 있습니다.')
    return admin


def member_scope_condition(admin, table_alias: str = ''):
    """RC4-4: 최고관리자는 전체 회원, 일반관리자는 본인이 등록한 회원만 조회/관리합니다."""
    if is_super_admin(admin):
        return '', []
    prefix = (table_alias + '.') if table_alias else ''
    return f'COALESCE({prefix}created_by,0)=?', [int(admin.get('id') or 0)]

def assert_member_access(c, admin, member_id: int):
    """회원 단건 작업 권한 확인."""
    if is_super_admin(admin):
        row = c.execute('SELECT id,name,created_by FROM members WHERE id=?', (member_id,)).fetchone()
    else:
        row = c.execute('SELECT id,name,created_by FROM members WHERE id=? AND COALESCE(created_by,0)=?', (member_id, int(admin.get('id') or 0))).fetchone()
    if not row:
        raise HTTPException(404, '관리 가능한 회원을 찾을 수 없습니다.')
    return row


# ===== PHASE19: 회차 자동 확인 / 속도 최적화 보조 =====
LOTTO_FIRST_DRAW_DATE = datetime.date(2002, 12, 7)  # 1회 추첨일
LOTTO_DRAW_WEEKDAY = 5  # Saturday
LOTTO_DRAW_HOUR = 20
LOTTO_DRAW_MINUTE = 35

def kst_now():
    """서버 위치와 무관하게 한국 시간 기준으로 회차를 계산합니다."""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

def expected_lotto_round(dt=None):
    """오늘 기준으로 관리해야 할 로또 회차를 계산합니다.
    토요일 추첨 전에도 오늘 추첨될 회차를 반환하므로 추천번호/당첨확인 회차가 밀리지 않습니다.
    """
    dt = dt or kst_now()
    today = dt.date() if isinstance(dt, datetime.datetime) else dt
    if today < LOTTO_FIRST_DRAW_DATE:
        return 1
    return int(((today - LOTTO_FIRST_DRAW_DATE).days // 7) + 1)

def draw_date_for_round(round_no:int):
    try:
        d = LOTTO_FIRST_DRAW_DATE + datetime.timedelta(days=(int(round_no)-1)*7)
        return d.strftime('%Y.%m.%d')
    except Exception:
        return ''

def draw_status_for_round(round_no:int):
    """scheduled: 추첨 전, pending: 추첨 후 번호 미저장, saved: DB 저장 완료"""
    now_kst = kst_now()
    r = int(round_no or 0)
    expected = expected_lotto_round(now_kst)
    draw_dt = datetime.datetime.combine(LOTTO_FIRST_DRAW_DATE + datetime.timedelta(days=(r-1)*7), datetime.time(LOTTO_DRAW_HOUR, LOTTO_DRAW_MINUTE)) if r > 0 else now_kst
    if r > expected:
        return 'future'
    if r == expected and now_kst < draw_dt:
        return 'scheduled'
    return 'pending'

# RC3-10: 동행복권 API가 일시 차단/지연될 때 운영이 멈추지 않도록
# 검증된 최신 회차를 보조 캐시로 둡니다. 최신 회차가 추가되면 여기만 보강해도 자동확인이 복구됩니다.
OFFICIAL_DRAW_FALLBACKS = {
    1231: {'round_no': 1231, 'draw_date': '2026.07.04', 'numbers': [4, 13, 14, 18, 31, 38], 'bonus': 15, 'source': 'official_cache'},
}


def _normalize_official_payload(data, round_no:int, source:str):
    if not data or data.get('returnValue') != 'success':
        return None
    nums = [int(data.get(f'drwtNo{i}', 0) or 0) for i in range(1, 7)]
    bonus = int(data.get('bnusNo', 0) or 0)
    if len(set(nums)) == 6 and all(1 <= n <= 45 for n in nums) and 1 <= bonus <= 45 and bonus not in nums:
        return {
            'round_no': int(data.get('drwNo') or round_no),
            'draw_date': str(data.get('drwNoDate') or draw_date_for_round(round_no)).replace('-', '.'),
            'numbers': sorted(nums),
            'bonus': bonus,
            'source': source,
        }
    return None


def _fallback_draw(round_no:int):
    cached = OFFICIAL_DRAW_FALLBACKS.get(int(round_no))
    if not cached:
        return None
    # 추첨 전 회차에 캐시가 잘못 적용되는 것을 방지합니다.
    if draw_status_for_round(int(round_no)) == 'scheduled':
        return None
    return dict(cached)


def fetch_official_lotto(round_no:int):
    """동행복권 공개 조회 JSON을 안전하게 시도합니다.
    RC3-10: 공식 API 실패 시 검증 캐시로 한 번 더 복구합니다.
    """
    r = int(round_no)
    urls = [
        'https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=' + urllib.parse.quote(str(r)),
        'http://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=' + urllib.parse.quote(str(r)),
    ]
    last_error = ''
    for idx, url in enumerate(urls):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; BBLOTTO-RC3-10/1.0)',
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://www.dhlottery.co.kr/',
            })
            with urllib.request.urlopen(req, timeout=7) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            normalized = _normalize_official_payload(data, r, 'dhlottery' if idx == 0 else 'dhlottery_http')
            if normalized:
                return normalized
            last_error = '공식 API 응답에 당첨번호가 없습니다.'
        except Exception as e:
            last_error = str(e)[:180]
            continue
    cached = _fallback_draw(r)
    if cached:
        cached['fetch_error'] = last_error
        return cached
    return None

def save_draw_if_missing(draw):
    if not draw:
        return None
    try:
        r, nums, bonus, expected, completed = _rc315_validate_draw_payload(draw.get('round_no'), draw.get('numbers', []), draw.get('bonus', 0), allow_completed_only=True)
        draw['round_no'] = r
        draw['numbers'] = nums
        draw['bonus'] = bonus
        with con() as c:
            old = c.execute('SELECT round_no FROM draws WHERE round_no=?', (r,)).fetchone()
            if not old:
                c.execute('INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)', (r, draw.get('draw_date',''), json.dumps(nums), bonus, draw.get('source','official'), now()))
                c.commit()
        return draw
    except HTTPException:
        return None
    except Exception:
        return None

def get_draw(round_no:int):
    with con() as c:
        r = c.execute('SELECT * FROM draws WHERE round_no=?', (round_no,)).fetchone()
    if not r: return None
    return {'round_no': r['round_no'], 'draw_date': r['draw_date'], 'numbers': parse_nums(r['numbers']), 'bonus': r['bonus']}

def resolve_draw_for_check(round_no:int|None=None, allow_fetch:bool=True):
    """당첨확인 화면용 회차/당첨번호를 자동 판정합니다."""
    expected = expected_lotto_round()
    r = int(round_no or expected)
    if r <= 0:
        r = expected
    status = draw_status_for_round(r)
    draw = get_draw(r)
    auto_fetched = False
    if not draw and allow_fetch and status == 'pending':
        fetched = fetch_official_lotto(r)
        if fetched:
            draw = save_draw_if_missing(fetched)
            auto_fetched = True
    if draw:
        return {
            'round_no': int(r), 'expected_round': int(expected), 'draw_date': draw.get('draw_date') or draw_date_for_round(r),
            'status': 'saved', 'can_check': True, 'numbers': draw.get('numbers') or [], 'bonus': int(draw.get('bonus') or 0),
            'source': draw.get('source','db'), 'auto_fetched': auto_fetched,
            'message': f'{r}회 당첨번호가 자동 확인되었습니다.' + ((' 공식 API/보조 캐시로 저장했습니다.' if draw.get('source') == 'official_cache' else ' 동행복권 공개 데이터로 저장했습니다.') if auto_fetched else '')
        }
    if status == 'scheduled':
        return {
            'round_no': int(r), 'expected_round': int(expected), 'draw_date': draw_date_for_round(r),
            'status': 'scheduled', 'can_check': False, 'numbers': [], 'bonus': 0, 'source': '', 'auto_fetched': False,
            'message': f'{r}회는 오늘 추첨 예정 회차입니다. 추첨 전이라 당첨번호는 아직 자동 입력하지 않습니다.'
        }
    if status == 'future':
        return {
            'round_no': int(r), 'expected_round': int(expected), 'draw_date': draw_date_for_round(r),
            'status': 'future', 'can_check': False, 'numbers': [], 'bonus': 0, 'source': '', 'auto_fetched': False,
            'message': f'{r}회는 아직 추첨 예정 전 회차입니다.'
        }
    return {
        'round_no': int(r), 'expected_round': int(expected), 'draw_date': draw_date_for_round(r),
        'status': 'pending', 'can_check': False, 'numbers': [], 'bonus': 0, 'source': '', 'auto_fetched': False,
        'message': f'{r}회 추첨 시간이 지났지만 당첨번호가 아직 공개/저장되지 않았습니다. 잠시 후 다시 확인하거나 수동 입력하세요.'
    }

def rank_result(combo, wins, bonus):
    combo = parse_nums(combo); wins = parse_nums(wins)
    matched = sorted(set(combo)&set(wins)); m=len(matched); bm = int(bonus in combo)
    rank = '낙첨'
    if m == 6: rank='1등'
    elif m == 5 and bm: rank='2등'
    elif m == 5: rank='3등'
    elif m == 4: rank='4등'
    elif m == 3: rank='5등'
    prize = PRIZE_TABLE[rank]; cost = COST_PER_COMBO; profit = prize-cost; roi = round((profit/cost)*100, 2) if cost else 0
    return {'combo':combo,'matched':matched,'match_count':m,'bonus_match':bool(bm),'rank':rank,'prize':prize,'cost':cost,'profit':profit,'roi':roi}

def all_draw_nums(limit=100):
    with con() as c:
        rows = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT ?', (limit,)).fetchall()
    nums=[]
    for r in rows: nums.extend(parse_nums(r['numbers']))
    return nums

def make_combos(count=10, fixed='', excluded='', mode='balanced'):
    nums = all_draw_nums(100); freq={n:nums.count(n) for n in range(1,46)}
    hot = sorted(range(1,46), key=lambda n:(-freq[n],n))[:15]
    cold = sorted(range(1,46), key=lambda n:(freq[n],n))[:15]
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    combos=[]; tries=0
    while len(combos)<max(1,min(50,count)) and tries<5000:
        tries+=1
        combo=set(fixed_set)
        if mode=='aggressive': base=random.sample(hot, min(3,len(hot))) + random.sample(pool, min(10,len(pool)))
        elif mode=='conservative': base=random.sample(cold, min(2,len(cold))) + random.sample(pool, min(12,len(pool)))
        else: base=random.sample(hot, min(2,len(hot))) + random.sample(cold, min(2,len(cold))) + random.sample(pool, min(12,len(pool)))
        for n in base:
            if n not in excluded_set and len(combo)<6: combo.add(n)
        while len(combo)<6: combo.add(random.choice(pool))
        arr=sorted(combo)
        odd=sum(n%2 for n in arr)
        sections=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        if odd in [2,3,4] and max(sections)<=4 and arr not in combos: combos.append(arr)
    return combos



def latest_stats(limit=100):
    """V40 Phase1 통계 엔진: 최근 10/30/50/100회 흐름, 미출현, 동반출현, 끝수/구간/홀짝/합계를 계산합니다."""
    with con() as c:
        rows = c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT ?', (max(10, int(limit or 100)),)).fetchall()
    draws=[]
    for r in rows:
        nums=parse_nums(r['numbers'])
        if len(nums)==6:
            draws.append({'round_no':int(r['round_no']), 'draw_date':r['draw_date'] or '', 'numbers':nums, 'bonus':int(r['bonus'] or 0)})
    if not draws:
        draws=[{'round_no':r,'draw_date':d,'numbers':n,'bonus':b} for r,d,n,b in DEFAULT_DRAWS if len(n)==6]
    windows={10:draws[:10], 30:draws[:30], 50:draws[:50], 100:draws[:100]}
    freq_by_window={}
    for w,ds in windows.items():
        f={n:0 for n in range(1,46)}
        for d in ds:
            for n in d['numbers']:
                f[n]+=1
        freq_by_window[w]=f
    freq=freq_by_window[100]
    last_seen={n:999 for n in range(1,46)}
    for idx,d in enumerate(draws[:100]):
        for n in d['numbers']:
            if last_seen[n] == 999:
                last_seen[n]=idx
    pair_counts=collections.Counter()
    for d in draws[:100]:
        for a,b in itertools.combinations(d['numbers'],2):
            pair_counts[tuple(sorted((a,b)))] += 1
    end_counts={i:0 for i in range(10)}
    zone_counts={'1~15':0,'16~30':0,'31~45':0}
    odd_total=0; sums=[]
    for d in draws[:100]:
        sums.append(sum(d['numbers']))
        for n in d['numbers']:
            end_counts[n%10]+=1
            odd_total += n%2
            if n<=15: zone_counts['1~15']+=1
            elif n<=30: zone_counts['16~30']+=1
            else: zone_counts['31~45']+=1
    avg100=sum(freq.values())/45 if freq else 0
    hot=sorted(range(1,46), key=lambda n:(-(freq_by_window[30][n]*1.7 + freq_by_window[100][n]*0.7 + freq_by_window[10][n]*2.0), last_seen[n], n))[:12]
    cold=sorted(range(1,46), key=lambda n:(freq_by_window[100][n], -last_seen[n], n))[:12]
    overdue=sorted(range(1,46), key=lambda n:(last_seen[n], -freq_by_window[100][n], n), reverse=True)[:12]
    mid=sorted(range(1,46), key=lambda n:(abs(freq_by_window[100][n]-avg100), last_seen[n], n))[:15]
    top_pairs=[{'pair':list(p),'count':c} for p,c in pair_counts.most_common(12)]
    recent_numbers=set()
    for d in draws[:3]: recent_numbers.update(d['numbers'])
    return {
        'draws':draws,'freq':freq,'freq10':freq_by_window[10],'freq30':freq_by_window[30],'freq50':freq_by_window[50],'freq100':freq_by_window[100],
        'last_seen':last_seen,'hot':hot,'mid':mid,'cold':cold,'overdue':overdue,'top_pairs':top_pairs,'pair_counts':pair_counts,
        'end_counts':end_counts,'zone_counts':zone_counts,'odd_ratio':odd_total/(max(1,len(draws[:100])*6)),
        'sum_avg':round(sum(sums)/len(sums),1) if sums else 0,'recent_numbers':recent_numbers,
        'latest_round':draws[0]['round_no'] if draws else 1230
    }

def ac_value(combo):
    arr=sorted(combo)
    diffs={b-a for a,b in itertools.combinations(arr,2)}
    return max(0, len(diffs)-5)

def combo_score(combo, st):
    """0~100 AI 점수. 당첨 보장 점수가 아니라 통계 균형/분산 품질 점수입니다."""
    combo=sorted(parse_nums(combo));
    if len(combo)!=6: return 0
    f10,f30,f100=st['freq10'],st['freq30'],st['freq100']; last=st['last_seen']; pairs=st['pair_counts']
    total=sum(combo); odd=sum(n%2 for n in combo); even=6-odd
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    cons=sum(1 for a,b in zip(combo,combo[1:]) if b-a==1)
    ends=len(set(n%10 for n in combo)); ac=ac_value(combo)
    # 기본 패턴 점수
    score=42.0
    score += {3:13,2:10,4:10,1:3,5:3,0:-8,6:-8}.get(odd,0)
    score += 13 if 105<=total<=175 else (8 if 95<=total<=190 else -10)
    score += 12 if max(zones)<=3 and min(zones)>=1 else (5 if max(zones)<=4 else -8)
    score += 7 if 5<=ac<=10 else (3 if 4<=ac<=11 else -4)
    score += 6 if ends>=5 else (3 if ends==4 else -4)
    score += 5 if cons<=1 else (-3 if cons==2 else -9)
    # 최근 흐름 점수: 과열수는 과하게 몰리지 않게, 중간/보강수를 같이 반영
    hot_hit=len(set(combo)&set(st['hot'][:10])); cold_hit=len(set(combo)&set(st['cold'][:10])); overdue_hit=len(set(combo)&set(st['overdue'][:10]))
    score += min(10, hot_hit*3.0) + min(7, cold_hit*2.1) + min(8, overdue_hit*2.2)
    if hot_hit>4: score -= 7
    if len(set(combo)&st['recent_numbers'])>=4: score -= 5
    # 동반출현은 1~3개 정도만 가산, 과도한 과거쌍 몰림은 감점
    pair_sum=sum(pairs.get(tuple(sorted((a,b))),0) for a,b in itertools.combinations(combo,2))
    strong_pairs=sum(1 for a,b in itertools.combinations(combo,2) if pairs.get(tuple(sorted((a,b))),0)>=4)
    score += min(10, pair_sum/4.0) + min(5, strong_pairs*1.5)
    if strong_pairs>5: score -= 5
    # 10/30/100 가중치 평균이 너무 한쪽으로 쏠리지 않게
    heat=sum(f10[n]*2.0 + f30[n]*1.1 + f100[n]*0.35 for n in combo)
    if 22 <= heat <= 55: score += 6
    elif heat > 70: score -= 8
    else: score += 2
    return round(max(35, min(99.7, score)), 1)

def tags_for_combo(combo, st):
    combo=sorted(combo); s=set(combo); tags=[]
    if len(s & set(st['hot'][:10]))>=2: tags.append('최근핵심')
    if len(s & set(st['overdue'][:10]))>=1: tags.append('미출현보강')
    if len(s & set(st['cold'][:10]))>=1: tags.append('저출현반등')
    if sum(n%2 for n in combo) in (2,3,4): tags.append('홀짝균형')
    zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    if max(zones)<=3 and min(zones)>=1: tags.append('구간분산')
    if ac_value(combo) in range(5,11): tags.append('AC안정')
    pairs=st['pair_counts']
    if any(pairs.get(tuple(sorted((a,b))),0)>=4 for a,b in itertools.combinations(combo,2)): tags.append('동반출현')
    return tags[:5] or ['균형형']

def combo_detail(combo, st):
    combo=sorted(combo)
    odd=sum(n%2 for n in combo); zones=[sum(n<=15 for n in combo),sum(16<=n<=30 for n in combo),sum(n>=31 for n in combo)]
    pair_hits=[]
    for a,b in itertools.combinations(combo,2):
        cnt=st['pair_counts'].get(tuple(sorted((a,b))),0)
        if cnt>=3: pair_hits.append({'pair':[a,b], 'count':cnt})
    pair_hits=sorted(pair_hits, key=lambda x:-x['count'])[:3]
    return {'numbers':combo,'score':combo_score(combo,st),'tags':tags_for_combo(combo,st),'sum':sum(combo),'odd':odd,'even':6-odd,'zones':zones,'ac':ac_value(combo),'pair_hits':pair_hits}

def _weighted_pick(candidates, weights, k):
    picked=[]; pool=list(candidates); w=list(weights)
    for _ in range(min(k,len(pool))):
        total=sum(max(0.01,x) for x in w)
        r=random.random()*total; acc=0; idx=0
        for i,x in enumerate(w):
            acc += max(0.01,x)
            if acc>=r:
                idx=i; break
        picked.append(pool.pop(idx)); w.pop(idx)
    return picked

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    st=latest_stats(120)
    fixed_set=set(parse_nums(fixed)); excluded_set=set(parse_nums(excluded))
    fixed_set={n for n in fixed_set if n not in excluded_set}
    if len(fixed_set)>6: fixed_set=set(sorted(fixed_set)[:6])
    pool=[n for n in range(1,46) if n not in excluded_set and n not in fixed_set]
    target=max(1,min(50,int(count or 10)))
    if len(pool)+len(fixed_set)<6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')
    past={tuple(d['numbers']) for d in st['draws']}
    f10,f30,f100,last=st['freq10'],st['freq30'],st['freq100'],st['last_seen']
    weights={}
    for n in pool:
        hot = f30[n]*1.4 + f10[n]*2.0 + f100[n]*0.35
        cold = max(0, 7-f100[n]) + min(8,last[n])*0.35
        mid = 6 - min(6, abs(f100[n] - (sum(f100.values())/45)))
        if mode=='aggressive': weights[n]=1 + hot*1.35 + cold*0.45 + mid*0.5
        elif mode=='conservative': weights[n]=1 + hot*0.65 + cold*1.25 + mid*0.9
        else: weights[n]=1 + hot*0.95 + cold*0.9 + mid*0.75
        # 직전 3회 과다 반영은 낮춤
        if n in st['recent_numbers']: weights[n]*=0.72
    candidates=[]; seen=set(); tries=0
    needed=max(target*75, 900)
    while len(candidates)<needed and tries<40000:
        tries+=1
        need=6-len(fixed_set)
        nums=set(fixed_set)
        picked=_weighted_pick(pool, [weights[n] for n in pool], need)
        nums.update(picked)
        arr=tuple(sorted(nums))
        if len(arr)!=6 or arr in seen or arr in past: continue
        odd=sum(n%2 for n in arr); total=sum(arr); zones=[sum(n<=15 for n in arr),sum(16<=n<=30 for n in arr),sum(n>=31 for n in arr)]
        cons=sum(1 for a,b in zip(arr,arr[1:]) if b-a==1)
        if odd not in (2,3,4): continue
        if not (90<=total<=195): continue
        if max(zones)>4 or 0 in zones: continue
        if cons>2: continue
        if len(set(n%10 for n in arr))<3: continue
        seen.add(arr)
        candidates.append((combo_score(arr,st), list(arr)))
    candidates=sorted(candidates, key=lambda x:(-x[0], x[1]))
    selected=[]
    for score, combo in candidates:
        # 최종 10개는 서로 너무 비슷하지 않게 분산
        if all(len(set(combo)&set(prev))<=4 for prev in selected):
            selected.append(combo)
        if len(selected)>=target: break
    if len(selected)<target:
        for score, combo in candidates:
            if combo not in selected:
                selected.append(combo)
            if len(selected)>=target: break
    details=[combo_detail(c, st) for c in selected[:target]]
    return selected[:target], details, st

def _engine_summary(details, st):
    if not details: return {'avg_score':0,'combo_count':0}
    scores=[d.get('score',0) for d in details]
    all_nums=[n for d in details for n in d.get('numbers',[])]
    freq=collections.Counter(all_nums)
    return {
        'avg_score':round(sum(scores)/len(scores),1),
        'max_score':max(scores),
        'combo_count':len(details),
        'latest_round':st.get('latest_round'),
        'hot':st.get('hot',[])[:8],
        'cold':st.get('cold',[])[:8],
        'overdue':st.get('overdue',[])[:8],
        'top_used':[n for n,_ in freq.most_common(8)],
        'top_pairs':st.get('top_pairs',[])[:5]
    }

def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    """생성된 추천 조합과 실제 최근 100회 통계를 함께 사용해 매번 다른 4~5줄 분석을 만듭니다."""
    details=details or []
    engine=_engine_summary(details, st)
    top_scores=sorted(details, key=lambda x:-x.get('score',0))[:3]
    used_nums=engine.get('top_used',[])[:6]
    hot=[n for n in st.get('hot',[])[:10] if n in used_nums] or st.get('hot',[])[:4]
    overdue=[n for n in st.get('overdue',[])[:10] if n in used_nums] or st.get('overdue',[])[:4]
    cold=[n for n in st.get('cold',[])[:10] if n in used_nums] or st.get('cold',[])[:4]
    pair_text=', '.join([f"{p['pair'][0]}-{p['pair'][1]}({p['count']}회)" for p in st.get('top_pairs',[])[:3]]) or '동반출현 데이터 보강 중'
    best = top_scores[0] if top_scores else {}
    mode_name={'balanced':'균형형','conservative':'보강형','aggressive':'공격형'}.get(mode, mode or '균형형')
    variants=[
        f"{round_no}회차는 최근 10/30/100회 흐름을 합산해 {mode_name} 기준으로 재분석했습니다.",
        f"이번 생성은 직전 과열 흐름을 낮추고 최근 100회 누적 통계를 함께 반영했습니다.",
        f"{round_no}회차 분석은 출현빈도, 미출현 간격, 동반출현, AC값을 동시에 적용했습니다."
    ]
    line1=random.choice(variants)
    line2=random.choice([
        f"핵심 후보는 {', '.join(map(str,hot[:5]))}번이며, 미출현 보강 후보는 {', '.join(map(str,overdue[:5]))}번입니다.",
        f"최근 강한 흐름은 {', '.join(map(str,hot[:5]))}번, 저출현 반등 후보는 {', '.join(map(str,cold[:5]))}번 중심으로 잡았습니다.",
        f"번호 풀은 HOT {', '.join(map(str,hot[:4]))}번과 보강 {', '.join(map(str,overdue[:4]))}번을 섞어 구성했습니다."
    ])
    if best:
        line3=f"대표 조합은 합계 {best.get('sum')} / AC {best.get('ac')} / 홀짝 {best.get('odd')}:{best.get('even')} 기준이며 AI점수는 {best.get('score')}점입니다."
    else:
        line3=f"평균 AI점수는 {engine.get('avg_score',0)}점이며 과도한 중복과 구간 쏠림을 줄였습니다."
    line4=random.choice([
        f"동반출현 참고 흐름은 {pair_text}이며, 조합 간 중복을 낮춰 분산형으로 정리했습니다.",
        f"동반출현은 {pair_text} 흐름을 참고했고, 끝수와 구간이 한쪽으로 몰리지 않게 제한했습니다.",
        f"상위 동반 흐름({pair_text})은 참고만 하고, 동일 패턴 반복은 줄였습니다."
    ])
    line5=f"분석 갱신시각: {now()}"
    return '\n'.join([line1,line2,line3,line4,line5])

def build_sms(member_name, round_no, combos, analysis, details):
    name=member_name or '회원'
    best=sorted(details or [], key=lambda x:-x.get('score',0))[:1]
    best_line=''
    if best:
        b=best[0]
        best_line=f"대표 조합 포인트: 합계 {b.get('sum')} / AC {b.get('ac')} / 홀짝 {b.get('odd')}:{b.get('even')} / AI점수 {b.get('score')}점"
    return '\n'.join([
        f'안녕하세요 {name}님, BBLOTTO입니다.',
        f'{round_no}회차 추천번호와 이번 회차 분석을 안내드립니다.',
        '[추천번호]',
        *[f'{i+1}. '+', '.join(map(str,c)) for i,c in enumerate(combos)],
        '[분석요약]',
        analysis,
        best_line,
        '좋은 결과 있으시길 바랍니다.'
    ]).strip()


# RC3-7: 추천결과 화면/저장 안정화를 위한 상세정보 보강
def rc37_grade(score):
    try: s=float(score or 0)
    except Exception: s=0
    if s >= 97: return '1등'
    if s >= 94: return '2등'
    return '일반'

def rc37_star(score):
    try: s=float(score or 0)
    except Exception: s=0
    if s >= 95: return '★★★★★'
    if s >= 90: return '★★★★☆'
    if s >= 85: return '★★★★'
    return '★★★☆'

def rc37_enrich_details(combos, details):
    enriched=[]
    details=list(details or [])
    for i, combo in enumerate(combos or []):
        d=dict(details[i]) if i < len(details) and isinstance(details[i], dict) else {}
        score=d.get('score') or d.get('ai_score') or d.get('vip_score') or 0
        try: score=round(float(score),1)
        except Exception: score=0
        nums=[int(n) for n in combo]
        odd=sum(n%2 for n in nums)
        zones=[sum(n<=15 for n in nums), sum(16<=n<=30 for n in nums), sum(n>=31 for n in nums)]
        d.update({
            'rank': i+1,
            'score': score,
            'star': d.get('star') or rc37_star(score),
            'grade': d.get('grade') or rc37_grade(score),
            'sum': d.get('sum') or sum(nums),
            'odd': d.get('odd') if d.get('odd') is not None else odd,
            'even': d.get('even') if d.get('even') is not None else 6-odd,
            'zones': d.get('zones') or zones,
        })
        tags=list(d.get('tags') or d.get('reasons') or [])
        tags.append(d['grade'])
        tags.append(d['star'])
        d['tags']=list(dict.fromkeys(str(t) for t in tags if t))[:5]
        enriched.append(d)
    return enriched

def rc37_top3(combos, details):
    rows=[]
    for combo, d in sorted(zip(combos or [], details or []), key=lambda x: -float(x[1].get('score') or 0))[:3]:
        rows.append({'numbers': combo, 'score': d.get('score',0), 'star': d.get('star',''), 'grade': d.get('grade','STANDARD')})
    return rows


# RC3-8: 실사용 안정화 / 추천 포트폴리오 품질 보강
def rc38_overlap(a, b):
    try:
        return len(set(int(x) for x in a) & set(int(x) for x in b))
    except Exception:
        return 0

def rc38_portfolio_reorder(combos, details, max_overlap=3):
    """점수 순위만 따르지 않고 조합 간 중복을 줄여 실사용 추천 포트폴리오로 재정렬합니다."""
    combos = [list(map(int, c)) for c in (combos or [])]
    details = list(details or [])
    rows = []
    for i, combo in enumerate(combos):
        d = dict(details[i]) if i < len(details) and isinstance(details[i], dict) else {}
        try:
            score = float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0)
        except Exception:
            score = 0.0
        rows.append({'idx': i, 'combo': combo, 'detail': d, 'score': score})
    rows.sort(key=lambda x: (-x['score'], sum(x['combo']), x['combo']))
    selected, rest = [], []
    for row in rows:
        if not selected or all(rc38_overlap(row['combo'], s['combo']) <= max_overlap for s in selected):
            selected.append(row)
        else:
            rest.append(row)
    selected.extend(rest)
    new_combos = [r['combo'] for r in selected]
    new_details = [r['detail'] for r in selected]
    # 화면 순위와 실제 저장 순위를 일치시킵니다.
    for i, d in enumerate(new_details):
        d['rank'] = i + 1
    return new_combos, new_details

def rc38_generation_report(combos, details, safe_round, safe_mode):
    scores=[]
    for d in details or []:
        try: scores.append(float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0))
        except Exception: pass
    overlap_count=0
    max_overlap=0
    for i in range(len(combos or [])):
        for j in range(i+1, len(combos or [])):
            ov=rc38_overlap(combos[i], combos[j]); max_overlap=max(max_overlap, ov)
            if ov >= 4: overlap_count += 1
    flat=[int(n) for c in combos or [] for n in c]
    zone=[sum(1<=n<=15 for n in flat), sum(16<=n<=30 for n in flat), sum(31<=n<=45 for n in flat)]
    odd=sum(n%2 for n in flat)
    total=len(flat) or 1
    return {
        'rc_version': RC3_8_VERSION,
        'round_no': safe_round,
        'mode': safe_mode,
        'combo_count': len(combos or []),
        'avg_score': round(sum(scores)/len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'max_overlap': max_overlap,
        'high_overlap_pairs': overlap_count,
        'zone_distribution': zone,
        'odd_even_total': {'odd': odd, 'even': total-odd},
        'quality_message': 'RC3-8 포트폴리오 보정: 고득점 조합을 우선하되 조합 간 중복과 구간 쏠림을 줄였습니다.'
    }

def rc38_db_health_snapshot():
    tables = ['admins','members','recommendations','sms_logs','winning_checks','admin_logs','login_logs','settings']
    out = {'version': RC3_8_VERSION, 'db_engine': DB_ENGINE, 'database_url_set': bool(DATABASE_URL), 'tables': {}, 'db_path': str(DB) if DB_ENGINE == 'sqlite' else 'postgresql'}
    with con() as c:
        for t in tables:
            try:
                out['tables'][t] = {'count': c.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'], 'columns': table_cols(c, t)}
            except Exception as e:
                out['tables'][t] = {'error': str(e)[:160], 'columns': []}
    return out

class LoginReq(BaseModel): username:str='admin'; password:str
class AdminReq(BaseModel): username:str; name:str='관리자'; password:str; role:str='전체권한'; memo:str=''
class AdminUpdateReq(BaseModel): name:str|None=None; password:str|None=None; role:str|None=None; memo:str|None=None; is_active:int|None=None
class MyAccountReq(BaseModel): name:str|None=None; phone:str|None=None; memo:str|None=None; current_password:str|None=None; new_password:str|None=None
class PasswordReq(BaseModel): password:str
class MemberReq(BaseModel): name:str; phone:str=''; grade:str='일반'; memo:str=''; status:str='활성'; priority:str='보통'; source:str='직접등록'; preferred_count:int=10; created_by:int|None=None; created_at:str|None=None; contract_months:int|None=12; contract_end_at:str|None=None
class MemberStatusReq(BaseModel): status:str; memo:str|None=None
class MemberMemoReq(BaseModel): memo:str=''
class MemberNoteReq(BaseModel): note:str; note_type:str='상담'
class MemberBulkStatusReq(BaseModel): member_ids:list[int]; status:str
class GenerateReq(BaseModel): member_id:int|None=None; round_no:int=1232; count:int=10; mode:str='balanced'; fixed:str=''; excluded:str=''; exclude:str='' # exclude는 기존 프론트 호환용
class SaveRecommendationReq(BaseModel): member_id:int|None=None; member_name:str=''; round_no:int; mode:str='balanced'; combos:list[list[int]]=[]; analysis:str=''; sms:str=''; details:list[dict]=[]; engine:dict={}
class SmsReq(BaseModel): member_id:int|None=None; member_name:str=''; phone:str=''; round_no:int; body:str; combos:list[list[int]]=[]; send_now:bool=False
class WinReq(BaseModel): round_no:int; win_numbers:list[int]=[]; bonus:int=0; combos:list[list[int]]=[]; member_id:int|None=None; member_name:str=''
class DrawReq(BaseModel): round_no:int; draw_date:str=''; numbers:list[int]; bonus:int
class AutoWinReq(BaseModel): round_no:int; winning:str|list[int]=''; bonus:int=0; draw_date:str=''
class SettingReq(BaseModel): key:str; value:str


