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


