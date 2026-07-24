from .ai.ai_lab_activation import load_stable_profile as ai_lab_load_stable_profile
from .recommendation_verification import build_generation_verification
# Extracted from legacy backend/app.py lines 2873-3075.
@router.post('/api/generate')
def generate(req:GenerateReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    member_name=''
    member_grade='일반'
    member_id=req.member_id
    stable_lab = {}
    with con() as c:
        member_id, member_name = rc312_resolve_member(c, member_id, '')
        try:
            if member_id:
                _mg = c.execute('SELECT grade FROM members WHERE id=?', (member_id,)).fetchone()
                member_grade = rc45_grade_label(_mg['grade'] if _mg else '일반')
        except Exception:
            member_grade = '일반'
        try:
            stable_lab = ai_lab_load_stable_profile(c) or {}
        except Exception:
            stable_lab = {}
    # RC3-12: 회원을 선택하지 않은 추천은 기존 호환을 위해 허용하지만,
    # 프론트에서는 회원 선택을 안내하여 이후 당첨확인에서 '회원 선택 없음'이 나오지 않도록 합니다.
    excluded_value = req.excluded or req.exclude or ''
    safe_count=max(1, min(50, int(req.count or 10)))
    _latest_for_generation = int((latest_stats(1) or {}).get('latest_round') or 0)
    safe_round=max(1, int(req.round_no or (_latest_for_generation + 1 if _latest_for_generation else expected_lotto_round())))
    safe_mode=req.mode or 'balanced'
    combos, details, st = make_premium_combos(safe_count, req.fixed, excluded_value, safe_mode, member_grade, member_id=member_id, lab_weight_profile=(stable_lab.get('weights') or None))
    # RC7-1: 회원별 AI 엔진 V2 문구/번호 분산용 회원 시드 정보
    try:
        st['member_id'] = member_id or 0
        st['member_name'] = member_name or ''
        st['member_grade'] = member_grade
        st['ai_lab_stable_version_id'] = int(stable_lab.get('version_id') or 0)
        st['ai_lab_stable_version_name'] = stable_lab.get('version_name') or ''
        st['ai_lab_profile_name'] = stable_lab.get('profile_name') or ''
        st['ai_lab_profile_applied'] = bool(stable_lab.get('weights'))
    except Exception:
        _log_suppressed_exception("40_recommendations_sms.py:29")
    details = rc37_enrich_details(combos, details)
    combos, details = rc38_portfolio_reorder(combos, details)
    details = rc37_enrich_details(combos, details)
    # 설명 엔진은 화면에 반환되는 최종 조합과 정확히 같은 번호를 사용해야 합니다.
    # 재정렬 과정에서 detail 안의 이전 번호가 남아도 최종 combos를 기준으로 덮어씁니다.
    for combo, detail in zip(combos, details):
        if isinstance(detail, dict):
            detail['numbers'] = list(combo)
            # 조합 카드와 하단 엔진 요약은 반드시 같은 회원 등급/엔진을 표시합니다.
            detail['member_grade'] = member_grade
            detail['grade'] = member_grade
            detail['engine_label'] = _rc729_engine_name(member_grade)
            detail['grade_strength'] = rc45_grade_strength_text(member_grade)
    analysis=clean_template_text(_stable13_build_analysis(safe_round, st, safe_mode, req.fixed, excluded_value, details, combos))
    sms=clean_template_text(build_sms(member_name, safe_round, combos, analysis, details))
    engine=_engine_summary(details, st)
    engine['analysis_engine_version']='PROFESSIONAL_REASON_V2_20260720'
    engine['phase']='RC6-D8.1-FULL-HISTORY-PORTFOLIO'
    engine['ai_lab_stable_version_id']=int(stable_lab.get('version_id') or 0)
    engine['ai_lab_stable_version_name']=stable_lab.get('version_name') or ''
    engine['ai_lab_profile_id']=int(stable_lab.get('profile_id') or 0)
    engine['ai_lab_profile_name']=stable_lab.get('profile_name') or ''
    engine['ai_lab_profile_applied']=bool(stable_lab.get('weights'))
    engine['ai_lab_backtest_run_id']=int(stable_lab.get('backtest_run_id') or 0)
    recommendation_analysis=analysis
    engine['member_grade']=member_grade
    engine['grade_strength']=rc45_grade_strength_text(member_grade)
    engine['engine_label']=_rc729_engine_name(member_grade)
    engine['rc38_report']=rc38_generation_report(combos, details, safe_round, safe_mode)
    engine['top3']=rc37_top3(combos, details)
    engine['quality_guide']=f'{member_grade} 관리 기준 · 1회차부터 최신 회차까지의 기록과 실제 조합 특징을 반영한 설명형 추천'
    verification=build_generation_verification(
        round_no=safe_round, mode=safe_mode, member_grade=member_grade,
        fixed=req.fixed, excluded=excluded_value, combos=combos, details=details,
        stats=st, engine=engine,
    )
    engine['verification']=verification
    engine['verification_id']=verification['verification_id']
    for index, detail in enumerate(details):
        if isinstance(detail, dict):
            detail['verification_id']=verification['verification_id']
            detail['verification_combo_index']=index + 1
    # RC8.18: 번호 생성 단계에서는 DB에 저장하지 않습니다.
    # 추천번호 저장/보낸문자 저장을 명시적으로 실행한 경우에만 recommendations에 등록됩니다.
    log_action(admin,'GENERATE_PREVIEW_RC8_18',f'{safe_round}회차 {len(combos)}조합 미리보기 생성 · 저장 안 함',request)
    return {'id':None,'saved':False,'round_no':safe_round,'round':safe_round,'sets':combos,'combos':combos,'details':details,'top3':engine.get('top3',[]),'engine':engine,'verification':verification,'analysis':analysis,'recommendation_analysis':recommendation_analysis,'sms':sms,'member_id':member_id,'member_name':member_name,'member_notice':sms,'quality_guide':engine.get('quality_guide')}


@router.post('/api/recommendations/save')
def save_recommendation(req:SaveRecommendationReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    combos=[parse_nums(c) for c in (req.combos or [])]
    combos=[c for c in combos if len(c)==6]
    if not combos:
        raise HTTPException(400,'저장할 추천번호가 없습니다.')
    member_id=req.member_id
    member_name=(req.member_name or '').strip()
    member_grade='일반'
    with con() as c:
        member_id, resolved_name = rc312_resolve_member(c, member_id, member_name)
        member_name = resolved_name or member_name
        if member_id:
            m=c.execute('SELECT grade FROM members WHERE id=?',(member_id,)).fetchone()
            member_grade=rc45_grade_label(m['grade'] if m else '일반')
        rec_cols=table_cols(c,'recommendations')
        for col, ddl in {
            'member_id':'INTEGER','member_name':'TEXT DEFAULT ""','round_no':'INTEGER DEFAULT 0',
            'mode':'TEXT DEFAULT "balanced"','count':'INTEGER DEFAULT 0','numbers':'TEXT DEFAULT "[]"','analysis':'TEXT DEFAULT ""','sms':'TEXT DEFAULT ""',
            'created_by':'INTEGER DEFAULT 0','created_at':'TEXT DEFAULT ""',
            'avg_score':'REAL DEFAULT 0','grade':'TEXT DEFAULT "일반"','engine_json':'TEXT DEFAULT "{}"','details_json':'TEXT DEFAULT "[]"','explicit_saved':'INTEGER DEFAULT 0',
            'engine_version':'TEXT DEFAULT ""','ai_lab_version_id':'INTEGER DEFAULT 0','ai_lab_version_name':'TEXT DEFAULT ""',
            'ai_lab_profile_id':'INTEGER DEFAULT 0','ai_lab_profile_name':'TEXT DEFAULT ""','ai_lab_backtest_run_id':'INTEGER DEFAULT 0'
        }.items():
            if col not in rec_cols:
                c.execute(f'ALTER TABLE recommendations ADD COLUMN {col} {ddl}')
        rec_cols=table_cols(c,'recommendations')
        engine=req.engine or {}
        data={
            'member_id':member_id,'member_name':member_name,'round_no':max(1,int(req.round_no or 1)),
            'mode':req.mode or 'balanced','count':len(combos),'numbers':json.dumps(combos,ensure_ascii=False),
            'analysis':clean_template_text(req.analysis or ''),'sms':clean_template_text(req.sms or ''),
            'created_by':admin['id'],'created_at':now(),'avg_score':float(engine.get('avg_score') or 0),
            'grade':member_grade,'engine_json':json.dumps(engine,ensure_ascii=False),'details_json':json.dumps(req.details or [],ensure_ascii=False),'explicit_saved':1,
            'engine_version':str(engine.get('engine_version') or engine.get('version') or ''),
            'ai_lab_version_id':int(engine.get('ai_lab_stable_version_id') or 0),
            'ai_lab_version_name':str(engine.get('ai_lab_stable_version_name') or ''),
            'ai_lab_profile_id':int(engine.get('ai_lab_profile_id') or 0),
            'ai_lab_profile_name':str(engine.get('ai_lab_profile_name') or ''),
            'ai_lab_backtest_run_id':int(engine.get('ai_lab_backtest_run_id') or 0)
        }
        cols=[k for k in data if k in rec_cols]
        cur=c.execute('INSERT INTO recommendations('+','.join(cols)+') VALUES('+','.join(['?']*len(cols))+')',[data[k] for k in cols])
        rid=cur.lastrowid
        c.commit()
    log_action(admin,'SAVE_RECOMMENDATION_RC8_18',f'{data["round_no"]}회차 {len(combos)}조합 저장 · {member_name or "회원 미선택"}',request)
    return {'ok':True,'saved':True,'id':rid,'member_id':member_id,'member_name':member_name,'round_no':data['round_no'],'count':len(combos)}


@router.get('/api/recommendations')
def recommendations(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        rows=c.execute('SELECT id,member_id,member_name,round_no,mode,count,analysis,sms,created_by,created_at FROM recommendations ORDER BY id DESC LIMIT 200').fetchall()
    return [dict(r) for r in rows]

@router.get('/api/recommendations/{rec_id}')
def recommendation_detail(rec_id:int, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        r=c.execute('SELECT * FROM recommendations WHERE id=?',(rec_id,)).fetchone()
    if not r: raise HTTPException(404,'추천번호를 찾을 수 없습니다.')
    d=dict(r); d['numbers']=json.loads(d.get('numbers') or '[]')
    try: d['engine']=json.loads(d.get('engine_json') or '{}')
    except Exception: d['engine']={}
    st=latest_stats(120)
    try:
        d['details']=json.loads(d.get('details_json') or '[]')
    except Exception:
        d['details']=[]
    if not d['details']:
        d['details']=[combo_detail(c,st) for c in d['numbers']]
    d['details']=rc37_enrich_details(d.get('numbers') or [], d.get('details') or [])
    d['top3']=rc37_top3(d.get('numbers') or [], d.get('details') or [])
    d['verification']=(d.get('engine') or {}).get('verification') or {}
    return d


def get_setting_value(key, default=''):
    try:
        with con() as c:
            r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return r['value'] if r else default
    except Exception:
        return default

def normalize_phone(phone):
    return re.sub(r'[^0-9]', '', phone or '')

def send_sms_provider(phone, body):
    """V34 문자 발송 게이트웨이.
    - 기본값 mock: 실제 과금/발송 없이 성공 처리하고 발송 이력만 남김
    - http: sms_api_url/sms_api_key/sms_sender 설정이 있으면 외부 문자 API에 POST 준비
      범용 JSON {to, from, text, api_key} 형태라 실제 업체 스펙에 맞게 URL만 연결/수정 가능
    """
    phone = normalize_phone(phone)
    provider = (get_setting_value('sms_provider', 'mock') or 'mock').lower()
    if not phone:
        return {'status':'failed','provider':provider,'message':'수신번호가 없습니다.'}
    if not body.strip():
        return {'status':'failed','provider':provider,'message':'문자 내용이 없습니다.'}
    if provider in ('mock','test','demo',''):
        return {'status':'sent_mock','provider':'mock','message':'모의 발송 완료: 실제 문자는 발송되지 않았고 이력만 저장되었습니다.'}
    if provider == 'http':
        url = get_setting_value('sms_api_url', '').strip()
        api_key = get_setting_value('sms_api_key', '').strip()
        sender = normalize_phone(get_setting_value('sms_sender', ''))
        if not url or not api_key:
            return {'status':'failed','provider':'http','message':'문자 API URL 또는 API KEY가 설정되지 않았습니다.'}
        payload = json.dumps({'to':phone,'from':sender,'text':body,'api_key':api_key}, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type':'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                txt = resp.read().decode('utf-8', 'ignore')[:500]
            return {'status':'sent','provider':'http','message':txt or 'API 발송 요청 완료'}
        except Exception as e:
            return {'status':'failed','provider':'http','message':str(e)}
    return {'status':'failed','provider':provider,'message':'지원하지 않는 문자 provider입니다. mock 또는 http를 사용하세요.'}

@router.post('/api/sms')
def save_sms(req:SmsReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    name=req.member_name
    phone=req.phone
    if req.member_id:
        with con() as c:
            m=c.execute('SELECT name,phone FROM members WHERE id=?',(req.member_id,)).fetchone()
            if m:
                name=m['name'] if m['name'] else name
                phone=m['phone'] if m['phone'] else phone
    result = send_sms_provider(phone, req.body) if req.send_now else {'status':'saved','provider':get_setting_value('sms_provider','mock'),'message':'발송하지 않고 이력만 저장했습니다.'}
    sent_at = now() if result['status'] in ('sent','sent_mock') else ''
    with con() as c:
        sms_cols=table_cols(c,'sms_logs')
        for col, ddl in {
            'recommendation_id':'INTEGER DEFAULT 0','engine_version':'TEXT DEFAULT ""','ai_lab_version_id':'INTEGER DEFAULT 0',
            'ai_lab_version_name':'TEXT DEFAULT ""','ai_lab_profile_name':'TEXT DEFAULT ""','ai_lab_backtest_run_id':'INTEGER DEFAULT 0'
        }.items():
            if col not in sms_cols:
                c.execute(f'ALTER TABLE sms_logs ADD COLUMN {col} {ddl}')
        sms_cols=table_cols(c,'sms_logs')
        trace={}
        if req.recommendation_id:
            rec=c.execute('SELECT engine_version,ai_lab_version_id,ai_lab_version_name,ai_lab_profile_name,ai_lab_backtest_run_id FROM recommendations WHERE id=?',(int(req.recommendation_id),)).fetchone()
            trace=dict(rec) if rec else {}
        values={
            'member_id':req.member_id,'member_name':name,'phone':normalize_phone(phone),'round_no':req.round_no,
            'body':req.body,'combos':json.dumps(req.combos,ensure_ascii=False),'provider':result.get('provider','mock'),
            'status':result.get('status','saved'),'result_message':result.get('message',''),'sent_at':sent_at,
            'created_by':admin['id'],'created_at':now(),'recommendation_id':int(req.recommendation_id or 0),
            'engine_version':trace.get('engine_version',''),'ai_lab_version_id':int(trace.get('ai_lab_version_id') or 0),
            'ai_lab_version_name':trace.get('ai_lab_version_name',''),'ai_lab_profile_name':trace.get('ai_lab_profile_name',''),
            'ai_lab_backtest_run_id':int(trace.get('ai_lab_backtest_run_id') or 0)
        }
        cols=[k for k in values if k in sms_cols]
        cur=c.execute('INSERT INTO sms_logs('+','.join(cols)+') VALUES('+','.join(['?']*len(cols))+')',[values[k] for k in cols])
        if req.member_id:
            c.execute('UPDATE members SET last_contact_at=?, updated_at=? WHERE id=?', (now(), now(), req.member_id))
        c.commit(); sid=cur.lastrowid
    action = 'SEND_SMS' if req.send_now else 'SAVE_SMS'
    log_action(admin,action,f'{req.round_no}회차 문자 {result.get("status")}',request)
    return {
        'id': sid,
        'sms_log_id': sid,
        'recommendation_id': int(req.recommendation_id or 0),
        'engine_version': values.get('engine_version', ''),
        'ai_lab_version_id': int(values.get('ai_lab_version_id') or 0),
        'ai_lab_version_name': values.get('ai_lab_version_name', ''),
        'ai_lab_profile_name': values.get('ai_lab_profile_name', ''),
        'ai_lab_backtest_run_id': int(values.get('ai_lab_backtest_run_id') or 0),
        **result,
    }

@router.post('/api/sms_log')
def save_sms_log_alias(req:SmsReq, request:Request, authorization: str|None = Header(default=None)):
    return save_sms(req, request, authorization)

@router.get('/api/sms')
def sms_logs(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c: rows=c.execute('SELECT * FROM sms_logs ORDER BY id DESC LIMIT 200').fetchall()
    return [dict(r) for r in rows]

@router.delete('/api/sms/{sms_id}')
def delete_sms_log(sms_id:int, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        row=c.execute('SELECT id, member_id, member_name, round_no FROM sms_logs WHERE id=?',(sms_id,)).fetchone()
        if not row:
            raise HTTPException(404,'문구 이력을 찾을 수 없습니다.')
        if row['member_id']:
            assert_member_access(c, admin, row['member_id'])
        c.execute('DELETE FROM sms_logs WHERE id=?',(sms_id,))
        c.commit()
    log_action(admin,'DELETE_SMS_LOG',f"문구 이력 삭제 ID {sms_id} / {row['round_no'] or '-'}회 / {row['member_name'] or ''}",request)
    return {'ok':True,'deleted_id':sms_id}
