# Extracted from legacy backend/app.py lines 6942-7879.
@app.get('/api/rc6-11/status')
def rc6_11_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC6-11_MEMBER_QUERY_REAL_FIX', 'engine': DB_ENGINE, 'admin': admin.get('username')}

# ===================== RC7-1: MEMBER PERSONALIZED AI ENGINE V2 =====================
# 회원별 시드(회원ID/이름/회차/조합)를 분석 문구에 반영하여
# 같은 회차 CSV에서도 회원별 추천번호·요약이 반복되지 않도록 보강합니다.
RC71_ENGINE_VERSION = 'RC7-1_MEMBER_PERSONALIZED_AI_ENGINE_V2'

def _rc71_seed(*parts):
    try:
        import hashlib
        raw = '|'.join(str(p or '') for p in parts)
        return int(hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12], 16)
    except Exception:
        return 0

def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    details = details or []
    engine = _engine_summary(details, st)
    member_id = st.get('member_id') or 0
    member_name = st.get('member_name') or ''
    grade = engine.get('member_grade') or rc45_grade_label(st.get('member_grade'))
    combos = [d.get('numbers', []) for d in details if d.get('numbers')]
    flat = [int(n) for c in combos for n in c if str(n).isdigit()]
    best = sorted(details, key=lambda x: -float(x.get('score') or 0))[:3]
    top_nums=[]
    for d in best:
        for n in d.get('numbers', []):
            if n not in top_nums:
                top_nums.append(n)
    hot = (st.get('hot300') or st.get('hot') or [])[:8]
    overdue = (st.get('overdue300') or st.get('overdue') or [])[:8]
    mode_name = {'balanced': '균형형', 'aggressive': '공격형', 'conservative': '안정형'}.get(mode, mode or '균형형')
    core_text = ', '.join(map(str, top_nums[:6])) if top_nums else '주요 후보군'
    hot_text = ', '.join(map(str, hot[:4])) if hot else '최근 흐름 번호'
    sub_text = ', '.join(map(str, overdue[:4])) if overdue else '보강 후보 번호'
    odd = sum(1 for n in flat if n % 2 == 1); even = len(flat) - odd
    low = sum(1 for n in flat if 1 <= n <= 15); mid = sum(1 for n in flat if 16 <= n <= 30); high = sum(1 for n in flat if 31 <= n <= 45)
    seed = _rc71_seed(round_no, member_id, member_name, mode, grade, sum(flat), core_text)
    def pick(arr, salt=0):
        return arr[(seed + salt) % len(arr)]
    openers = [
        f'{round_no}회차는 {mode_name} 기준으로 최근 흐름과 누적 데이터를 함께 비교했습니다.',
        f'{round_no}회차는 회원별 추천 이력과 번호 분포를 나누어 조합을 선별했습니다.',
        f'이번 회차는 최근 강세 구간과 보강 후보를 함께 반영해 맞춤형으로 구성했습니다.',
        f'{round_no}회차는 특정 번호대 편중을 줄이고 조합별 차이를 확보하는 방향으로 정리했습니다.',
        f'이번 추천은 최근 출현 흐름, 끝수, 구간, 홀짝 균형을 함께 점검했습니다.',
    ]
    middles = [
        f'핵심 후보는 {core_text} 중심이며, {hot_text} 흐름을 일부 반영했습니다.',
        f'최근 흐름 번호({hot_text})와 보강 후보({sub_text})를 나누어 배치했습니다.',
        f'조합 간 번호 중복을 줄이고 {core_text} 후보군의 분산도를 높였습니다.',
        f'장기 보강 후보({sub_text})를 함께 넣어 단순 고빈도 조합을 피했습니다.',
        '최근 반복된 패턴은 일부만 반영하고 새롭게 움직일 가능성이 있는 번호를 보강했습니다.',
    ]
    balances = [
        f'전체 홀짝 흐름은 홀수 {odd}개/짝수 {even}개 기준으로 검토했습니다.',
        f'저·중·고 구간 분포는 {low}/{mid}/{high} 흐름으로 맞춰 편중을 줄였습니다.',
        '끝수 반복과 연속수 과다 사용을 제한해 조합별 형태가 겹치지 않게 했습니다.',
        '번호 간 간격과 AC값을 함께 확인해 단순 나열식 조합을 줄였습니다.',
        '회원별 발송 조합이 서로 비슷하게 반복되지 않도록 분산 기준을 추가했습니다.',
    ]
    closers = [
        '단순 빈도보다 번호 간 균형과 최근 흐름을 함께 본 추천입니다.',
        '최근 데이터와 누적 통계를 함께 고려한 심층 추천 결과입니다.',
        '안정성과 변화 가능성을 동시에 반영한 구성입니다.',
    ]
    lines = [pick(openers,1), pick(middles,7), pick(balances,13), pick(closers,19)]
    clean=[]
    for line in lines:
        if line and line not in clean:
            clean.append(line)
    return '\n'.join(clean[:4])

@app.get('/api/rc7-1/status')
def rc7_1_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': RC71_ENGINE_VERSION, 'engine': DB_ENGINE, 'summary': '회원별 추천번호/분석요약 분산 엔진 적용', 'admin': admin.get('username')}
# ===================== /RC7-1 MEMBER PERSONALIZED AI ENGINE V2 =====================




# ===================== RC7-3 SMSGANDA REAL XLS EXPORT =====================
class SmsGandaRow(BaseModel):
    name: str = ''
    phone: str = ''
    seg1: str = ''
    seg2: str = ''
    seg3: str = ''
    seg4: str = ''

class SmsGandaXlsReq(BaseModel):
    rows: list[SmsGandaRow] = []
    scope: str = 'all'
    round_no: str | int | None = None

def _smsganda_clean_phone(value):
    return re.sub(r'[^0-9]', '', str(value or ''))

def _safe_download_name(name):
    return re.sub(r'[^0-9A-Za-z_\-가-힣]', '_', str(name or 'download'))[:120] or 'download'

def _smsganda_cell_text(value):
    """RC7-21 문자간다 최종 포맷.
    문자간다 엑셀 업로드가 CR/LF를 지우는 환경이 있어, 실제 미리보기에서 줄로 인식된
    Unicode LINE SEPARATOR(U+2028)를 저장합니다. 또한 이전 패치의 / 구분과 1) 형식을
    1. 형식의 한 줄 1조합으로 복구합니다.
    """
    text = str(value or '')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\\n', '\n')
    text = re.sub(r'\s*/\s*(?=\d{1,2}[\.\)]\s*)', '\n', text)
    text = re.sub(r'(\[추천번호\])\s*(?=\d{1,2}[\.\)]\s*)', r'\1\n', text)
    text = re.sub(r'([^\n])\s+(?=\d{1,2}[\.\)]\s*\d)', r'\1\n', text)
    text = re.sub(r'(^|\n)(\d{1,2})\)\s*', r'\1\2. ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text.replace('\n', '\u2028')

@app.post('/api/export/smsganda_xls')
def export_smsganda_real_xls(req: SmsGandaXlsReq, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    try:
        import xlwt
    except Exception as e:
        raise HTTPException(status_code=500, detail='문자간다 XLS 생성 모듈(xlwt)이 설치되지 않았습니다. requirements.txt에 xlwt를 추가한 뒤 재배포하세요.') from e

    cleaned=[]
    seen=set()
    for row in (req.rows or []):
        name = str(row.name or '').strip()
        phone = _smsganda_clean_phone(row.phone)
        if not name or not phone:
            continue
        key=(name, phone)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append((
            name,
            phone,
            str(getattr(row, 'seg1', '') or ''),
            str(getattr(row, 'seg2', '') or ''),
            str(getattr(row, 'seg3', '') or ''),
            str(getattr(row, 'seg4', '') or '')
        ))
    if not cleaned:
        raise HTTPException(status_code=400, detail='엑셀로 만들 회원 이름/전화번호가 없습니다.')

    # 문자간다 제공 샘플 형식 그대로 맞춥니다.
    # 샘플 1행: 이름, 휴대전화, [*1*], [*2*], [*3*], [*4*]
    # 실제 데이터는 2행부터 A열=이름, B열=휴대전화, C~F열=[*1*]~[*4*] 치환값으로 저장합니다.
    wb = xlwt.Workbook(encoding='cp949')
    ws = wb.add_sheet('Sheet1')

    header_style = xlwt.XFStyle()
    header_style.num_format_str = '@'
    header_font = xlwt.Font()
    header_font.bold = True
    header_style.font = header_font

    text_style = xlwt.XFStyle()
    text_style.num_format_str = '@'
    text_alignment = xlwt.Alignment()
    text_alignment.wrap = 1
    text_alignment.vert = xlwt.Alignment.VERT_TOP
    text_style.alignment = text_alignment

    headers = ['이름', '휴대전화', '[*1*]', '[*2*]', '[*3*]', '[*4*]']
    for col, header in enumerate(headers):
        ws.write(0, col, header, header_style)

    for idx, (name, phone, seg1, seg2, seg3, seg4) in enumerate(cleaned, start=1):
        ws.write(idx, 0, name, text_style)
        ws.write(idx, 1, phone, text_style)
        ws.write(idx, 2, _smsganda_cell_text(seg1), text_style)
        ws.write(idx, 3, _smsganda_cell_text(seg2), text_style)
        ws.write(idx, 4, _smsganda_cell_text(seg3), text_style)
        ws.write(idx, 5, _smsganda_cell_text(seg4), text_style)
        max_lines = max(1, *[_smsganda_cell_text(v).count('\n') + 1 for v in (seg1, seg2, seg3, seg4)])
        ws.row(idx).height_mismatch = True
        ws.row(idx).height = min(9000, max(360, max_lines * 300))

    widths = [16, 18, 34, 44, 44, 28]
    for col, width in enumerate(widths):
        ws.col(col).width = width * 256

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    scope_label = {'all':'전체회원','representative':'대표관리자회원','general':'일반관리자회원','selected':'선택회원'}.get(str(req.scope or 'all'), '회원')
    round_part = f'{req.round_no}회차_' if req.round_no else ''
    filename = _safe_download_name(f'BBLOTTO_{round_part}문자간다_주소록_{scope_label}.xls')
    # Starlette/HTTP headers are latin-1 encoded. Korean text in the plain filename= part
    # causes a server 500 error, so keep filename= ASCII and put the real Korean filename
    # only in RFC 5987 filename*=UTF-8''.
    ascii_filename = 'bblotto_smsganda_address.xls'
    quoted = urllib.parse.quote(filename)
    return StreamingResponse(
        bio,
        media_type='application/vnd.ms-excel',
        headers={'Content-Disposition': f"attachment; filename={ascii_filename}; filename*=UTF-8''{quoted}"}
    )



# ===================== RC7-5 SMSGANDA TXT CP949 EXPORT =====================
@app.post('/api/export/smsganda_txt')
def export_smsganda_txt(req: SmsGandaXlsReq, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    cleaned=[]
    seen=set()
    for row in (req.rows or []):
        name = str(row.name or '').strip()
        phone = _smsganda_clean_phone(row.phone)
        if not name or not phone:
            continue
        key=(name, phone)
        if key in seen:
            continue
        seen.add(key)
        # 문자간다 텍스트 업로드용: 이름,전화번호 한 줄씩
        cleaned.append(f'{name},{phone}')
    if not cleaned:
        raise HTTPException(status_code=400, detail='TXT로 만들 회원 이름/전화번호가 없습니다.')

    # 문자간다 구형 업로드 화면 호환을 위해 CP949(ANSI) + CRLF로 저장합니다.
    text = '\r\n'.join(cleaned) + '\r\n'
    data = text.encode('cp949', errors='replace')
    bio = io.BytesIO(data)
    scope_label = {'all':'전체회원','representative':'대표관리자회원','general':'일반관리자회원','selected':'선택회원'}.get(str(req.scope or 'all'), '회원')
    round_part = f'{req.round_no}회차_' if req.round_no else ''
    filename = _safe_download_name(f'BBLOTTO_{round_part}문자간다_주소록_{scope_label}.txt')
    ascii_filename = 'bblotto_smsganda_address.txt'
    quoted = urllib.parse.quote(filename)
    return StreamingResponse(
        bio,
        media_type='text/plain; charset=cp949',
        headers={'Content-Disposition': f"attachment; filename={ascii_filename}; filename*=UTF-8''{quoted}"}
    )

@app.get('/api/rc7-5/status')
def rc7_5_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-5 SMSGANDA TXT CP949', 'engine': DB_ENGINE, 'summary': '문자간다 TXT ANSI/CP949 주소록 생성 기본 지원', 'admin': admin.get('username')}

@app.get('/api/rc7-6/status')
def rc7_6_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-6 SMSGANDA TEMPLATE XLS', 'engine': DB_ENGINE, 'summary': '문자간다 샘플 XLS 헤더 형식(이름/휴대전화/[*1*]~[*4*]) 적용', 'admin': admin.get('username')}

@app.get('/api/rc7-8/status')
def rc7_8_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-8 SMSGANDA SEND CENTER', 'engine': DB_ENGINE, 'summary': '문자간다 [*1*]~[*4*] 문구 분리/수정/미리보기/XLS 연동 적용', 'admin': admin.get('username')}
# ===================== /RC7-5 SMSGANDA TXT CP949 EXPORT =====================

@app.get('/api/rc7-4/status')
def rc7_4_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-4 SMSGANDA HEADER FIX', 'engine': DB_ENGINE, 'summary': '문자간다 XLS 다운로드 한글 파일명 헤더 오류 수정', 'admin': admin.get('username')}

@app.get('/api/rc7-3/status')
def rc7_3_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-3 SMSGANDA REAL XLS', 'engine': DB_ENGINE, 'summary': '문자간다 샘플 기준 Excel 97-2003 BIFF .xls 주소록 생성', 'admin': admin.get('username')}
# ===================== /RC7-3 SMSGANDA REAL XLS EXPORT =====================


# ===================== RC7-2 SMSGANDA XLS EXPORT =====================
@app.get('/api/rc7-2/status')
def rc7_2_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-2 SMSGANDA XLS', 'engine': DB_ENGINE, 'summary': '문자간다 A열 이름/B열 전화번호 XLS 업로드 파일 생성 지원', 'admin': admin.get('username')}
# ===================== /RC7-2 SMSGANDA XLS EXPORT =====================

# ===================== BBLOTTO AI V4 ENGINE FULL REPLACEMENT =====================
# 기존 API/DB/화면 구조는 유지하고 실제 추천번호 생성 엔진만 최종 오버라이드합니다.
BBLOTTO_AI_V4_ENGINE_VERSION = 'BBLOTTO_AI_V4_ENGINE_FULL_REPLACEMENT_RC8_1'


def _v4_grade_params(grade='일반'):
    g = rc45_grade_label(grade)
    if g == '1등':
        return {'candidates': 18000, 'tries': 240000, 'score_shift': 5.8, 'max_num_use': 3, 'max_pair_use': 1, 'max_overlap': 3, 'history_overlap': 3}
    if g == '2등':
        return {'candidates': 13000, 'tries': 180000, 'score_shift': 3.2, 'max_num_use': 4, 'max_pair_use': 1, 'max_overlap': 4, 'history_overlap': 4}
    return {'candidates': 8500, 'tries': 120000, 'score_shift': 0.0, 'max_num_use': 5, 'max_pair_use': 2, 'max_overlap': 4, 'history_overlap': 5}


def _v4_weight_profile(st, ext, mode='balanced', member_grade='일반'):
    profile, _ = _ai_v1_profile(st, mode)
    f10 = st.get('freq10') or {}
    f30 = st.get('freq30') or {}
    f50 = st.get('freq50') or {}
    f100 = st.get('freq100') or {}
    f300 = ext.get('freq300') or {}
    last = ext.get('last_seen300') or {}
    hot = set((ext.get('hot300') or [])[:16])
    cold = set((ext.get('cold300') or [])[:16])
    overdue = set((ext.get('overdue300') or [])[:18])
    mid = set((ext.get('mid300') or [])[:20])
    recent_numbers = set(st.get('recent_numbers') or [])
    g = rc45_grade_label(member_grade)
    for n in range(1, 46):
        trend = f10.get(n, 0) * 2.8 + f30.get(n, 0) * 1.45 + f50.get(n, 0) * 0.75 + f100.get(n, 0) * 0.35 + f300.get(n, 0) * 0.12
        gap = min(28, int(last.get(n, 999) if last.get(n, 999) != 999 else 28)) * 0.32
        band = 1.25 if 11 <= n <= 35 else 0.75
        w = 1.0 + trend + gap + band + profile.get(n, 1.0) * 0.45
        if n in hot: w += 3.2 if g == '1등' else 2.1 if g == '2등' else 1.2
        if n in overdue: w += 2.4 if g == '1등' else 1.5 if g == '2등' else 0.9
        if n in cold: w += 0.8 if g == '1등' else 0.45
        if n in mid: w += 1.05 if g != '일반' else 0.55
        if n in recent_numbers: w *= 0.72
        if mode == 'aggressive' and n >= 31: w += 0.9
        if mode == 'conservative' and 10 <= n <= 35: w += 0.9
        profile[n] = max(0.2, round(w, 4))
    return profile


def _v4_gap_score(combo, ext):
    last = ext.get('last_seen300') or {}
    gaps = [min(30, int(last.get(n, 999) if last.get(n, 999) != 999 else 30)) for n in combo]
    avg_gap = sum(gaps) / 6
    # 너무 최근 번호만 몰리거나 너무 장기 미출현만 몰리는 것을 방지
    score = 0.0
    if 3.0 <= avg_gap <= 16.0: score += 5.5
    elif 1.5 <= avg_gap <= 23.0: score += 2.5
    if sum(1 for g in gaps if g >= 12) in (1, 2, 3): score += 3.0
    if sum(1 for g in gaps if g <= 2) >= 4: score -= 4.0
    return score


def _v4_combo_score(combo, st, mode, ext, profile, member_grade='일반'):
    combo = sorted(parse_nums(combo))
    if len(combo) != 6:
        return 0.0
    sig = _ai_v1_signature(combo)
    base = _rc42_adjusted_score(combo, st, mode, ext, profile)
    pairs100 = st.get('pair_counts') or collections.Counter()
    pairs300 = ext.get('pair300') or collections.Counter()
    triples300 = ext.get('triple300') or collections.Counter()
    hot = set((ext.get('hot300') or [])[:14])
    cold = set((ext.get('cold300') or [])[:14])
    overdue = set((ext.get('overdue300') or [])[:16])
    mid = set((ext.get('mid300') or [])[:20])
    s = float(base)
    # 패턴 안정성
    s += 4.6 if sig['odd'] in (2, 3, 4) else -7.5
    s += 5.2 if 105 <= sig['sum'] <= 178 else 1.5 if 92 <= sig['sum'] <= 190 else -8.0
    s += 5.0 if max(sig['zones']) <= 3 and min(sig['zones']) >= 1 else -8.0
    s += 3.5 if 6 <= sig['ac'] <= 10 else 1.0 if 5 <= sig['ac'] <= 11 else -5.0
    s += 2.8 if sig['end_dup'] <= 1 else 0.6 if sig['end_dup'] == 2 else -4.5
    s += 2.4 if sig['cons'] <= 1 else -4.5
    # 흐름 배합
    hits = {'hot': len(set(combo) & hot), 'cold': len(set(combo) & cold), 'overdue': len(set(combo) & overdue), 'mid': len(set(combo) & mid)}
    s += min(5.0, hits['hot'] * 1.5) + min(4.5, hits['overdue'] * 1.35) + min(3.4, hits['cold'] * 1.0) + min(3.2, hits['mid'] * 0.65)
    if hits['hot'] >= 5 or hits['overdue'] >= 5:
        s -= 4.0
    s += _v4_gap_score(combo, ext)
    # 동반출현/트리플은 과다하지 않게 가산
    pair_score = 0.0
    strong_pairs = 0
    for p in itertools.combinations(combo, 2):
        key = tuple(sorted(p))
        pc = pairs100.get(key, 0) * 0.55 + pairs300.get(key, 0) * 0.45
        pair_score += pc
        if pc >= 3.5:
            strong_pairs += 1
    triple_score = sum(triples300.get(tuple(sorted(t)), 0) for t in itertools.combinations(combo, 3))
    s += min(7.0, pair_score / 8.0) + min(4.0, strong_pairs * 0.9) + min(3.5, triple_score / 4.0)
    if strong_pairs >= 8:
        s -= 3.5
    if triple_score >= 10:
        s -= 3.0
    s += _v4_grade_params(member_grade)['score_shift']
    s += ((sum(n * n for n in combo) + sum(combo) * 3) % 29 - 14) * 0.045
    return round(max(72.0, min(99.8, s)), 1)


def _v4_detail(combo, st, mode, ext, profile, member_grade='일반'):
    combo = sorted(parse_nums(combo))
    d = _rc42_detail(combo, st, mode, ext, profile)
    score = _v4_combo_score(combo, st, mode, ext, profile, member_grade)
    sig = _ai_v1_signature(combo)
    reasons, pair_hits = _ai_v1_reasons(combo, st, ext)
    extra = []
    if _v4_gap_score(combo, ext) >= 5: extra.append('출현간격 안정권')
    if len(pair_hits) >= 1: extra.append('동반출현 보정')
    if max(sig['zones']) <= 3 and min(sig['zones']) >= 1: extra.append('구간 분산 우수')
    tags = []
    for t in _rc729_grade_tags(member_grade) + reasons + extra + ['AI V4 후보대량선별']:
        if t and t not in tags:
            tags.append(t)
    d.update({
        'numbers': combo, 'score': score, 'ai_score': score, 'vip_score': score,
        'raw_score': score,
        'grade': rc45_grade_label(member_grade),
        'member_grade': rc45_grade_label(member_grade),
        'grade_strength': rc45_grade_strength_text(member_grade),
        'engine_version': BBLOTTO_AI_V4_ENGINE_VERSION,
        'engine_label': _rc729_engine_name(member_grade),
        'sum': sig['sum'], 'odd': sig['odd'], 'even': sig['even'], 'zones': sig['zones'], 'ac': sig['ac'],
        'end_digit_dup': sig['end_dup'], 'consecutive': sig['cons'],
        'tags': tags[:7], 'reasons': tags[:7], 'reason_text': ' · '.join(tags[:5]),
        'pair_hits': pair_hits,
        'quality_rule': '최근 10/30/50/100/300회, 출현간격, 동반출현, 트리플, 합계, 홀짝, 구간, 끝수, AC, 연속수, 이전 추천 유사도를 종합 검토',
    })
    return d


def make_premium_combos(count=10, fixed='', excluded='', mode='balanced', member_grade='일반', member_id=None):
    """BBLOTTO AI V4: 추천번호 생성 엔진 전면 교체 버전.
    기존 라우트와 DB 저장 방식은 유지하면서 후보 생성/점수/포트폴리오 선별만 새로 수행합니다.
    """
    member_grade = rc45_grade_label(member_grade)
    params = _v4_grade_params(member_grade)
    st = latest_stats(300)
    ext = _ai_v1_window_stats(st, 300)
    fixed_set = set(parse_nums(fixed)); excluded_set = set(parse_nums(excluded))
    fixed_set = {n for n in fixed_set if n not in excluded_set}
    if len(fixed_set) > 6:
        fixed_set = set(sorted(fixed_set)[:6])
    pool = [n for n in range(1, 46) if n not in excluded_set and n not in fixed_set]
    target = max(1, min(50, int(count or 10)))
    if len(pool) + len(fixed_set) < 6:
        raise HTTPException(400, '고정수/제외수를 확인하세요. 선택 가능한 번호가 부족합니다.')

    profile = _v4_weight_profile(st, ext, mode, member_grade)
    past_draws = {tuple(sorted(d.get('numbers') or [])) for d in st.get('draws', []) if len(d.get('numbers') or []) == 6}
    recent_history = _rc55_recent_recommendation_combos(member_id=member_id, limit=300)
    recent_usage = collections.Counter(n for combo in recent_history[:100] for n in combo)

    buckets = {
        'hot': [n for n in (ext.get('hot300') or [])[:25] if n in pool],
        'cold': [n for n in (ext.get('cold300') or [])[:25] if n in pool],
        'overdue': [n for n in (ext.get('overdue300') or [])[:25] if n in pool],
        'mid': [n for n in (ext.get('mid300') or [])[:30] if n in pool],
        'low': [n for n in range(1, 16) if n in pool],
        'middle': [n for n in range(16, 31) if n in pool],
        'high': [n for n in range(31, 46) if n in pool],
        'all': pool[:],
    }
    plans = [
        ['hot','overdue','mid','low','middle','high'],
        ['hot','cold','overdue','mid','all','all'],
        ['mid','hot','cold','low','middle','high'],
        ['overdue','hot','mid','all','all','all'],
        ['low','middle','high','hot','overdue','mid'],
        ['cold','mid','hot','overdue','all','all'],
    ]
    if member_grade == '1등':
        plans += [['hot','hot','overdue','mid','cold','all'], ['overdue','hot','mid','low','middle','high']]
    elif member_grade == '2등':
        plans += [['hot','overdue','mid','cold','all','all'], ['mid','hot','overdue','low','high','all']]
    if mode == 'aggressive':
        plans += [['hot','hot','high','overdue','all','all'], ['hot','mid','high','cold','all','all']]
    elif mode == 'conservative':
        plans += [['mid','mid','cold','overdue','low','middle'], ['cold','mid','middle','all','all','all']]

    candidates, seen = [], set()
    tries = 0
    while len(candidates) < params['candidates'] and tries < params['tries']:
        tries += 1
        nums = set(fixed_set)
        plan = random.choice(plans)[:]
        random.shuffle(plan)
        for name in plan:
            if len(nums) >= 6:
                break
            usable = [n for n in buckets.get(name, pool) if n not in nums]
            if usable:
                nums.update(_weighted_pick(usable, [profile.get(n, 1) for n in usable], 1))
        while len(nums) < 6:
            usable = [n for n in pool if n not in nums]
            if not usable:
                break
            nums.update(_weighted_pick(usable, [profile.get(n, 1) for n in usable], 1))
        arr = tuple(sorted(nums))
        if len(arr) != 6 or arr in seen or arr in past_draws:
            continue
        if _rc55_too_close_to_history(arr, recent_history, max_overlap=params['history_overlap']):
            continue
        ok, _why = _rc42_combo_ok(arr, past=past_draws, fixed_set=fixed_set)
        if not ok:
            continue
        sig = _ai_v1_signature(arr)
        if sig['odd'] not in (2, 3, 4): continue
        if not (92 <= sig['sum'] <= 190): continue
        if max(sig['zones']) > 3 or min(sig['zones']) == 0: continue
        if sig['cons'] > 1: continue
        if sig['end_dup'] > 2: continue
        if not (5 <= sig['ac'] <= 11): continue
        seen.add(arr)
        score = _v4_combo_score(arr, st, mode, ext, profile, member_grade)
        # 최근 추천에 많이 쓰인 번호는 살짝 감점해 매번 같은 번호 반복을 줄임
        score -= min(2.8, sum(recent_usage.get(n, 0) for n in arr) * 0.04)
        candidates.append((round(max(72.0, min(99.8, score)), 1), list(arr)))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    usage = collections.Counter()
    pair_usage = collections.Counter()
    pattern_usage = collections.Counter()

    def pattern_key(combo):
        try:
            return _rc42_pattern_key(combo)
        except Exception:
            sig = _ai_v1_signature(combo)
            return (sig['odd'], tuple(sig['zones']), sig['sum'] // 10, sig['ac'])

    def can_add(combo, max_num_use, max_pair_use, max_overlap, max_pattern_use=3):
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        pkey = pattern_key(combo)
        if any(usage[n] >= max_num_use for n in combo if n not in fixed_set): return False
        if any(pair_usage[p] >= max_pair_use for p in pairs): return False
        if pattern_usage[pkey] >= max_pattern_use: return False
        if not all(len(set(combo) & set(prev)) <= max_overlap for prev in selected): return False
        return True

    def add_combo(combo):
        selected.append(combo)
        usage.update(combo)
        pair_usage.update([tuple(sorted(p)) for p in itertools.combinations(combo, 2)])
        pattern_usage.update([pattern_key(combo)])

    limit_sets = [
        (params['max_num_use'], params['max_pair_use'], params['max_overlap'], 2),
        (params['max_num_use'] + 1, params['max_pair_use'] + 1, 4, 3),
        (6, 3, 4, 5),
    ]
    for limits in limit_sets:
        if len(selected) >= target: break
        for _score, combo in candidates:
            if combo in selected: continue
            if can_add(combo, *limits): add_combo(combo)
            if len(selected) >= target: break
    if len(selected) < target:
        for _score, combo in candidates:
            if combo not in selected:
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        # 극단적인 고정/제외 조건에서도 화면이 멈추지 않도록 최종 안전 fallback
        fallback = make_combos(target - len(selected), ','.join(map(str, fixed_set)), ','.join(map(str, excluded_set)), mode)
        for combo in fallback:
            if combo not in selected:
                add_combo(combo)
            if len(selected) >= target:
                break

    details = [_v4_detail(c, st, mode, ext, profile, member_grade) for c in selected[:target]]
    details.sort(key=lambda x: -float(x.get('score') or 0))
    selected_sorted = [d['numbers'] for d in details]
    st.update(ext)
    st.update({
        'engine_version': BBLOTTO_AI_V4_ENGINE_VERSION,
        'member_grade': member_grade,
        'grade_strength': rc45_grade_strength_text(member_grade),
        'ai_v4_candidates': len(candidates),
        'ai_v4_attempts': tries,
        'ai_v1_candidates': len(candidates),
        'ai_v1_attempts': tries,
        'rc55_history_checked': len(recent_history),
        'rc42_portfolio': {
            'max_overlap': max((len(set(a) & set(b)) for i, a in enumerate(selected_sorted) for b in selected_sorted[i+1:]), default=0),
            'unique_patterns': len({pattern_key(c) for c in selected_sorted}),
            'number_usage_max': max(usage.values()) if usage else 0,
            'pair_usage_max': max(pair_usage.values()) if pair_usage else 0,
            'recent_history_checked': len(recent_history),
        }
    })
    return selected_sorted[:target], details[:target], st


def _engine_summary(details, st):
    scores = [float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    grade = rc45_grade_label(st.get('member_grade') or (details[0].get('member_grade') if details else '일반'))
    return {
        'version': BBLOTTO_AI_V4_ENGINE_VERSION,
        'engine_version': BBLOTTO_AI_V4_ENGINE_VERSION,
        'phase': 'RC8-1',
        'member_grade': grade,
        'engine_label': _rc729_engine_name(grade),
        'grade_strength': rc45_grade_strength_text(grade),
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('ai_v4_candidates') or st.get('ai_v1_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'v4_report': {
            'summary': '추천번호 엔진을 AI V4로 전면 교체했습니다. 최근 10/30/50/100/300회 흐름, 출현간격, 동반출현, 트리플, AC값, 끝수, 구간, 연속수, 이전 추천 유사도를 종합 선별합니다.',
            'portfolio': st.get('rc42_portfolio') or {},
            'candidates': int(st.get('ai_v4_candidates') or 0),
            'attempts': int(st.get('ai_v4_attempts') or 0),
        },
        'rc55_report': {
            'grade_policy': '1등/2등/일반 3단계 전용 점수 구간은 유지하되, 후보 생성·점수화·포트폴리오 선별은 AI V4 기준으로 교체',
            'portfolio': st.get('rc42_portfolio') or {},
            'summary': '후보 대량 생성 후 번호/페어/패턴/최근 추천 중복을 줄여 최종 조합을 선별했습니다.'
        },
        'rc45_report': {
            'summary': '최근 흐름과 누적 통계를 함께 반영한 심층 추천 결과입니다.',
            'portfolio': st.get('rc42_portfolio') or {},
        }
    }
# ===================== /BBLOTTO AI V4 ENGINE FULL REPLACEMENT =====================

# RC8-1 점수 보정: 기존 고점수 함수 영향으로 모든 조합이 99점대에 몰리지 않도록 V4 자체 점수화로 재정의합니다.
def _v4_combo_score(combo, st, mode, ext, profile, member_grade='일반'):
    combo = sorted(parse_nums(combo))
    if len(combo) != 6:
        return 0.0
    sig = _ai_v1_signature(combo)
    pairs100 = st.get('pair_counts') or collections.Counter()
    pairs300 = ext.get('pair300') or collections.Counter()
    triples300 = ext.get('triple300') or collections.Counter()
    hot = set((ext.get('hot300') or [])[:14]); cold = set((ext.get('cold300') or [])[:14]); overdue = set((ext.get('overdue300') or [])[:16]); mid = set((ext.get('mid300') or [])[:20])
    s = 58.0
    s += {3: 9.0, 2: 7.0, 4: 7.0, 1: 1.0, 5: 1.0}.get(sig['odd'], -6.0)
    s += 9.0 if 105 <= sig['sum'] <= 178 else 4.0 if 92 <= sig['sum'] <= 190 else -8.0
    s += 8.0 if max(sig['zones']) <= 3 and min(sig['zones']) >= 1 else -9.0
    s += 5.5 if 6 <= sig['ac'] <= 10 else 2.0 if 5 <= sig['ac'] <= 11 else -5.0
    s += 4.0 if sig['end_dup'] <= 1 else 1.5 if sig['end_dup'] == 2 else -5.0
    s += 3.5 if sig['cons'] == 0 else 1.5 if sig['cons'] == 1 else -5.0
    wavg = sum(profile.get(n, 1) for n in combo) / 6.0
    s += min(9.0, wavg * 0.36)
    hits = {'hot': len(set(combo) & hot), 'cold': len(set(combo) & cold), 'overdue': len(set(combo) & overdue), 'mid': len(set(combo) & mid)}
    s += min(5.2, hits['hot'] * 1.45) + min(4.6, hits['overdue'] * 1.30) + min(3.2, hits['cold'] * 0.9) + min(3.0, hits['mid'] * 0.55)
    if hits['hot'] >= 5 or hits['overdue'] >= 5: s -= 4.0
    s += _v4_gap_score(combo, ext)
    pair_score = 0.0; strong_pairs = 0
    for p in itertools.combinations(combo, 2):
        key = tuple(sorted(p)); pc = pairs100.get(key, 0) * 0.55 + pairs300.get(key, 0) * 0.45
        pair_score += pc
        if pc >= 3.5: strong_pairs += 1
    triple_score = sum(triples300.get(tuple(sorted(t)), 0) for t in itertools.combinations(combo, 3))
    s += min(5.0, pair_score / 11.0) + min(3.0, strong_pairs * 0.65) + min(2.4, triple_score / 5.5)
    if strong_pairs >= 8: s -= 3.5
    if triple_score >= 10: s -= 3.0
    # 등급별 표시는 분리하되 일반/2등/1등 점수대가 완전히 같아 보이지 않도록 차등 보정
    g = rc45_grade_label(member_grade)
    if g == '1등': s += 4.2
    elif g == '2등': s += 2.0
    s += ((sum(n * n for n in combo) + sum(combo) * 3) % 29 - 14) * 0.055
    return round(max(72.0, min(99.2, s)), 1)

# RC8-1 점수 보정 2차: 점수 분포를 일반 88~94, 2등 92~96, 1등 95~99 근처로 자연스럽게 분산합니다.
def _v4_combo_score(combo, st, mode, ext, profile, member_grade='일반'):
    combo = sorted(parse_nums(combo))
    if len(combo) != 6:
        return 0.0
    sig = _ai_v1_signature(combo)
    pairs100 = st.get('pair_counts') or collections.Counter(); pairs300 = ext.get('pair300') or collections.Counter(); triples300 = ext.get('triple300') or collections.Counter()
    hot = set((ext.get('hot300') or [])[:14]); cold = set((ext.get('cold300') or [])[:14]); overdue = set((ext.get('overdue300') or [])[:16]); mid = set((ext.get('mid300') or [])[:20])
    s = 41.0
    s += {3: 7.5, 2: 5.8, 4: 5.8, 1: 0.5, 5: 0.5}.get(sig['odd'], -5.5)
    s += 7.0 if 105 <= sig['sum'] <= 178 else 3.0 if 92 <= sig['sum'] <= 190 else -7.0
    s += 6.8 if max(sig['zones']) <= 3 and min(sig['zones']) >= 1 else -8.0
    s += 4.8 if 6 <= sig['ac'] <= 10 else 1.6 if 5 <= sig['ac'] <= 11 else -4.5
    s += 3.2 if sig['end_dup'] <= 1 else 1.0 if sig['end_dup'] == 2 else -4.0
    s += 2.8 if sig['cons'] == 0 else 1.0 if sig['cons'] == 1 else -4.5
    wavg = sum(profile.get(n, 1) for n in combo) / 6.0
    s += min(7.0, wavg * 0.13)
    hits = {'hot': len(set(combo) & hot), 'cold': len(set(combo) & cold), 'overdue': len(set(combo) & overdue), 'mid': len(set(combo) & mid)}
    s += min(4.0, hits['hot'] * 1.15) + min(3.6, hits['overdue'] * 1.05) + min(2.8, hits['cold'] * 0.75) + min(2.5, hits['mid'] * 0.45)
    if hits['hot'] >= 5 or hits['overdue'] >= 5: s -= 3.5
    s += min(5.0, _v4_gap_score(combo, ext) * 0.65)
    pair_score = 0.0; strong_pairs = 0
    for p in itertools.combinations(combo, 2):
        key = tuple(sorted(p)); pc = pairs100.get(key, 0) * 0.55 + pairs300.get(key, 0) * 0.45
        pair_score += pc
        if pc >= 3.5: strong_pairs += 1
    triple_score = sum(triples300.get(tuple(sorted(t)), 0) for t in itertools.combinations(combo, 3))
    s += min(4.0, pair_score / 18.0) + min(2.3, strong_pairs * 0.45) + min(1.8, triple_score / 8.0)
    if strong_pairs >= 8: s -= 3.0
    if triple_score >= 10: s -= 2.5
    g = rc45_grade_label(member_grade)
    if g == '1등': s += 5.0
    elif g == '2등': s += 3.7
    s += ((sum(n * n for n in combo) + sum(combo) * 3) % 29 - 14) * 0.065
    return round(max(72.0, min(99.2, s)), 1)

# =========================================================
# BBLOTTO AI V6 DB FULL HISTORY CACHE FINAL PATCH
# - 분석 결과를 database/bblotto_v34.db 의 ai_analysis_cache 테이블에 저장
# - 1회차~1231회차 전체 보유 여부를 API로 확인 가능
# - 추천번호 생성은 최종적으로 ai_engine_v6만 사용
# =========================================================
try:
    from .ai_engine_v7 import make_premium_combos as make_premium_combos
    from .ai_engine_v7 import latest_stats as latest_stats
    from .ai_engine_v7 import get_analysis_cache as _ai_v6_get_analysis_cache
    BBLOTTO_AI_V6_ENGINE_VERSION = 'BBLOTTO_RC10_AUTO_FULL_HISTORY'

    @app.get('/api/ai-engine/v6-cache')
    def ai_engine_v6_cache(authorization: str|None = Header(default=None), force: int = 0, target_round: int|None = None):
        require_admin(authorization)
        cache = _ai_v6_get_analysis_cache(bool(force), target_round=target_round)
        return {
            'ok': True,
            'engine_version': cache.get('engine_version'),
            'cache_storage': cache.get('cache_storage'),
            'analysis_confirm': cache.get('analysis_confirm'),
            'draw_count': cache.get('draw_count'),
            'actual_count': cache.get('actual_count'),
            'expected_count': cache.get('expected_count'),
            'round_range': cache.get('round_range'),
            'latest_round': cache.get('latest_round'),
            'target_round': cache.get('target_round'),
            'is_full_history': cache.get('is_full_history'),
            'missing_rounds_count': cache.get('missing_rounds_count'),
            'missing_rounds_sample': cache.get('missing_rounds_sample'),
            'hot': cache.get('hot', [])[:12],
            'cold': cache.get('cold', [])[:12],
            'overdue': cache.get('overdue', [])[:12],
            'cache_used': True,
        }
except Exception as _v6_import_error:
    BBLOTTO_AI_V6_ENGINE_VERSION = 'BBLOTTO_AI_V6_IMPORT_FAILED'
    print('[BBLOTTO] AI V6 engine import failed:', _v6_import_error)

try:
    from .ai_engine_v7 import sync_official_full_history as _ai_v6_sync_official_full_history

    @app.post('/api/ai-engine/v6-sync-full')
    def ai_engine_v6_sync_full(authorization: str|None = Header(default=None), max_round: int|None = None):
        require_admin(authorization)
        return _ai_v6_sync_official_full_history(max_round=max_round)
except Exception as _v6_sync_import_error:
    print('[BBLOTTO] AI V6 sync endpoint failed:', _v6_sync_import_error)


# =========================================================
# BBLOTTO AI V6 관리자 화면용 전체 동기화/분석 API
# - 관리자 버튼에서 사용: POST /api/admin/ai-v6/full-sync
# - 주소 직접 입력 시 Not Found 대신 안내/실행 가능 여부 반환
# =========================================================
try:
    from .ai_engine_v7 import sync_official_full_history as _bb_v6_sync_full_ui
    from .ai_engine_v7 import get_analysis_cache as _bb_v6_cache_ui

    @app.post('/api/admin/ai-v6/full-sync')
    def admin_ai_v6_full_sync(authorization: str|None = Header(default=None), max_round: int|None = None):
        require_admin(authorization)
        sync_result = _bb_v6_sync_full_ui(max_round=max_round)
        cache = _bb_v6_cache_ui(True, target_round=max_round)
        return {
            'ok': True,
            'message': sync_result.get('message') or (f'1회차~{cache.get("target_round", max_round)}회차 전체 동기화/분석 저장 완료' if cache.get('is_full_history') else f'전체 분석 미완료: {cache.get("missing_rounds_count", 0)}개 누락'),
            'completed': bool(cache.get('is_full_history')),
            'sync_result': sync_result,
            'cache': {
                'engine_version': cache.get('engine_version'),
                'cache_storage': cache.get('cache_storage'),
                'analysis_confirm': cache.get('analysis_confirm'),
                'actual_count': cache.get('actual_count'),
                'expected_count': cache.get('expected_count'),
                'round_range': cache.get('round_range'),
                'latest_round': cache.get('latest_round'),
                'target_round': cache.get('target_round'),
                'is_full_history': cache.get('is_full_history'),
                'missing_rounds_count': cache.get('missing_rounds_count'),
                'missing_rounds_sample': cache.get('missing_rounds_sample'),
            }
        }


    from .ai_engine_v7 import sync_official_history_step as _bb_v6_sync_step_ui

    @app.post('/api/admin/ai-v6/full-sync-step')
    def admin_ai_v6_full_sync_step(authorization: str|None = Header(default=None), max_round: int|None = None, chunk_size: int = 25):
        require_admin(authorization)
        try:
            return _bb_v6_sync_step_ui(max_round=max_round, chunk_size=chunk_size)
        except Exception as exc:
            # 브라우저에는 원인을 알 수 없는 500 오류 대신 재시도 가능한 안내를 반환합니다.
            print('[BBLOTTO] AI V7 step sync failed:', repr(exc))
            return {
                'ok': False,
                'completed': False,
                'message': '회차 동기화 처리 중 오류가 발생했습니다. 잠시 후 다시 실행해주세요.',
                'error_type': type(exc).__name__,
                'retryable': True,
            }

    @app.get('/api/admin/ai-v6/cache-status')
    def admin_ai_v6_cache_status(authorization: str|None = Header(default=None), target_round: int|None = None):
        require_admin(authorization)
        cache = _bb_v6_cache_ui(False, target_round=target_round)
        return {
            'ok': True,
            'engine_version': cache.get('engine_version'),
            'cache_storage': cache.get('cache_storage'),
            'analysis_confirm': cache.get('analysis_confirm'),
            'actual_count': cache.get('actual_count'),
            'expected_count': cache.get('expected_count'),
            'round_range': cache.get('round_range'),
            'latest_round': cache.get('latest_round'),
            'target_round': cache.get('target_round'),
            'is_full_history': cache.get('is_full_history'),
            'missing_rounds_count': cache.get('missing_rounds_count'),
            'missing_rounds_sample': cache.get('missing_rounds_sample'),
        }

    @app.get('/admin/sync-full-history')
    def admin_sync_full_history_url_notice(authorization: str|None = Header(default=None), max_round: int|None = None):
        # 브라우저 주소창 직접 입력 시 기존처럼 Not Found가 나오지 않도록 안내한다.
        # 실제 실행은 로그인 후 관리자 화면 버튼 또는 Authorization 헤더가 있는 요청에서만 가능하다.
        if not authorization:
            return {
                'ok': False,
                'message': '주소창 직접 입력은 로그인 토큰이 없어 실행하지 않습니다. 관리자 화면 > AI 엔진 > 전체 회차 동기화 버튼을 눌러주세요.',
                'api': '/api/admin/ai-v6/full-sync',
                'target_round': max_round
            }
        require_admin(authorization)
        sync_result = _bb_v6_sync_full_ui(max_round=max_round)
        cache = _bb_v6_cache_ui(True, target_round=max_round)
        return {'ok': bool(cache.get('is_full_history')), 'message': sync_result.get('message') or ('전체 저장/분석 완료' if cache.get('is_full_history') else '전체 분석 미완료'), 'sync_result': sync_result, 'cache': cache}
except Exception as _bb_v6_ui_sync_error:
    print('[BBLOTTO] AI V6 admin UI sync endpoint failed:', _bb_v6_ui_sync_error)


# ===================== RC10.2 DYNAMIC MEMBER-FRIENDLY ANALYSIS =====================
def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    """추천번호의 실제 특징을 바탕으로, 생성할 때마다 표현이 달라지는 쉬운 분석문을 만든다."""
    import random
    import secrets

    details = details or []
    combos = []
    for item in details:
        nums = item.get('numbers') or item.get('nums') or item.get('combo') or []
        try:
            nums = sorted({int(n) for n in nums if 1 <= int(n) <= 45})
        except Exception:
            nums = []
        if len(nums) == 6:
            combos.append(nums)

    flat = [n for combo in combos for n in combo]
    rng = random.Random(secrets.randbits(64))
    latest_round = int(st.get('latest_round') or st.get('target_round') or max(0, int(round_no or 1) - 1))
    hot = [int(x) for x in (st.get('hot300') or st.get('hot100') or st.get('hot') or [])[:10] if str(x).isdigit()]
    overdue = [int(x) for x in (st.get('overdue300') or st.get('overdue100') or st.get('overdue') or [])[:10] if str(x).isdigit()]

    if not flat:
        return '\n'.join(rng.sample([
            '최근 흐름과 전체 기록을 함께 살펴 번호가 한쪽에 몰리지 않도록 구성했습니다.',
            '자주 나온 번호와 한동안 쉬었던 번호를 섞어 이번 회차의 변화를 함께 살폈습니다.',
            '비슷한 모양의 조합이 반복되지 않도록 번호 간 간격과 구간을 고르게 맞췄습니다.',
            '이번 추천은 단순히 많이 나온 번호만 고르지 않고 전체적인 균형을 우선했습니다.',
        ], 3))

    low = sum(1 for n in flat if n <= 15)
    mid = sum(1 for n in flat if 16 <= n <= 30)
    high = len(flat) - low - mid
    odd = sum(1 for n in flat if n % 2)
    even = len(flat) - odd
    zone_counts = [('낮은 번호대', low), ('중간 번호대', mid), ('높은 번호대', high)]
    strongest_zone = max(zone_counts, key=lambda x: x[1])[0]
    most_common = []
    freq = {}
    for n in flat:
        freq[n] = freq.get(n, 0) + 1
    most_common = [n for n, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:5]]
    hot_used = [n for n in hot if n in freq][:4]
    overdue_used = [n for n in overdue if n in freq][:4]
    consecutive_count = sum(1 for c in combos for a, b in zip(c, c[1:]) if b - a == 1)
    same_end_count = 0
    for c in combos:
        ends = [n % 10 for n in c]
        same_end_count += len(ends) - len(set(ends))

    mode_label = {'balanced': '균형을 우선한', 'conservative': '안정적인 흐름을 우선한', 'aggressive': '변화를 조금 더 반영한'}.get(mode, '균형을 우선한')
    opening_pool = [
        f'{latest_round}회차까지의 기록과 최근 흐름을 함께 살펴 이번 추천을 구성했습니다.',
        '이번 회차는 오래된 기록과 최근 움직임을 같이 비교해 번호를 골랐습니다.',
        '최근 결과만 보지 않고 전체 흐름까지 함께 확인해 추천번호를 정리했습니다.',
        f'1회차부터 {latest_round}회차까지의 흐름을 바탕으로 이번 조합을 새로 구성했습니다.',
        '이번 추천은 자주 나온 번호와 잠시 쉬었던 번호를 함께 비교해 만들었습니다.',
    ]
    zone_pool = [
        f'{strongest_zone}의 흐름이 비교적 눈에 띄어 다른 번호대와 함께 고르게 섞었습니다.',
        '낮은 번호, 중간 번호, 높은 번호가 한쪽에 몰리지 않도록 나누어 배치했습니다.',
        '특정 번호대만 반복되지 않도록 여러 구간을 섞어 조합의 폭을 넓혔습니다.',
        f'{mode_label} 방식으로 번호대를 나누어 전체적인 모양을 맞췄습니다.',
    ]
    flow_pool = []
    if hot_used:
        flow_pool += [
            f'최근 자주 보인 {", ".join(map(str, hot_used))}번을 중심 후보로 두되 다른 번호와 함께 분산했습니다.',
            f'{", ".join(map(str, hot_used))}번은 최근 흐름이 이어져 일부 조합에 나누어 반영했습니다.',
        ]
    if overdue_used:
        flow_pool += [
            f'한동안 쉬었던 {", ".join(map(str, overdue_used))}번도 일부 포함해 변화 가능성을 살폈습니다.',
            f'{", ".join(map(str, overdue_used))}번은 오랜 공백 뒤 다시 나올 가능성을 고려해 보강 후보로 넣었습니다.',
        ]
    if not flow_pool:
        flow_pool = [
            '최근에 자주 나온 번호와 한동안 쉬었던 번호를 함께 섞어 한쪽 흐름에 치우치지 않게 했습니다.',
            f'반복해서 사용된 중심 번호는 {", ".join(map(str, most_common))}번이며, 나머지 번호는 조합마다 다르게 배치했습니다.',
            '단순 출현 횟수보다 최근 움직임과 번호 간 조화를 함께 살폈습니다.',
        ]
    shape_pool = [
        '홀수와 짝수가 지나치게 한쪽으로 쏠리지 않도록 조합마다 균형을 맞췄습니다.',
        '조합끼리 같은 번호가 너무 많이 겹치지 않도록 서로 다른 구성을 우선했습니다.',
        '번호 간 간격이 너무 좁거나 넓은 조합은 줄이고 자연스러운 배열을 선택했습니다.',
        '끝자리가 같은 번호가 지나치게 반복되지 않도록 조합별로 나누어 배치했습니다.',
    ]
    if consecutive_count:
        shape_pool.append('연속번호는 일부 조합에만 넣어 최근 흐름을 반영하면서도 반복을 줄였습니다.')
    if same_end_count <= max(2, len(combos)):
        shape_pool.append('끝자리 분포가 비교적 고르게 나오도록 비슷한 끝수의 반복을 줄였습니다.')
    close_pool = [
        '전체적으로 비슷한 조합의 반복을 줄이고 각 조합의 차이를 살린 추천입니다.',
        '이번 결과는 한 가지 흐름에만 기대지 않고 여러 가능성을 나누어 담았습니다.',
        '번호가 한곳에 몰리지 않도록 조정해 보기 편하고 이해하기 쉬운 구성으로 정리했습니다.',
        '최근 흐름을 반영하되 과도한 편중은 줄이는 방향으로 최종 조합을 골랐습니다.',
    ]

    candidates = [rng.choice(opening_pool), rng.choice(zone_pool), rng.choice(flow_pool), rng.choice(shape_pool), rng.choice(close_pool)]
    result = []
    for line in candidates:
        if line not in result:
            result.append(line)
    # 화면이 지나치게 길어지지 않도록 4줄만 제공한다.
    return '\n'.join(result[:4])
# ===================== /RC10.2 DYNAMIC MEMBER-FRIENDLY ANALYSIS =====================


# ===== RC9 AI V7 integrity audit =====
