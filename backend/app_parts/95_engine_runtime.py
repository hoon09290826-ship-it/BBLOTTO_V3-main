"""Final recommendation, export, and explanation runtime.

Consolidated from the former staged upgrade/override files while preserving
their original execution order.
"""

# ---- recommendation engine refinements ----
# Extracted from legacy backend/app.py lines 5979-6941.
@router.get('/api/rc3-11/engine-status')
def rc311_engine_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    st = latest_stats(300)
    profile, ext = _ai_v1_profile(st, 'balanced')
    top_weighted = sorted(profile.keys(), key=lambda n: (-profile[n], n))[:12]
    sample_combos, sample_details, sample_stats = make_premium_combos(5, '', '', 'balanced')
    return {
        'ok': True,
        'version': AI_ENGINE_V1_VERSION,
        'latest_round': st.get('latest_round'),
        'draws_used': ext.get('draws_used'),
        'top_weighted': top_weighted,
        'hot300': ext.get('hot300', [])[:12],
        'cold300': ext.get('cold300', [])[:12],
        'overdue300': ext.get('overdue300', [])[:12],
        'sample': {'combos': sample_combos, 'details': sample_details, 'engine': _engine_summary(sample_details, sample_stats)},
        'summary': 'RC3-11 BBLOTTO AI Engine V1.0 상태 점검입니다.'
    }


# === RC3-14: 회원 상세 화면 정리 ===
@router.get('/api/rc3-14/status')
def rc314_status(authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    return {
        'ok': True,
        'version': 'RC3-14',
        'summary': '회원 상세 페이지에서 추천이력 노출을 제거하고 문구이력/당첨이력 중심으로 정리했습니다.',
        'sections': ['member_profile', 'memo', 'sms_logs', 'winning_checks']
    }


# === RC3-15: 당첨번호 회차 무결성 점검/복구 ===
@router.get('/api/rc3-15/draw-integrity')
def rc315_draw_integrity(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    expected, completed = _rc315_expected_round_and_completed()
    with con() as c:
        future_rows = c.execute('SELECT round_no,draw_date,numbers,bonus,source,updated_at FROM draws WHERE round_no>? ORDER BY round_no DESC', (completed,)).fetchall()
        latest_rows = c.execute('SELECT round_no,draw_date,numbers,bonus,source,updated_at FROM draws WHERE round_no<=? ORDER BY round_no DESC LIMIT 15', (completed or 999999,)).fetchall()
    return {
        'ok': len(future_rows) == 0,
        'version': 'RC3-15',
        'expected_round': expected,
        'completed_round': completed,
        'future_or_invalid_draws': [dict(r) for r in future_rows],
        'latest_valid_draws': [{'round_no':r['round_no'], 'draw_date':r['draw_date'], 'numbers':parse_nums(r['numbers']), 'bonus':r['bonus'], 'source':r['source'], 'updated_at':r['updated_at']} for r in latest_rows],
        'message': 'ok=false이면 /api/rc3-15/repair-draws 를 실행하면 추첨 전 회차 당첨번호가 정리됩니다.'
    }

@router.post('/api/rc3-15/repair-draws')
def rc315_repair_draws(request:Request, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    with con() as c:
        result = _rc315_clean_future_draws_in_conn(c)
        c.commit()
    log_action(admin, 'RC3_15_REPAIR_DRAWS', f'추첨 전/미래 회차 당첨번호 {result.get("removed",0)}건 정리', request)
    return {'ok': True, 'version': 'RC3-15', **result, 'message': f'잘못 저장된 추첨 전/미래 회차 {result.get("removed",0)}건을 정리했습니다.'}

# ===== RC4-2: Recommendation Engine Quality Upgrade =====
# 최종 실행 시점에서 /api/generate가 사용하는 추천 엔진을 RC4-2 버전으로 재정의합니다.
AI_ENGINE_RC42_VERSION = 'BBLOTTO_PRO_V2_RC4_2_AI_ENGINE'

def _rc42_gap_signature(combo):
    nums = sorted(parse_nums(combo))
    gaps = [nums[i] - nums[i-1] for i in range(1, len(nums))]
    return {
        'gaps': gaps,
        'min_gap': min(gaps) if gaps else 0,
        'max_gap': max(gaps) if gaps else 0,
        'small_gaps': sum(1 for g in gaps if g <= 2),
        'wide_gaps': sum(1 for g in gaps if g >= 15),
    }

def _rc42_end_digits(combo):
    digits = [int(n) % 10 for n in parse_nums(combo)]
    return digits, collections.Counter(digits)

def _rc42_pattern_key(combo):
    sig = _ai_v1_signature(combo)
    digits, dc = _rc42_end_digits(combo)
    decade = tuple(sum(1 for n in combo if lo <= n <= hi) for lo, hi in [(1,9),(10,19),(20,29),(30,39),(40,45)])
    return (sig['odd'], tuple(sig['zones']), decade, tuple(sorted(dc.values(), reverse=True)[:2]))

def _rc42_combo_ok(combo, past=None, fixed_set=None):
    combo = tuple(sorted(parse_nums(combo)))
    if len(combo) != 6 or len(set(combo)) != 6:
        return False, '중복 번호'
    if past and combo in past:
        return False, '과거 당첨 조합과 동일'
    sig = _ai_v1_signature(combo)
    gap = _rc42_gap_signature(combo)
    digits, dc = _rc42_end_digits(combo)
    if sig['odd'] not in (2, 3, 4):
        return False, '홀짝 불균형'
    if not (96 <= sig['sum'] <= 184):
        return False, '합계 범위 이탈'
    if max(sig['zones']) > 3 or min(sig['zones']) < 1:
        return False, '저중고 구간 불균형'
    if sig['cons'] > 1:
        return False, '연속수 과다'
    if sig['ac'] < 6 or sig['ac'] > 11:
        return False, 'AC값 범위 이탈'
    if max(dc.values() or [0]) > 2:
        return False, '끝수 중복 과다'
    if len(set(digits)) < 5:
        return False, '끝수 분산 부족'
    if gap['small_gaps'] > 2:
        return False, '근접 번호 과다'
    if gap['wide_gaps'] > 1 or gap['max_gap'] >= 20:
        return False, '번호 간격 과다'
    return True, '통과'

def _rc42_adjusted_score(combo, st, mode, ext, profile):
    score = float(_ai_v1_combo_score(combo, st, mode, ext, profile))
    sig = _ai_v1_signature(combo)
    gap = _rc42_gap_signature(combo)
    digits, dc = _rc42_end_digits(combo)
    if sig['odd'] == 3:
        score += 1.5
    if max(sig['zones']) == 2:
        score += 1.2
    if len(set(digits)) >= 6:
        score += 1.4
    elif len(set(digits)) == 5:
        score += 0.8
    if 118 <= sig['sum'] <= 166:
        score += 1.1
    if 7 <= sig['ac'] <= 10:
        score += 1.2
    if gap['small_gaps'] == 0:
        score += 0.8
    if gap['wide_gaps'] == 0:
        score += 0.6
    return round(max(70.0, min(99.4, score)), 1)

def _rc42_detail(combo, st, mode, ext=None, profile=None):
    ext = ext or _ai_v1_window_stats(st, 300)
    profile = profile or _ai_v1_profile(st, mode)[0]
    detail = _ai_v1_detail(combo, st, mode, ext, profile)
    combo = sorted(parse_nums(combo))
    sig = _ai_v1_signature(combo)
    gap = _rc42_gap_signature(combo)
    digits, dc = _rc42_end_digits(combo)
    score = _rc42_adjusted_score(combo, st, mode, ext, profile)
    tags = list(detail.get('tags') or [])
    for tag in ['RC4-2 고품질 필터', '끝수 5개 이상 분산', '포트폴리오 중복 제한']:
        if tag not in tags:
            tags.append(tag)
    detail.update({
        'score': score,
        'ai_score': score,
        'vip_score': score,
        'grade': 'VIP' if score >= 94 else 'PREMIUM' if score >= 89 else 'STANDARD',
        'star': '★★★★★' if score >= 94 else '★★★★☆' if score >= 89 else '★★★★',
        'tags': tags[:6],
        'reason_text': ' · '.join(tags[:5]),
        'gap_min': gap['min_gap'],
        'gap_max': gap['max_gap'],
        'end_digit_diversity': len(set(digits)),
        'end_digit_counts': dict(dc),
        'quality_rule': '홀짝·저중고·끝수·AC·합계·간격·연속수·중복패턴 RC4-2 필터 통과',
        'engine_version': AI_ENGINE_RC42_VERSION,
        'v2_reason': 'RC4-2는 후보를 대량 생성한 뒤 끝수 분산, 근접/광역 간격, 패턴 반복, 페어 반복, 조합 간 중복을 추가로 제한합니다.',
    })
    return detail

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced'):
    """RC4-2: AI 후보 생성 + 고품질 패턴 필터 + 포트폴리오 중복 제한."""
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
    past = {tuple(sorted(d['numbers'])) for d in st.get('draws', []) if len(d.get('numbers', [])) == 6}
    buckets = {
        'hot': [n for n in ext['hot300'][:20] if n in pool],
        'cold': [n for n in ext['cold300'][:20] if n in pool],
        'overdue': [n for n in ext['overdue300'][:20] if n in pool],
        'mid': [n for n in ext['mid300'][:24] if n in pool],
        'all': pool[:],
    }
    if mode == 'aggressive':
        plans = [['hot','hot','mid','overdue','all','cold'], ['hot','mid','all','overdue','all','all'], ['hot','cold','overdue','all','all','mid']]
    elif mode == 'conservative':
        plans = [['mid','mid','cold','overdue','all','all'], ['cold','overdue','mid','hot','all','all'], ['mid','cold','all','all','overdue','all']]
    else:
        plans = [['hot','cold','overdue','mid','all','all'], ['hot','mid','cold','overdue','all','all'], ['mid','hot','overdue','all','cold','all']]
    candidates = []
    seen = set()
    tries = 0
    needed = max(6200, target * 520)
    max_tries = max(125000, needed * 24)
    while len(candidates) < needed and tries < max_tries:
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
        if arr in seen:
            continue
        ok, reason = _rc42_combo_ok(arr, past=past, fixed_set=fixed_set)
        if not ok:
            continue
        seen.add(arr)
        candidates.append((_rc42_adjusted_score(arr, st, mode, ext, profile), list(arr)))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    usage = collections.Counter()
    pair_usage = collections.Counter()
    pattern_usage = collections.Counter()
    def can_add(combo, max_number_use, max_pair_use, max_overlap, max_pattern_use):
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        pattern = _rc42_pattern_key(combo)
        if any(usage[n] >= max_number_use for n in combo if n not in fixed_set):
            return False
        if any(pair_usage[p] >= max_pair_use for p in pairs):
            return False
        if pattern_usage[pattern] >= max_pattern_use:
            return False
        if not all(len(set(combo) & set(prev)) <= max_overlap for prev in selected):
            return False
        return True
    def add_combo(combo):
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        selected.append(combo)
        usage.update(combo)
        pair_usage.update(pairs)
        pattern_usage.update([_rc42_pattern_key(combo)])
    for score, combo in candidates:
        if can_add(combo, 3, 1, 3, 1):
            add_combo(combo)
        if len(selected) >= target:
            break
    if len(selected) < target:
        for score, combo in candidates:
            if combo in selected:
                continue
            if can_add(combo, 4, 2, 3, 2):
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo in selected:
                continue
            if can_add(combo, 5, 2, 4, 3):
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo not in selected:
                add_combo(combo)
            if len(selected) >= target:
                break
    details = [_rc42_detail(c, st, mode, ext, profile) for c in selected[:target]]
    details.sort(key=lambda x: -float(x.get('score') or 0))
    selected_sorted = [d['numbers'] for d in details]
    st.update(ext)
    st['ai_v1_candidates'] = len(candidates)
    st['ai_v1_attempts'] = tries
    st['engine_version'] = AI_ENGINE_RC42_VERSION
    st['rc42_portfolio'] = {
        'max_overlap': max((len(set(a) & set(b)) for i, a in enumerate(selected_sorted) for b in selected_sorted[i+1:]), default=0),
        'unique_patterns': len({_rc42_pattern_key(c) for c in selected_sorted}),
        'number_usage_max': max(usage.values()) if usage else 0,
    }
    return selected_sorted[:target], details[:target], st

def _engine_summary(details, st):
    scores = [float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    return {
        'version': AI_ENGINE_RC42_VERSION,
        'engine_version': AI_ENGINE_RC42_VERSION,
        'phase': 'RC4-2',
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('ai_v1_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'rc42_report': {
            'pipeline': '최근 10/30/50/100/300회 통계 → 가중치 후보 생성 → RC4-2 품질 필터 → 점수화 → 포트폴리오 중복 제한',
            'filters': '홀짝 2:4~4:2 / 합계 96~184 / 저중고 각 1개 이상 / AC 6~11 / 끝수 5개 이상 / 연속수 1쌍 이하 / 과도한 간격 제한',
            'portfolio': st.get('rc42_portfolio') or {},
            'summary': 'RC4-2는 번호 품질, 끝수 분산, 반복 패턴 제거, 조합 간 중복 제한을 강화한 추천 엔진입니다.'
        },
        'ai_engine_v1_report': {
            'pipeline': 'RC4-2 품질 필터가 적용된 BBLOTTO AI Engine',
            'draws_used': int(st.get('draws_used') or len(st.get('draws') or [])),
            'candidate_count': int(st.get('ai_v1_candidates') or 0),
            'attempts': int(st.get('ai_v1_attempts') or 0),
            'filters': '홀짝·합계·구간·AC·끝수·간격·연속수·과거조합 제외',
            'portfolio': '동일 번호 과사용, 동일 페어 반복, 유사 패턴 반복, 조합 간 4개 이상 중복을 제한합니다.',
            'summary': 'BBLOTTO PRO RC4-2 추천 엔진 적용 완료'
        },
        'v2_pipeline_report': {
            'pipeline': '통계 가중치 → 후보 대량 생성 → 품질 필터 → 포트폴리오 선별',
            'stage1_candidates': int(st.get('ai_v1_candidates') or 0),
            'stage2_filters': '끝수/간격/AC/구간/홀짝/연속수 필터 강화',
            'stage3_portfolio': '번호·페어·패턴 중복 제한 및 TOP3 우선 표시',
            'summary': 'RC4-2 추천번호 AI 엔진 고도화 완료'
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
        f'{round_no}회차는 RC4-2 {mode_name} 엔진으로 최근 10/30/50/100/300회 흐름을 반영했습니다.',
        f'핵심 흐름 {", ".join(map(str, hot)) if hot else "자동 분석"} / 보강 흐름 {", ".join(map(str, overdue)) if overdue else "분산 보강"} 기준입니다.',
        f'TOP3 핵심 후보 번호는 {", ".join(map(str, top_nums[:8])) if top_nums else "생성 결과 기준 자동 산출"}이며 평균 AI 점수는 {avg}점입니다.',
        '끝수 5개 이상 분산, 연속수 1쌍 이하, AC값 6~11, 조합 간 중복 제한을 적용했습니다.',
        ''
    ]
    return '\n'.join(lines)


# ===================== RC4-5 DEEP RECOMMEND ENGINE =====================
def rc45_grade_label(raw='일반'):
    v = str(raw or '일반').strip()
    alias = {
        'VIP':'1등', '다이아':'1등', '다이아몬드':'1등', '프리미엄':'2등',
        '1등관리':'1등', '1등 관리':'1등', '2등관리':'2등', '2등 관리':'2등',
        '일반관리':'일반', '일반 관리':'일반'
    }
    return alias.get(v, v if v in ('1등','2등','일반') else '일반')

def rc45_grade_strength_text(grade='일반'):
    g = rc45_grade_label(grade)
    if g == '1등':
        return '고강도 심층분석: 후보군 확대, 페어 반복 억제, 끝수·구간·AC·중복 제한을 가장 엄격하게 적용'
    if g == '2등':
        return '중강도 심층분석: 최근 흐름과 미출현 보강을 균형 반영하고 유사 조합을 제한'
    return '표준 심층분석: 안정형 균형 조합 중심으로 과한 패턴과 중복을 제한'

def _rc45_grade_params(grade='일반'):
    g = rc45_grade_label(grade)
    if g == '1등':
        return {'needed': 820, 'base': 9200, 'tries': 30, 'first': (2,1,3,1), 'second': (3,1,3,2), 'third': (4,2,3,2), 'score_boost': 1.8}
    if g == '2등':
        return {'needed': 660, 'base': 7600, 'tries': 26, 'first': (3,1,3,1), 'second': (4,2,3,2), 'third': (5,2,4,3), 'score_boost': 1.0}
    return {'needed': 520, 'base': 6200, 'tries': 24, 'first': (4,2,4,2), 'second': (5,2,4,3), 'third': (6,3,4,4), 'score_boost': 0.3}

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced', member_grade='일반'):
    """RC4-5: 회원 등급(1등/2등/일반)별 추천 강도 차등 + 심층분석 후보 선별."""
    member_grade = rc45_grade_label(member_grade)
    gp = _rc45_grade_params(member_grade)
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
    for n in range(1, 46):
        if n in (ext.get('hot300') or [])[:12]:
            profile[n] = profile.get(n, 1) + gp['score_boost']
        if n in (ext.get('overdue300') or [])[:12]:
            profile[n] = profile.get(n, 1) + gp['score_boost'] * 0.75
        if member_grade == '1등' and n in (ext.get('mid300') or [])[:16]:
            profile[n] = profile.get(n, 1) + 0.6
    past = {tuple(sorted(d['numbers'])) for d in st.get('draws', []) if len(d.get('numbers', [])) == 6}
    buckets = {
        'hot': [n for n in ext['hot300'][:22] if n in pool],
        'cold': [n for n in ext['cold300'][:22] if n in pool],
        'overdue': [n for n in ext['overdue300'][:22] if n in pool],
        'mid': [n for n in ext['mid300'][:26] if n in pool],
        'all': pool[:],
    }
    if member_grade == '1등':
        plans = [['hot','overdue','mid','cold','all','all'], ['hot','mid','overdue','all','cold','all'], ['mid','hot','overdue','cold','all','all']]
    elif member_grade == '2등':
        plans = [['hot','cold','overdue','mid','all','all'], ['mid','hot','overdue','all','cold','all'], ['cold','mid','hot','all','overdue','all']]
    elif mode == 'aggressive':
        plans = [['hot','hot','mid','overdue','all','cold'], ['hot','mid','all','overdue','all','all'], ['hot','cold','overdue','all','all','mid']]
    elif mode == 'conservative':
        plans = [['mid','mid','cold','overdue','all','all'], ['cold','overdue','mid','hot','all','all'], ['mid','cold','all','all','overdue','all']]
    else:
        plans = [['hot','cold','overdue','mid','all','all'], ['hot','mid','cold','overdue','all','all'], ['mid','hot','overdue','all','cold','all']]
    candidates = []
    seen = set()
    tries = 0
    needed = max(gp['base'], target * gp['needed'])
    max_tries = max(125000, needed * gp['tries'])
    while len(candidates) < needed and tries < max_tries:
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
        if arr in seen:
            continue
        ok, reason = _rc42_combo_ok(arr, past=past, fixed_set=fixed_set)
        if not ok:
            continue
        seen.add(arr)
        score = _rc42_adjusted_score(arr, st, mode, ext, profile)
        spread_bonus = len({n % 10 for n in arr}) * (0.12 if member_grade == '1등' else 0.08)
        section_bonus = len({0 if n <= 15 else 1 if n <= 30 else 2 for n in arr}) * (0.18 if member_grade == '1등' else 0.10)
        candidates.append((score + spread_bonus + section_bonus, list(arr)))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    usage = collections.Counter()
    pair_usage = collections.Counter()
    pattern_usage = collections.Counter()
    def can_add(combo, max_number_use, max_pair_use, max_overlap, max_pattern_use):
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        pattern = _rc42_pattern_key(combo)
        if any(usage[n] >= max_number_use for n in combo if n not in fixed_set):
            return False
        if any(pair_usage[p] >= max_pair_use for p in pairs):
            return False
        if pattern_usage[pattern] >= max_pattern_use:
            return False
        if not all(len(set(combo) & set(prev)) <= max_overlap for prev in selected):
            return False
        return True
    def add_combo(combo):
        selected.append(combo)
        usage.update(combo)
        pair_usage.update([tuple(sorted(p)) for p in itertools.combinations(combo, 2)])
        pattern_usage.update([_rc42_pattern_key(combo)])
    for score, combo in candidates:
        if can_add(combo, *gp['first']):
            add_combo(combo)
        if len(selected) >= target:
            break
    if len(selected) < target:
        for score, combo in candidates:
            if combo in selected:
                continue
            if can_add(combo, *gp['second']):
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo in selected:
                continue
            if can_add(combo, *gp['third']):
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo not in selected:
                add_combo(combo)
            if len(selected) >= target:
                break
    details = [_rc42_detail(c, st, mode, ext, profile) for c in selected[:target]]
    for d in details:
        d['member_grade'] = member_grade
        d['grade_strength'] = rc45_grade_strength_text(member_grade)
        d['engine_version'] = 'RC4-5_DEEP_GRADE_ENGINE'
    details.sort(key=lambda x: -float(x.get('score') or 0))
    selected_sorted = [d['numbers'] for d in details]
    st.update(ext)
    st['ai_v1_candidates'] = len(candidates)
    st['ai_v1_attempts'] = tries
    st['engine_version'] = 'RC4-5_DEEP_GRADE_ENGINE'
    st['member_grade'] = member_grade
    st['grade_strength'] = rc45_grade_strength_text(member_grade)
    st['rc42_portfolio'] = {
        'max_overlap': max((len(set(a) & set(b)) for i, a in enumerate(selected_sorted) for b in selected_sorted[i+1:]), default=0),
        'unique_patterns': len({_rc42_pattern_key(c) for c in selected_sorted}),
        'number_usage_max': max(usage.values()) if usage else 0,
    }
    return selected_sorted[:target], details[:target], st

def _engine_summary(details, st):
    scores = [float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    grade = rc45_grade_label(st.get('member_grade') or (details[0].get('member_grade') if details else '일반'))
    return {
        'version': 'RC4-5_DEEP_GRADE_ENGINE',
        'engine_version': 'RC4-5_DEEP_GRADE_ENGINE',
        'phase': 'RC4-5',
        'member_grade': grade,
        'grade_strength': rc45_grade_strength_text(grade),
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('ai_v1_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'rc45_report': {
            'pipeline': '최근 10/30/50/100/300회 통계 → 등급별 후보군 가중치 → 심층 품질 필터 → 포트폴리오 중복 제한 → 최종 점수 선별',
            'grade_policy': '회원 등급은 1등/2등/일반으로 운영하며 등급별 후보 수, 중복 제한, 조합 선별 강도를 다르게 적용합니다.',
            'filters': '홀짝·합계·저중고 구간·AC값·끝수·간격·연속수·과거 동일 조합·페어 반복 제한',
            'portfolio': st.get('rc42_portfolio') or {},
            'summary': '최근 흐름과 누적 통계를 함께 반영한 심층 추천 결과입니다.'
        }
    }

def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
    """회원용 3~5줄 분석 문구. 개발자/엔진명 문구는 노출하지 않고, 생성 결과에 따라 문장 조합이 달라지도록 구성합니다."""
    import hashlib
    details = details or []
    engine = _engine_summary(details, st)
    grade = engine.get('member_grade') or rc45_grade_label(st.get('member_grade'))
    best = sorted(details, key=lambda x: -float(x.get('score') or 0))[:3]
    top_nums = []
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
    combos = [d.get('numbers', []) for d in details if d.get('numbers')]
    flat = [int(n) for c in combos for n in c if str(n).isdigit()]
    low = sum(1 for n in flat if 1 <= n <= 15); mid = sum(1 for n in flat if 16 <= n <= 30); high = sum(1 for n in flat if 31 <= n <= 45)
    odd = sum(1 for n in flat if n % 2 == 1); even = len(flat) - odd
    focus = []
    if mode == 'conservative': focus.append('안정형')
    elif mode == 'aggressive': focus.append('공격형')
    else: focus.append('균형형')
    if hot: focus.append('최근흐름')
    if overdue: focus.append('보강후보')
    if abs(odd-even) <= max(2, len(flat)//8): focus.append('홀짝균형')
    if max(low, mid, high) - min(low, mid, high) <= max(2, len(flat)//10): focus.append('구간분산')

    seed_src = f"{round_no}|{mode}|{grade}|{core_text}|{hot_text}|{sub_text}|{sum(flat)}|{len(details)}"
    seed = int(hashlib.sha256(seed_src.encode('utf-8')).hexdigest()[:12], 16)
    def pick(arr, salt=0):
        return arr[(seed + salt) % len(arr)]

    openers = {
        '균형형': [
            f'{round_no}회차는 최근 흐름과 누적 데이터를 함께 비교해 안정적인 분포의 조합으로 구성했습니다.',
            f'{round_no}회차는 특정 번호대에 치우치지 않도록 전체 흐름을 기준으로 조합을 선별했습니다.',
            f'이번 회차는 최근 당첨 흐름과 장기 통계를 함께 반영해 균형 중심으로 구성했습니다.',
            f'번호 분포와 최근 출현 흐름을 함께 검토해 {round_no}회차 추천 조합을 구성했습니다.'
        ],
        '안정형': [
            f'{round_no}회차는 과도한 변동보다 안정적인 번호 흐름을 우선해 조합을 선별했습니다.',
            f'이번 회차는 최근 흐름 안에서 무리한 편중을 줄이고 안정성을 높이는 방향으로 구성했습니다.',
            f'{round_no}회차는 누적 통계와 반복 패턴을 함께 살펴 안정적인 조합을 중심으로 선별했습니다.'
        ],
        '공격형': [
            f'{round_no}회차는 최근 흐름 변화가 큰 구간을 함께 반영해 적극적인 조합으로 구성했습니다.',
            f'이번 회차는 출현 가능성이 높아진 후보를 중심으로 변화를 준 조합을 선별했습니다.',
            f'{round_no}회차는 최근 강세 번호와 보강 후보를 함께 반영해 흐름 전환 가능성을 고려했습니다.'
        ]
    }
    middles = [
        f'주요 후보는 {core_text}이며, 최근 흐름 번호와 보강 후보를 함께 배분했습니다.',
        f'최근 흐름 번호({hot_text})와 보강 후보({sub_text})를 조합해 한쪽으로 쏠리지 않게 맞췄습니다.',
        f'핵심 후보군은 {core_text} 중심이며, 전체 조합 간 중복 가능성을 낮추는 방향으로 정리했습니다.',
        f'번호별 출현 흐름을 비교해 {hot_text} 계열과 {sub_text} 계열을 균형 있게 반영했습니다.',
        '최근 반복된 패턴은 일부만 반영하고, 새롭게 움직일 가능성이 있는 번호를 함께 보강했습니다.',
        '당첨 흐름이 강한 번호와 장기적으로 보강이 필요한 번호를 나누어 조합에 배치했습니다.'
    ]
    balances = [
        '홀짝 비율과 저·중·고 구간 분포를 함께 맞춰 전체적인 안정성을 높였습니다.',
        '끝수 흐름과 번호 간 간격을 함께 확인해 비슷한 형태의 조합이 반복되지 않도록 조정했습니다.',
        '연속수와 반복 패턴은 필요한 범위 안에서만 반영해 조합 간 차이를 살렸습니다.',
        '구간 분산과 번호 간 연결성을 함께 고려해 조합별 완성도를 높였습니다.',
        '최근 회차와 지나치게 유사한 구성은 줄이고, 조합별 다양성을 확보했습니다.',
        f'{mode_name} 기준에 맞춰 번호대, 끝수, 반복 흐름을 함께 점검했습니다.'
    ]
    closers = [
        '전체적으로 최근 데이터와 누적 통계를 함께 고려한 심층 추천 결과입니다.',
        '이번 추천은 안정성과 변화 가능성을 함께 반영한 구성입니다.',
        '단순 빈도보다 번호 간 균형과 최근 흐름을 함께 본 추천입니다.',
        '회원별 추천 이력과 중복 가능성까지 고려해 최종 조합을 정리했습니다.',
        '최근 흐름을 유지하면서도 새로운 출현 가능성을 함께 고려했습니다.'
    ]
    opener_pool = openers.get(focus[0], openers['균형형'])
    lines = [pick(opener_pool, 1), pick(middles, 7), pick(balances, 13)]
    if (seed % 3) != 0:
        lines.append(pick(closers, 19))
    # 3~4줄 유지, 중복 문장 제거
    clean = []
    for line in lines:
        if line and line not in clean:
            clean.append(line)
    return '\n'.join(clean[:4])
# ===================== /RC4-5 DEEP RECOMMEND ENGINE =====================

# ===================== RC5-5 RECOMMEND ENGINE UPGRADE =====================
# 추천번호 생성 품질 강화: 등급별 후보 강도, 최근 추천 중복 방지, 조합별 다양성 강화.
RC55_ENGINE_VERSION = 'RC7-29_GRADE_TIER_ENGINE'

def _rc55_recent_recommendation_combos(member_id=None, limit=180):
    """최근 생성 이력에서 추천 조합을 가져와 동일/유사 조합 반복을 줄입니다."""
    out = []
    try:
        with con() as c:
            cols = table_cols(c, 'recommendations')
            if 'numbers' not in cols:
                return out
            if member_id and 'member_id' in cols:
                rs = c.execute('SELECT numbers FROM recommendations WHERE member_id=? ORDER BY id DESC LIMIT ?', (member_id, limit)).fetchall()
            else:
                rs = c.execute('SELECT numbers FROM recommendations ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            for r in rs:
                try:
                    data = json.loads(r['numbers'] or '[]')
                except Exception:
                    data = []
                if isinstance(data, list):
                    for item in data:
                        nums = item.get('numbers') if isinstance(item, dict) else item
                        nums = parse_nums(nums)
                        if len(nums) == 6:
                            out.append(tuple(sorted(nums)))
                if len(out) >= limit:
                    break
    except Exception:
        return []
    return out[:limit]

def _rc55_too_close_to_history(combo, history, max_overlap=4):
    s = set(parse_nums(combo))
    for h in history or []:
        hs = set(parse_nums(h))
        if len(s & hs) > max_overlap:
            return True
    return False

def _rc55_combo_quality_bonus(combo, st, ext, usage=None, member_grade='일반'):
    nums = sorted(parse_nums(combo))
    sig = _ai_v1_signature(nums)
    digits = [n % 10 for n in nums]
    decade = [sum(1 for n in nums if lo <= n <= hi) for lo, hi in [(1,9),(10,19),(20,29),(30,39),(40,45)]]
    bonus = 0.0
    # 가장 안정적인 합계/AC/구간에 가산점
    if 115 <= sig.get('sum', 0) <= 170:
        bonus += 1.2
    if 7 <= sig.get('ac', 0) <= 10:
        bonus += 1.1
    if sig.get('odd') in (2, 3, 4):
        bonus += 0.8
    if len(set(digits)) >= 5:
        bonus += 0.9
    if max(decade or [0]) <= 2:
        bonus += 0.7
    # 최근 추천에서 과사용된 번호는 감점해 회원에게 비슷한 느낌이 반복되지 않게 함
    if usage:
        bonus -= sum(max(0, usage.get(n, 0) - 1) * 0.18 for n in nums)
    g = rc45_grade_label(member_grade)
    if g == '1등':
        bonus += 1.8
    elif g == '2등':
        bonus += 0.9
    return bonus


def _rc729_engine_name(grade='일반'):
    g = rc45_grade_label(grade)
    if g == '1등':
        return 'AI MASTER'
    if g == '2등':
        return 'AI PREMIUM'
    return 'AI BASIC'

def _rc729_grade_score(base_score, grade='일반'):
    """RC7-29: 등급별 점수 구간을 분리합니다.
    일반은 90~94점대, 2등은 94~97점대, 1등은 97~99점대로 표시해
    화면에서 등급별 엔진 차이가 확실히 보이도록 합니다.
    """
    try:
        base = float(base_score or 0)
    except Exception:
        base = 85.0
    # 기존 엔진 점수를 0~1 값으로 정규화하여 등급 구간 안에서 상대 품질을 유지
    norm = max(0.0, min(1.0, (base - 70.0) / 29.7))
    g = rc45_grade_label(grade)
    if g == '1등':
        lo, hi = 97.0, 99.2
    elif g == '2등':
        lo, hi = 94.0, 96.8
    else:
        lo, hi = 90.0, 93.8
    return round(lo + (hi - lo) * norm, 1)

def _rc729_grade_tags(grade='일반'):
    g = rc45_grade_label(grade)
    if g == '1등':
        return ['1등 전용', 'AI MASTER', '상위 후보 선별']
    if g == '2등':
        return ['2등 전용', 'AI PREMIUM', '강화 후보 선별']
    return ['일반 전용', 'AI BASIC', '기본 균형 선별']

def _rc55_grade_params(grade='일반'):
    # RC7-29: 1등/2등/일반 3단계만 사용하고 등급별 후보 선별 강도를 분리합니다.
    g = rc45_grade_label(grade)
    if g == '1등':
        return {
            'base': 2200, 'mult': 220, 'tries': 14,
            'first': (2, 1, 3, 1), 'second': (3, 1, 3, 2), 'third': (4, 2, 3, 3),
            'history_overlap': 4, 'hot_boost': 3.2, 'overdue_boost': 2.15, 'mid_boost': 1.25,
        }
    if g == '2등':
        return {
            'base': 1650, 'mult': 165, 'tries': 11,
            'first': (3, 1, 3, 1), 'second': (4, 2, 3, 2), 'third': (5, 2, 4, 3),
            'history_overlap': 4, 'hot_boost': 2.25, 'overdue_boost': 1.55, 'mid_boost': 0.8,
        }
    return {
        'base': 1000, 'mult': 120, 'tries': 9,
        'first': (4, 2, 4, 2), 'second': (5, 2, 4, 3), 'third': (6, 3, 4, 4),
        'history_overlap': 5, 'hot_boost': 1.15, 'overdue_boost': 0.75, 'mid_boost': 0.25,
    }

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced', member_grade='일반', member_id=None):
    """RC5-5: 추천번호 생성 엔진 업그레이드.
    - 1등/2등/일반 등급별 후보군 강도 차등
    - 최근 추천 이력과 유사한 조합 제한
    - 번호/페어/패턴 중복 제한 강화
    - 조합 간 분산성과 안정성 동시 반영
    """
    member_grade = rc45_grade_label(member_grade)
    gp = _rc55_grade_params(member_grade)
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
    hot = ext.get('hot300') or []
    cold = ext.get('cold300') or []
    overdue = ext.get('overdue300') or []
    mid = ext.get('mid300') or []
    # 등급별 가중치 강화
    for n in range(1, 46):
        if n in hot[:14]:
            profile[n] = profile.get(n, 1) + gp['hot_boost']
        if n in overdue[:14]:
            profile[n] = profile.get(n, 1) + gp['overdue_boost']
        if n in mid[:18]:
            profile[n] = profile.get(n, 1) + gp['mid_boost']
        if n in cold[:10] and member_grade == '1등':
            profile[n] = profile.get(n, 1) + 0.35

    past_draws = {tuple(sorted(d['numbers'])) for d in st.get('draws', []) if len(d.get('numbers', [])) == 6}
    recent_history = _rc55_recent_recommendation_combos(member_id=member_id, limit=220)
    recent_usage = collections.Counter(n for combo in recent_history[:80] for n in combo)

    buckets = {
        'hot': [n for n in hot[:24] if n in pool],
        'cold': [n for n in cold[:24] if n in pool],
        'overdue': [n for n in overdue[:24] if n in pool],
        'mid': [n for n in mid[:28] if n in pool],
        'low': [n for n in range(1, 16) if n in pool],
        'middle': [n for n in range(16, 31) if n in pool],
        'high': [n for n in range(31, 46) if n in pool],
        'all': pool[:],
    }
    # 다양한 계획을 섞어 매번 후보군 성격이 달라지도록 구성
    plans = [
        ['hot','cold','overdue','mid','all','all'],
        ['hot','mid','overdue','low','middle','high'],
        ['mid','hot','cold','overdue','all','all'],
        ['low','middle','high','hot','overdue','all'],
        ['cold','mid','hot','all','overdue','all'],
        ['overdue','hot','middle','high','low','all'],
    ]
    if member_grade == '1등':
        plans += [
            ['hot','overdue','mid','cold','low','high'],
            ['hot','hot','overdue','mid','middle','all'],
            ['overdue','mid','hot','cold','all','all'],
        ]
    elif member_grade == '2등':
        plans += [
            ['hot','cold','overdue','mid','middle','all'],
            ['mid','hot','overdue','low','high','all'],
        ]
    if mode == 'aggressive':
        plans += [['hot','hot','overdue','high','all','all'], ['hot','mid','high','overdue','all','all']]
    elif mode == 'conservative':
        plans += [['mid','mid','cold','middle','all','all'], ['cold','overdue','mid','low','middle','all']]

    candidates = []
    seen = set()
    tries = 0
    needed = max(gp['base'], target * gp['mult'])
    max_tries = max(9000, needed * gp['tries'])
    while len(candidates) < needed and tries < max_tries:
        tries += 1
        nums = set(fixed_set)
        plan = random.choice(plans)[:]
        random.shuffle(plan)
        for b in plan:
            if len(nums) >= 6:
                break
            usable = [n for n in buckets.get(b, pool) if n not in nums]
            if usable:
                nums.update(_weighted_pick(usable, [profile.get(n, 1) for n in usable], 1))
        while len(nums) < 6:
            usable = [n for n in pool if n not in nums]
            nums.update(_weighted_pick(usable, [profile.get(n, 1) for n in usable], 1))
        arr = tuple(sorted(nums))
        if arr in seen or arr in past_draws:
            continue
        if _rc55_too_close_to_history(arr, recent_history, max_overlap=gp['history_overlap']):
            continue
        ok, _reason = _rc42_combo_ok(arr, past=past_draws, fixed_set=fixed_set)
        if not ok:
            continue
        seen.add(arr)
        base_score = _rc42_adjusted_score(arr, st, mode, ext, profile)
        score = base_score + _rc55_combo_quality_bonus(arr, st, ext, recent_usage, member_grade)
        candidates.append((round(max(70.0, min(99.7, score)), 1), list(arr)))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    usage = collections.Counter()
    pair_usage = collections.Counter()
    pattern_usage = collections.Counter()

    def can_add(combo, max_number_use, max_pair_use, max_overlap, max_pattern_use):
        pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
        pattern = _rc42_pattern_key(combo)
        if any(usage[n] >= max_number_use for n in combo if n not in fixed_set):
            return False
        if any(pair_usage[p] >= max_pair_use for p in pairs):
            return False
        if pattern_usage[pattern] >= max_pattern_use:
            return False
        if not all(len(set(combo) & set(prev)) <= max_overlap for prev in selected):
            return False
        return True

    def add_combo(combo):
        selected.append(combo)
        usage.update(combo)
        pair_usage.update([tuple(sorted(p)) for p in itertools.combinations(combo, 2)])
        pattern_usage.update([_rc42_pattern_key(combo)])

    for limits in (gp['first'], gp['second'], gp['third'], (6, 3, 4, 5)):
        if len(selected) >= target:
            break
        for score, combo in candidates:
            if combo in selected:
                continue
            if can_add(combo, *limits):
                add_combo(combo)
            if len(selected) >= target:
                break
    if len(selected) < target:
        for score, combo in candidates:
            if combo not in selected:
                add_combo(combo)
            if len(selected) >= target:
                break

    details = [_rc42_detail(c, st, mode, ext, profile) for c in selected[:target]]
    # 실제 최종 점수도 RC5-6 빠른 엔진 기준으로 재보정
    for d in details:
        nums = d.get('numbers') or []
        raw_score = float(d.get('score') or 0) + _rc55_combo_quality_bonus(nums, st, ext, recent_usage, member_grade)
        score = _rc729_grade_score(raw_score, member_grade)
        d['raw_score'] = round(max(70.0, min(99.7, raw_score)), 1)
        d['score'] = d['ai_score'] = d['vip_score'] = score
        d['member_grade'] = member_grade
        d['grade_strength'] = rc45_grade_strength_text(member_grade)
        d['engine_version'] = RC55_ENGINE_VERSION
        d['engine_label'] = _rc729_engine_name(member_grade)
        d['grade'] = '1등' if member_grade == '1등' else '2등' if member_grade == '2등' else '일반'
        tags = [t for t in (d.get('tags') or []) if not str(t).startswith('RC') and str(t) not in ('VIP','PREMIUM','STANDARD')]
        for tag in _rc729_grade_tags(member_grade) + ['최근 추천 중복 제한', '구간·끝수 분산', '조합 간 유사도 제한']:
            if tag not in tags:
                tags.append(tag)
        d['tags'] = tags[:6]
        d['reason_text'] = ' · '.join(tags[:5])
        d['quality_rule'] = '홀짝·구간·끝수·간격·AC·연속수·최근 추천 유사도까지 종합 검토'
    details.sort(key=lambda x: -float(x.get('score') or 0))
    selected_sorted = [d['numbers'] for d in details]

    st.update(ext)
    st['ai_v1_candidates'] = len(candidates)
    st['ai_v1_attempts'] = tries
    st['engine_version'] = RC55_ENGINE_VERSION
    st['member_grade'] = member_grade
    st['grade_strength'] = rc45_grade_strength_text(member_grade)
    st['rc55_history_checked'] = len(recent_history)
    st['rc42_portfolio'] = {
        'max_overlap': max((len(set(a) & set(b)) for i, a in enumerate(selected_sorted) for b in selected_sorted[i+1:]), default=0),
        'unique_patterns': len({_rc42_pattern_key(c) for c in selected_sorted}),
        'number_usage_max': max(usage.values()) if usage else 0,
        'recent_history_checked': len(recent_history),
    }
    return selected_sorted[:target], details[:target], st

def _engine_summary(details, st):
    scores = [float(d.get('score') or d.get('ai_score') or d.get('vip_score') or 0) for d in (details or []) if (d.get('score') or d.get('ai_score') or d.get('vip_score'))]
    grade = rc45_grade_label(st.get('member_grade') or (details[0].get('member_grade') if details else '일반'))
    return {
        'version': RC55_ENGINE_VERSION,
        'engine_version': RC55_ENGINE_VERSION,
        'phase': 'RC7-29',
        'member_grade': grade,
        'engine_label': _rc729_engine_name(grade),
        'grade_strength': rc45_grade_strength_text(grade),
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('ai_v1_candidates') or 0),
        'selected_count': len(details or []),
        'latest_round': st.get('latest_round') or 0,
        'rc55_report': {
            'grade_policy': '1등/2등/일반 3단계 전용 · 일반 90~94점대 / 2등 94~97점대 / 1등 97~99점대 구간 분리',
            'portfolio': st.get('rc42_portfolio') or {},
            'summary': '최근 추천 이력과 유사한 조합을 줄이고 분산형 후보를 우선 선별했습니다.'
        },
        # 화면 호환용 기존 키 유지
        'rc45_report': {
            'summary': '최근 흐름과 누적 통계를 함께 반영한 심층 추천 결과입니다.',
            'portfolio': st.get('rc42_portfolio') or {},
        }
    }
# ===================== /RC5-5 RECOMMEND ENGINE UPGRADE =====================



# ---- export and audit runtime ----
# Extracted from legacy backend/app.py lines 6942-7879.
@router.get('/api/rc6-11/status')
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

@router.get('/api/rc7-1/status')
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

@router.post('/api/export/smsganda_xls')
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
@router.post('/api/export/smsganda_txt')
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

@router.get('/api/rc7-5/status')
def rc7_5_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-5 SMSGANDA TXT CP949', 'engine': DB_ENGINE, 'summary': '문자간다 TXT ANSI/CP949 주소록 생성 기본 지원', 'admin': admin.get('username')}

@router.get('/api/rc7-6/status')
def rc7_6_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-6 SMSGANDA TEMPLATE XLS', 'engine': DB_ENGINE, 'summary': '문자간다 샘플 XLS 헤더 형식(이름/휴대전화/[*1*]~[*4*]) 적용', 'admin': admin.get('username')}

@router.get('/api/rc7-8/status')
def rc7_8_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-8 SMSGANDA SEND CENTER', 'engine': DB_ENGINE, 'summary': '문자간다 [*1*]~[*4*] 문구 분리/수정/미리보기/XLS 연동 적용', 'admin': admin.get('username')}
# ===================== /RC7-5 SMSGANDA TXT CP949 EXPORT =====================

@router.get('/api/rc7-4/status')
def rc7_4_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-4 SMSGANDA HEADER FIX', 'engine': DB_ENGINE, 'summary': '문자간다 XLS 다운로드 한글 파일명 헤더 오류 수정', 'admin': admin.get('username')}

@router.get('/api/rc7-3/status')
def rc7_3_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-3 SMSGANDA REAL XLS', 'engine': DB_ENGINE, 'summary': '문자간다 샘플 기준 Excel 97-2003 BIFF .xls 주소록 생성', 'admin': admin.get('username')}
# ===================== /RC7-3 SMSGANDA REAL XLS EXPORT =====================


# ===================== RC7-2 SMSGANDA XLS EXPORT =====================
@router.get('/api/rc7-2/status')
def rc7_2_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return {'ok': True, 'version': 'RC7-2 SMSGANDA XLS', 'engine': DB_ENGINE, 'summary': '문자간다 A열 이름/B열 전화번호 XLS 업로드 파일 생성 지원', 'admin': admin.get('username')}
# ===================== /RC7-2 SMSGANDA XLS EXPORT =====================

# ===================== BBLOTTO AI V4 ENGINE FULL REPLACEMENT =====================
# 기존 API/DB/화면 구조는 유지하고 실제 추천번호 생성 엔진만 최종 오버라이드합니다.
BBLOTTO_AI_V4_ENGINE_VERSION = 'BBLOTTO_AI_V4_ENGINE_FULL_REPLACEMENT_RC8_1'


def _v4_grade_params(grade='일반'):
    # STAGE8 performance: previous settings attempted up to 120k~240k loops per click,
    # which could make Render workers appear frozen. Quality tiers remain distinct,
    # but candidate work is bounded and later scaled to the requested combination count.
    g = rc45_grade_label(grade)
    if g == '1등':
        return {'candidates': 2600, 'tries': 36000, 'score_shift': 5.8, 'max_num_use': 3, 'max_pair_use': 1, 'max_overlap': 3, 'history_overlap': 3, 'time_budget': 3.0}
    if g == '2등':
        return {'candidates': 2100, 'tries': 30000, 'score_shift': 3.2, 'max_num_use': 4, 'max_pair_use': 1, 'max_overlap': 4, 'history_overlap': 4, 'time_budget': 2.8}
    return {'candidates': 1600, 'tries': 24000, 'score_shift': 0.0, 'max_num_use': 5, 'max_pair_use': 2, 'max_overlap': 4, 'history_overlap': 5, 'time_budget': 2.5}


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
    # Requested count controls workload. Ten combinations no longer generate thousands
    # more candidates than necessary, and a hard monotonic time budget guarantees a response.
    candidate_goal = min(params['candidates'], max(400, target * 60))
    tries_limit = min(params['tries'], max(5000, target * 900))
    generation_started = time.monotonic()
    time_budget = float(params.get('time_budget') or 4.0)
    while len(candidates) < candidate_goal and tries < tries_limit:
        tries += 1
        if tries % 250 == 0 and (time.monotonic() - generation_started) >= time_budget:
            break
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
        'ai_v4_candidate_goal': candidate_goal,
        'ai_v4_time_ms': int((time.monotonic() - generation_started) * 1000),
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
    from .recommendation_engine import make_premium_combos as make_premium_combos
    from .recommendation_engine import latest_stats as latest_stats
    from .recommendation_engine import get_analysis_cache as _ai_v6_get_analysis_cache
    BBLOTTO_AI_V6_ENGINE_VERSION = 'BBLOTTO_RC10_AUTO_FULL_HISTORY'

    # 구형 V6 캐시 API 등록은 제거했습니다. 아래 V13 호환 API가 동일 경로를 단일 등록합니다.
except Exception as _v6_import_error:
    BBLOTTO_AI_V6_ENGINE_VERSION = 'BBLOTTO_AI_V6_IMPORT_FAILED'
    print('[BBLOTTO] AI V6 engine import failed:', _v6_import_error)

# 구형 V6 전체 동기화 API 등록은 제거했습니다. 아래 V13 호환 API가 동일 경로를 단일 등록합니다.


# =========================================================
# BBLOTTO AI V13 관리자 캐시 상태/재분석 API
# - AI-01~04의 persistent cache_engine을 관리자 화면에 직접 연결
# - 외부 회차 동기화와 캐시 재분석을 분리하여 0/0 무한 대기 방지
# =========================================================
try:
    from .ai.cache_engine import (
        get_analysis_cache as _ai_v13_get_cache,
        get_cache_status as _ai_v13_get_status,
        refresh_cache as _ai_v13_refresh_cache,
        request_background_refresh as _ai_v13_request_refresh,
        repair_missing_history as _ai_v13_repair_missing_history,
    )

    def _ai_v13_admin_payload(cache):
        cache = cache or {}
        actual = int(cache.get('actual_count') or cache.get('draw_count') or 0)
        latest = int(cache.get('latest_round') or 0)
        expected = int(cache.get('expected_count') or latest or actual)
        first = 0
        rr = cache.get('round_range') or [0, latest]
        if isinstance(rr, (list, tuple)) and rr:
            try: first = int(rr[0] or 0)
            except Exception: first = 0
        full = bool(cache.get('is_full_history') or (first == 1 and actual > 0 and actual == expected))
        return {
            'ok': True,
            'engine_version': cache.get('engine_version') or 'BBLOTTO_AI_CACHE_V13',
            'cache_storage': cache.get('cache_storage') or 'database+persistent-memory',
            'analysis_confirm': cache.get('analysis_confirm') or (f'1회차부터 {latest}회차까지 {actual}개 회차 분석' if actual else '분석 데이터 없음'),
            'actual_count': actual,
            'draw_count': actual,
            'expected_count': expected,
            'round_range': rr,
            'latest_round': latest,
            'target_round': latest,
            'is_full_history': full,
            'missing_rounds_count': int(cache.get('missing_rounds_count') or max(0, expected-actual)),
            'missing_rounds_sample': cache.get('missing_rounds_sample') or [],
            'cache_update_mode': cache.get('cache_update_mode') or cache.get('last_update_mode') or '-',
            'incremental_added_rounds': int(cache.get('incremental_added_rounds') or 0),
            'refresh_running': bool(cache.get('refresh_running', False)),
            'last_refresh_error': cache.get('last_refresh_error') or '',
        }

    @router.get('/api/admin/ai-v6/cache-status')
    def admin_ai_v6_cache_status(authorization: str|None = Header(default=None), target_round: int|None = None):
        require_admin(authorization)
        cache = _ai_v13_get_cache(force=False, target_round=target_round)
        return _ai_v13_admin_payload(cache)

    @router.get('/api/ai-engine/v6-cache')
    def ai_engine_v6_cache_compat(authorization: str|None = Header(default=None), target_round: int|None = None):
        require_admin(authorization)
        cache = _ai_v13_get_cache(force=False, target_round=target_round)
        return _ai_v13_admin_payload(cache)

    @router.post('/api/admin/ai-v6/full-sync-step')
    def admin_ai_v6_full_sync_step(authorization: str|None = Header(default=None), max_round: int|None = None, chunk_size: int = 25):
        require_admin(authorization)
        # 부분 DB(예: 1131~1232회만 존재)도 1회차부터 순차 복구한다.
        # 한 요청에서는 제한된 개수만 처리하여 Render 요청 제한과 화면 멈춤을 피한다.
        result = _ai_v13_repair_missing_history(max_round=max_round, chunk_size=chunk_size)
        payload = _ai_v13_admin_payload(result.get('cache') or {})
        return {
            'ok': bool(result.get('ok', True)),
            'completed': bool(result.get('completed') or payload['is_full_history']),
            'message': result.get('message') or payload['analysis_confirm'],
            'error': result.get('error') or '',
            'saved': int(result.get('saved') or 0),
            'requested': int(result.get('requested') or 0),
            'failed': int(result.get('failed') or 0),
            'failed_rounds': result.get('failed_rounds') or [],
            'remaining': int(result.get('remaining') if result.get('remaining') is not None else payload['missing_rounds_count']),
            'cache': payload,
        }

    @router.post('/api/admin/ai-v6/full-sync')
    def admin_ai_v6_full_sync(authorization: str|None = Header(default=None), max_round: int|None = None):
        require_admin(authorization)
        result = _ai_v13_repair_missing_history(max_round=max_round, chunk_size=100)
        payload = _ai_v13_admin_payload(result.get('cache') or {})
        return {'ok': True, 'completed': bool(result.get('completed') or payload['is_full_history']), 'message': result.get('message') or payload['analysis_confirm'], 'saved': int(result.get('saved') or 0), 'remaining': int(result.get('remaining') or payload['missing_rounds_count']), 'cache': payload}

    @router.post('/api/ai-engine/v6-sync-full')
    def ai_engine_v6_sync_full(authorization: str|None = Header(default=None), max_round: int|None = None):
        require_admin(authorization)
        cache = _ai_v13_refresh_cache(force=True)
        return _ai_v13_admin_payload(cache)

    @router.get('/admin/sync-full-history')
    def admin_sync_full_history_url_notice(authorization: str|None = Header(default=None), max_round: int|None = None):
        if not authorization:
            return {'ok': False, 'message': '관리자 화면의 AI 엔진 탭에서 캐시 상태 확인 또는 재분석 버튼을 사용해주세요.'}
        require_admin(authorization)
        cache = _ai_v13_refresh_cache(force=True)
        return _ai_v13_admin_payload(cache)
except Exception as _ai_v13_admin_cache_error:
    print('[BBLOTTO] AI V13 admin cache endpoint failed:', repr(_ai_v13_admin_cache_error))


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

# ---- final explanation and compatibility layer ----
# Extracted from legacy backend/app.py lines 7880-7985.
@router.get('/api/ai-engine/rc9-audit')
def rc9_engine_audit(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    from .recommendation_engine import rc9_audit
    return rc9_audit()




# ===================== STABLE V4.1 PORTFOLIO ENGINE UPGRADE =====================
# 기존 V4 후보 생성/필터 규칙은 유지하고, 최종 10조합은 전체 포트폴리오의
# 번호 반복·조합 중복·패턴 다양성·HOT/미출현 후보 분산을 다시 평가해 선별합니다.
_BBLOTTO_V40_MAKE_PREMIUM_COMBOS = make_premium_combos
BBLOTTO_STABLE_ENGINE_VERSION = 'BBLOTTO_STABLE_V4_1_PORTFOLIO'

def _stable41_combo_key(combo):
    return tuple(sorted(parse_nums(combo)))

def _stable41_marginal_value(combo, detail, selected, usage, pair_usage, pattern_usage, st):
    combo = list(_stable41_combo_key(combo))
    base = float((detail or {}).get('score') or (detail or {}).get('ai_score') or 0)
    value = base
    # 같은 번호와 같은 페어가 반복될수록 단계적으로 감점합니다.
    value -= sum(max(0, usage[n] - 1) * 1.15 + usage[n] * 0.42 for n in combo)
    pairs = [tuple(sorted(p)) for p in itertools.combinations(combo, 2)]
    value -= sum(pair_usage[p] * 1.35 for p in pairs)
    # 이미 선택한 조합과 4개 이상 겹치면 큰 감점, 3개 겹침도 소폭 감점합니다.
    for prev in selected:
        overlap = len(set(combo) & set(prev))
        if overlap >= 4: value -= 14.0 + (overlap-4)*8.0
        elif overlap == 3: value -= 2.8
    try:
        pkey = _rc42_pattern_key(combo)
    except Exception:
        sig = _ai_v1_signature(combo); pkey=(sig['odd'],tuple(sig['zones']),sig['sum']//10,sig['ac'])
    value -= pattern_usage[pkey] * 3.0
    # 아직 포트폴리오에 적게 반영된 최근 강세/미출현 후보에는 소폭 가산합니다.
    hot = set((st.get('hot20') or st.get('hot30') or st.get('hot100') or st.get('hot300') or [])[:12])
    overdue = set((st.get('overdue20') or st.get('overdue30') or st.get('overdue100') or st.get('overdue300') or [])[:12])
    value += sum(0.55 for n in combo if n in hot and usage[n] == 0)
    value += sum(0.40 for n in combo if n in overdue and usage[n] == 0)
    # 구간·홀짝·끝수·AC가 안정적인 조합을 최종 선별에서 한 번 더 우대합니다.
    sig = _ai_v1_signature(combo)
    if sig['odd'] == 3: value += 0.9
    if max(sig['zones']) == 2: value += 0.8
    if len({n % 10 for n in combo}) == 6: value += 0.7
    if 7 <= sig['ac'] <= 10: value += 0.6
    if 115 <= sig['sum'] <= 170: value += 0.5
    return value

def make_premium_combos(count=10, fixed='', excluded='', mode='balanced', member_grade='일반', member_id=None):
    target = max(1, min(50, int(count or 10)))
    sample_count = min(50, max(target, 18 if target <= 10 else target + min(10, target)))
    combos, details, st = _BBLOTTO_V40_MAKE_PREMIUM_COMBOS(
        sample_count, fixed, excluded, mode, member_grade, member_id=member_id
    )
    detail_map = {_stable41_combo_key(d.get('numbers') or []): d for d in details or []}
    pool = []
    for combo in combos or []:
        key = _stable41_combo_key(combo)
        if len(key) == 6 and key not in [x[0] for x in pool]:
            pool.append((key, detail_map.get(key, {'numbers': list(key), 'score': 0})))
    selected=[]; selected_details=[]
    usage=collections.Counter(); pair_usage=collections.Counter(); pattern_usage=collections.Counter()
    while pool and len(selected) < target:
        ranked=[]
        for key, detail in pool:
            ranked.append((_stable41_marginal_value(key, detail, selected, usage, pair_usage, pattern_usage, st), key, detail))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        _value, key, detail = ranked[0]
        selected.append(list(key)); selected_details.append(detail)
        usage.update(key); pair_usage.update(tuple(sorted(p)) for p in itertools.combinations(key,2))
        try: pattern_usage.update([_rc42_pattern_key(key)])
        except Exception:
            sig=_ai_v1_signature(key); pattern_usage.update([(sig['odd'],tuple(sig['zones']),sig['sum']//10,sig['ac'])])
        pool=[item for item in pool if item[0] != key]
    # 후보가 부족할 때만 기존 결과에서 보충합니다.
    if len(selected) < target:
        fallback, fallback_details, _ = _BBLOTTO_V40_MAKE_PREMIUM_COMBOS(target, fixed, excluded, mode, member_grade, member_id=member_id)
        fdm={_stable41_combo_key(d.get('numbers') or []):d for d in fallback_details or []}
        for combo in fallback:
            key=_stable41_combo_key(combo)
            if len(key)==6 and list(key) not in selected:
                selected.append(list(key)); selected_details.append(fdm.get(key, {'numbers':list(key),'score':0}))
            if len(selected)>=target: break
    st['engine_version']=BBLOTTO_STABLE_ENGINE_VERSION
    st['stable41_sample_count']=len(combos or [])
    st['stable41_unique_numbers']=len(usage)
    st['stable41_max_number_use']=max(usage.values(), default=0)
    st['stable41_max_pair_use']=max(pair_usage.values(), default=0)
    for d in selected_details:
        d['engine_version']=BBLOTTO_STABLE_ENGINE_VERSION
        d['quality_rule']='후보 대량 선별 후 번호 반복, 조합 중복, 패턴 다양성, 최근 강세/미출현 후보 분산을 포트폴리오 단위로 재검토'
    return selected[:target], selected_details[:target], st

# ===================== /STABLE V4.1 PORTFOLIO ENGINE UPGRADE =====================

# ===================== RC11 EXPLAINABLE ANALYSIS OVERRIDE =====================
try:
    from .professional_analysis_engine import build_evidence_analysis as _stable13_build_analysis, build_recommendation_analysis as _stable13_build_recommendation

    def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
        return _stable13_build_analysis(round_no, st, mode, fixed, excluded, details or [])
except Exception as _rc11_analysis_import_error:
    print('[BBLOTTO] RC11 analysis engine load failed:', repr(_rc11_analysis_import_error))
# ===================== /RC11 EXPLAINABLE ANALYSIS OVERRIDE =====================

# ===================== FULL-HISTORY FAST V12 FINAL ENGINE BINDING =====================
# 가장 마지막에 등록해 이전 단계의 호환용 엔진 재정의를 확실히 대체합니다.
try:
    from .recommendation_engine import make_premium_combos as make_premium_combos
    from .recommendation_engine import latest_stats as latest_stats
    from .recommendation_engine import get_analysis_cache as get_analysis_cache
    from .recommendation_engine import sync_official_full_history as sync_official_full_history
    from .recommendation_engine import sync_official_history_step as sync_official_history_step
    BBLOTTO_FINAL_ENGINE_VERSION = 'BBLOTTO_AI_FULL_HISTORY_FAST_V12'
except Exception as _v12_final_engine_import_error:
    print('[BBLOTTO] V12 final recommendation engine load failed:', repr(_v12_final_engine_import_error))
# ===================== /FULL-HISTORY FAST V12 FINAL ENGINE BINDING =====================

# ===================== V12 ENGINE METADATA SUMMARY =====================
def _engine_summary(details, st):
    scores = [float(d.get('display_score') if d.get('display_score') is not None else (d.get('score') or d.get('ai_score') or d.get('vip_score') or 0)) for d in (details or [])]
    scores = [s for s in scores if s]
    version = st.get('engine_version') or 'BBLOTTO_AI_FULL_HISTORY_FAST_V12'
    grade = rc45_grade_label(st.get('member_grade') or '일반')
    return {
        'version': version,
        'engine_version': version,
        'phase': 'RC6-D8.1-FULL-HISTORY-PORTFOLIO',
        'member_grade': grade,
        'engine_label': _rc729_engine_name(grade),
        'grade_strength': rc45_grade_strength_text(grade),
        'avg_score': round(sum(scores) / len(scores), 1) if scores else 0,
        'max_score': round(max(scores), 1) if scores else 0,
        'min_score': round(min(scores), 1) if scores else 0,
        'candidate_count': int(st.get('candidate_count') or 0),
        'selected_count': len(details or []),
        'latest_round': int(st.get('latest_round') or 0),
        'draw_count': int(st.get('draw_count') or 0),
        'generation_ms': float(st.get('generation_ms') or 0),
        'cache_build_ms': float(st.get('cache_build_ms') or 0),
        'analysis_confirm': st.get('analysis_confirm') or '',
        'methodology': st.get('methodology') or [],
        'summary': '1회차부터 DB 최신 회차까지 전체 이력을 캐시 분석하고, 다중 기간 흐름·미출현 간격·동반출현·조합 구조·포트폴리오 중복을 함께 평가합니다.',
    }
# ===================== /V12 ENGINE METADATA SUMMARY =====================
