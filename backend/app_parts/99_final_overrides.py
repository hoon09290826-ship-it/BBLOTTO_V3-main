# Extracted from legacy backend/app.py lines 7880-7985.
@router.get('/api/ai-engine/rc9-audit')
def rc9_engine_audit(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    from .ai_engine_v7 import rc9_audit
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
    sample_count = min(50, max(target, 30 if target <= 10 else target * 3))
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
    from .analysis_engine_stable13 import build_evidence_analysis as _stable13_build_analysis, build_recommendation_analysis as _stable13_build_recommendation

    def build_analysis_text(round_no, st, mode, fixed, excluded, details=None):
        return _stable13_build_analysis(round_no, st, mode, fixed, excluded, details or [])
except Exception as _rc11_analysis_import_error:
    print('[BBLOTTO] RC11 analysis engine load failed:', repr(_rc11_analysis_import_error))
# ===================== /RC11 EXPLAINABLE ANALYSIS OVERRIDE =====================
