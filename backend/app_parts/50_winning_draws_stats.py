# Extracted from legacy backend/app.py lines 3076-3407.
@router.post('/api/win-check')
def win_check(req:WinReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    wins=parse_nums(req.win_numbers)
    if not wins:
        d=get_draw(req.round_no)
        if not d: raise HTTPException(400,'당첨번호를 입력하거나 회차를 먼저 저장하세요.')
        wins=d['numbers']; req.bonus=d['bonus']
    results=[rank_result(c,wins,req.bonus) for c in req.combos]
    with con() as c:
        for r in results:
            c.execute('INSERT INTO winning_checks(member_id,member_name,round_no,target_numbers,win_numbers,bonus,match_count,bonus_match,rank,prize,cost,profit,roi,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(req.member_id,req.member_name,req.round_no,json.dumps(r['combo']),json.dumps(wins),req.bonus,r['match_count'],int(r['bonus_match']),r['rank'],r['prize'],r['cost'],r['profit'],r['roi'],admin['id'],now()))
        c.commit()
    summary={'count':len(results),'prize':sum(r['prize'] for r in results),'cost':sum(r['cost'] for r in results),'profit':sum(r['profit'] for r in results)}
    summary['roi']=round((summary['profit']/summary['cost']*100),2) if summary['cost'] else 0
    log_action(admin,'WIN_CHECK',f'{req.round_no}회차 수익률 계산',request); return {'wins':wins,'bonus':req.bonus,'results':results,'summary':summary}

@router.get('/api/win-checks')
def win_checks(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c: rows=c.execute('SELECT * FROM winning_checks ORDER BY id DESC LIMIT 300').fetchall()
    return [dict(r) for r in rows]

@router.get('/api/draws')
def draws(limit:int=100, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    limit=max(1, min(200, int(limit or 100)))
    with con() as c: rows=c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT ?', (limit,)).fetchall()
    return [{'round_no':r['round_no'],'draw_date':r['draw_date'],'numbers':parse_nums(r['numbers']),'bonus':r['bonus']} for r in rows]



@router.get('/api/draws/search')
def search_draw(round_no:int, authorization: str|None = Header(default=None)):
    """V3.0.0 STABLE: 1회차부터 추첨 완료 최신 회차까지 회차별 당첨번호 조회.
    DB에 없으면 동행복권 공개 조회를 시도하고, 성공 시 DB에 저장합니다.
    """
    require_admin(authorization)
    try:
        r = int(round_no or 0)
    except Exception:
        raise HTTPException(400, '회차는 숫자로 입력하세요.')
    expected, completed = _rc315_expected_round_and_completed()
    if r < 1:
        raise HTTPException(400, '1회차 이상만 조회할 수 있습니다.')
    if r > completed:
        return {
            'ok': False, 'round_no': r, 'expected_round': expected, 'completed_round': completed,
            'status': 'future', 'draw_date': draw_date_for_round(r), 'numbers': [], 'bonus': 0,
            'message': f'{r}회는 아직 추첨 완료 전입니다. 현재 조회 가능한 최신 완료 회차는 {completed}회입니다.'
        }
    draw = get_draw(r)
    source = 'db'
    if not draw:
        fetched = fetch_official_lotto(r)
        if fetched:
            saved = save_draw_if_missing(fetched)
            draw = saved or fetched
            source = draw.get('source', 'official')
    if draw and len(draw.get('numbers') or []) == 6:
        return {
            'ok': True, 'round_no': r, 'expected_round': expected, 'completed_round': completed,
            'status': 'saved', 'draw_date': draw.get('draw_date') or draw_date_for_round(r),
            'numbers': parse_nums(draw.get('numbers')), 'bonus': int(draw.get('bonus') or 0),
            'source': source, 'message': f'{r}회 당첨번호를 조회했습니다.'
        }
    return {
        'ok': False, 'round_no': r, 'expected_round': expected, 'completed_round': completed,
        'status': 'missing', 'draw_date': draw_date_for_round(r), 'numbers': [], 'bonus': 0,
        'message': f'{r}회 당첨번호가 DB에 없고 자동 조회도 실패했습니다. 인터넷 연결 또는 동행복권 조회 차단 여부를 확인하세요.'
    }

@router.get('/api/draws/next')
def next_draw_round(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    expected = expected_lotto_round()
    check = resolve_draw_for_check(expected, allow_fetch=True)
    _, completed_round = _rc315_expected_round_and_completed()
    with con() as c:
        _rc315_clean_future_draws_in_conn(c)
        c.commit()
        latest=c.execute('SELECT * FROM draws WHERE round_no<=? ORDER BY round_no DESC LIMIT 1', (completed_round or 999999,)).fetchone()
    latest_obj = None
    latest_round = None
    if latest:
        latest_round = int(latest['round_no'])
        latest_obj = {'round_no':latest['round_no'], 'draw_date':latest['draw_date'], 'numbers':parse_nums(latest['numbers']), 'bonus':latest['bonus']}
    next_round = max(int(expected), int(latest_round or 0) + 1) if latest_round != expected else expected + 1
    return {
        'latest_round': latest_round,
        'expected_round': int(expected),
        'next_round': int(next_round),
        'check_round': int(check['round_no']),
        'draw_date': check.get('draw_date') or draw_date_for_round(expected),
        'draw_status': check.get('status'),
        'can_check': bool(check.get('can_check')),
        'latest': latest_obj,
        'current': {'round_no':check['round_no'], 'draw_date':check.get('draw_date',''), 'numbers':check.get('numbers',[]), 'bonus':check.get('bonus',0)} if check.get('numbers') else None,
        'check': check,
        'message': check.get('message','')
    }

@router.get('/api/draws/check-auto')
def check_draw_auto(round_no:int|None=None, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    return resolve_draw_for_check(round_no or expected_lotto_round(), allow_fetch=True)

@router.post('/api/draws/fetch-official')
def fetch_draw_official_api(req: dict, request:Request, authorization: str|None = Header(default=None)):
    """RC3-10: 운영자가 회차를 강제로 공식/캐시 조회 후 DB에 저장할 수 있는 복구 API."""
    admin = require_admin(authorization)
    r = int((req or {}).get('round_no') or expected_lotto_round())
    fetched = fetch_official_lotto(r)
    if not fetched:
        raise HTTPException(404, f'{r}회 당첨번호를 공식 API/보조 캐시에서 찾지 못했습니다. 수동 입력이 필요합니다.')
    saved = save_draw_if_missing(fetched)
    log_action(admin, 'RC3_10_FETCH_DRAW', f'{r}회 당첨번호 자동조회/저장 source={saved.get("source")}', request)
    return {'ok': True, 'version': RC3_10_VERSION, 'draw': saved, 'message': f'{r}회 당첨번호를 저장했습니다.'}

@router.post('/api/draws')
def save_draw(req:DrawReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    r, nums, bonus, expected, completed = _rc315_validate_draw_payload(req.round_no, req.numbers, req.bonus, allow_completed_only=True)
    with con() as c:
        _rc315_clean_future_draws_in_conn(c)
        c.execute('INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)',(r,req.draw_date or draw_date_for_round(r),json.dumps(nums),bonus,'manual',now()))
        c.commit()
    log_action(admin,'SAVE_DRAW',f'{r}회차 당첨번호 저장 · 완료가능최신 {completed}회',request); return {'ok':True, 'round_no':r, 'numbers':nums, 'bonus':bonus, 'completed_round':completed}


def _auto_check_round(admin, req:AutoWinReq, request:Request):
    if not int(req.round_no or 0):
        req.round_no = expected_lotto_round()
    wins=parse_nums(req.winning)
    resolved = None
    # PHASE20: 당첨번호를 입력하지 않아도 회차 기준으로 자동 조회/저장 후 확인합니다.
    if len(wins)!=6 or not int(req.bonus or 0):
        resolved = resolve_draw_for_check(req.round_no, allow_fetch=True)
        if resolved.get('numbers') and resolved.get('bonus'):
            wins = parse_nums(resolved.get('numbers'))
            req.bonus = int(resolved.get('bonus') or 0)
            req.draw_date = req.draw_date or resolved.get('draw_date','')
        else:
            raise HTTPException(400, resolved.get('message') or '당첨번호가 아직 자동 확인되지 않았습니다.')
    if len(wins)!=6:
        raise HTTPException(400,'당첨번호 6개를 입력하세요.')
    if not (1 <= int(req.bonus) <= 45):
        raise HTTPException(400,'보너스 번호를 입력하세요.')
    if int(req.bonus) in wins:
        raise HTTPException(400,'보너스 번호는 당첨번호 6개와 달라야 합니다.')
    # RC3-15: 당첨확인 저장 회차는 반드시 실제 추첨 완료 회차까지만 허용합니다.
    req.round_no, wins, req.bonus, expected_round, completed_round = _rc315_validate_draw_payload(req.round_no, wins, req.bonus, allow_completed_only=True)
    with con() as c:
        _rc315_clean_future_draws_in_conn(c)
        c.execute('INSERT OR REPLACE INTO draws(round_no,draw_date,numbers,bonus,source,updated_at) VALUES(?,?,?,?,?,?)', (req.round_no, req.draw_date or draw_date_for_round(req.round_no), json.dumps(wins), int(req.bonus), (resolved.get('source') if resolved else 'manual_auto'), now()))
        # RC4-4 개선: 공동추천/회원 미지정 추천은 당첨확인 결과에서 제외하고, 회원별로 묶어서 확인합니다.
        rec_where = 'r.round_no=? AND COALESCE(r.member_id,0)>0 AND COALESCE(r.explicit_saved,0)=1'
        rec_args = [req.round_no]
        if not is_super_admin(admin):
            rec_where += ' AND COALESCE(m.created_by,0)=?'
            rec_args.append(int(admin.get('id') or 0))
        recs = [dict(r) for r in c.execute(f'''
            SELECT r.id,
                   r.member_id,
                   COALESCE(NULLIF(r.member_name,''), m.name, '회원명 미확인') AS member_name,
                   r.round_no,
                   r.numbers
            FROM recommendations r
            INNER JOIN members m ON m.id = r.member_id
            WHERE {rec_where}
            ORDER BY m.name ASC, r.id DESC
        ''', rec_args).fetchall()]

        # RC8.19: 기존 버전에서 '복사저장/보낸문자 저장/문구이력 저장'으로 남긴 번호도
        # 당첨확인 대상으로 복구합니다. sms_logs.combos가 비어 있지 않은 기록만 사용하며,
        # 추천번호 저장 기록과 같은 조합은 회원별로 중복 제거합니다.
        sms_where = "s.round_no=? AND COALESCE(s.member_id,0)>0 AND COALESCE(s.combos,'') NOT IN ('','[]')"
        sms_args = [req.round_no]
        if not is_super_admin(admin):
            sms_where += ' AND COALESCE(m.created_by,0)=?'
            sms_args.append(int(admin.get('id') or 0))
        sms_rows = c.execute(f'''
            SELECT s.id, s.member_id,
                   COALESCE(NULLIF(s.member_name,''), m.name, '회원명 미확인') AS member_name,
                   s.round_no, s.combos AS numbers
            FROM sms_logs s
            INNER JOIN members m ON m.id=s.member_id
            WHERE {sms_where}
            ORDER BY m.name ASC, s.id DESC
        ''', sms_args).fetchall()
        recs.extend({
            'id': -int(r['id'] or 0), 'member_id': r['member_id'],
            'member_name': r['member_name'], 'round_no': r['round_no'],
            'numbers': r['numbers']
        } for r in sms_rows)

        deduped_recs=[]
        seen_saved=set()
        for rec in recs:
            try:
                parsed=[parse_nums(x) for x in json.loads(rec.get('numbers') or '[]')]
                parsed=[x for x in parsed if len(x)==6]
            except Exception:
                parsed=[]
            if not parsed:
                continue
            canonical=json.dumps(parsed, ensure_ascii=False, separators=(',',':'))
            key=(int(rec.get('member_id') or 0), canonical)
            if key in seen_saved:
                continue
            seen_saved.add(key)
            rec['numbers']=json.dumps(parsed, ensure_ascii=False)
            deduped_recs.append(rec)
        recs=deduped_recs

        # 과거 '생성만 한 조합'으로 만들어진 당첨확인 결과를 같은 회차/회원 기준으로 정리합니다.
        explicit_member_ids=sorted({int(r['member_id'] or 0) for r in recs if int(r['member_id'] or 0)>0})
        if explicit_member_ids:
            marks=','.join(['?']*len(explicit_member_ids))
            c.execute(f'DELETE FROM winning_checks WHERE round_no=? AND member_id IN ({marks})', [req.round_no, *explicit_member_ids])
        checked=[]
        member_map={}
        rank_order={'1등':1,'2등':2,'3등':3,'4등':4,'5등':5,'낙첨':9}
        for rec in recs:
            try:
                combos=json.loads(rec['numbers'] or '[]')
            except Exception:
                combos=[]
            mid=int(rec['member_id'] or 0)
            mname=rec['member_name'] or '회원명 미확인'
            group=member_map.setdefault(mid, {
                'member_id': mid,
                'member_name': mname,
                'recommendation_count': 0,
                'total_combos': 0,
                'hit_count': 0,
                'lose_count': 0,
                'total_prize': 0,
                'best_rank': '낙첨',
                'best_prize': 0,
                'combos': []
            })
            if combos:
                group['recommendation_count'] += 1
            for idx, combo in enumerate(combos, start=1):
                r=rank_result(combo, wins, int(req.bonus))
                target=json.dumps(r['combo'], ensure_ascii=False)
                old=c.execute('SELECT id FROM winning_checks WHERE round_no=? AND COALESCE(member_id,0)=COALESCE(?,0) AND target_numbers=? AND win_numbers=? AND bonus=?', (req.round_no, rec['member_id'], target, json.dumps(wins), int(req.bonus))).fetchone()
                if old:
                    c.execute('UPDATE winning_checks SET member_name=?, match_count=?, bonus_match=?, rank=?, prize=?, cost=?, profit=?, roi=?, created_by=?, created_at=? WHERE id=?', (mname, r['match_count'], int(r['bonus_match']), r['rank'], r['prize'], r['cost'], r['profit'], r['roi'], admin['id'], now(), old['id']))
                else:
                    c.execute('INSERT INTO winning_checks(member_id,member_name,round_no,target_numbers,win_numbers,bonus,match_count,bonus_match,rank,prize,cost,profit,roi,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (rec['member_id'], mname, req.round_no, target, json.dumps(wins), int(req.bonus), r['match_count'], int(r['bonus_match']), r['rank'], r['prize'], r['cost'], r['profit'], r['roi'], admin['id'], now()))
                item={'member_id':mid, 'member_name':mname, 'recommendation_id':rec['id'], 'combo_index':idx, **r}
                checked.append(item)
                group['total_combos'] += 1
                group['total_prize'] += int(r.get('prize') or 0)
                if r.get('rank') and r.get('rank') != '낙첨':
                    group['hit_count'] += 1
                else:
                    group['lose_count'] += 1
                if rank_order.get(r.get('rank','낙첨'),9) < rank_order.get(group['best_rank'],9):
                    group['best_rank'] = r.get('rank') or '낙첨'
                    group['best_prize'] = int(r.get('prize') or 0)
                group['combos'].append(item)
        c.commit()
    member_results=list(member_map.values())
    member_results.sort(key=lambda x: (rank_order.get(x.get('best_rank','낙첨'),9), -int(x.get('total_prize') or 0), x.get('member_name') or ''))
    summary={'members':len(member_results), 'recommendations':len(recs), 'checked_combos':len(checked), 'hit_members':sum(1 for m in member_results if m.get('hit_count',0)>0), 'hit_combos':sum(1 for x in checked if x.get('rank')!='낙첨'), 'lose_combos':sum(1 for x in checked if x.get('rank')=='낙첨'), 'prize':sum(x['prize'] for x in checked), 'cost':sum(x['cost'] for x in checked), 'profit':sum(x['profit'] for x in checked)}
    summary['roi']=round((summary['profit']/summary['cost']*100),2) if summary['cost'] else 0
    log_action(admin,'AUTO_WIN_CHECK',f'{req.round_no}회차 회원별 자동 당첨확인 {len(member_results)}명/{len(checked)}조합',request)
    return {'ok':True, 'round_no':req.round_no, 'wins':wins, 'bonus':int(req.bonus), 'draw_date':req.draw_date, 'auto_resolved': bool(resolved), 'summary':summary, 'member_results':member_results, 'results':checked[:300]}

@router.post('/api/check_winning')
def check_winning_alias(req:AutoWinReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return _auto_check_round(admin, req, request)

@router.post('/api/win-check-auto')
def win_check_auto(req:AutoWinReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    return _auto_check_round(admin, req, request)

@router.get('/api/stats')
def api_stats(limit:int=100, authorization: str|None = Header(default=None)):
    require_admin(authorization)
    st=latest_stats(limit)
    draws=st.get('draws',[])
    sums=[sum(d['numbers']) for d in draws]
    nums=[]
    for d in draws: nums.extend(d['numbers'])
    sections=[sum(1 for n in nums if n<=15),sum(1 for n in nums if 16<=n<=30),sum(1 for n in nums if n>=31)]
    odd=sum(1 for n in nums if n%2); even=len(nums)-odd
    pair_counter=collections.Counter()
    for d in draws:
        for a,b in itertools.combinations(d['numbers'],2):
            pair_counter[(a,b)]+=1
    return {
        'count': int(st.get('draw_count') or len(draws)),
        'display_count': len(draws),
        'limit': limit,
        'latest': draws[0] if draws else None,
        'recent_draws': draws if int(limit) <= 0 else draws[:max(100, int(limit))],
        'hot': st.get('hot', []),
        'cold': st.get('cold', []),
        'missing20': st.get('overdue', []),
        'odd': odd,
        'even': even,
        'sections': sections,
        'sum_min': min(sums) if sums else 0,
        'sum_avg': round(sum(sums)/len(sums),1) if sums else 0,
        'sum_max': max(sums) if sums else 0,
        'top_pairs': [{'pair':list(k),'count':v} for k,v in pair_counter.most_common(15)] or st.get('top_pairs', []),
        'freq': st.get('freq',{}),
        'freq100': st.get('freq100',{}),
        'engine_version': st.get('engine_version'),
        'analysis_confirm': st.get('analysis_confirm'),
        'round_range': st.get('round_range', []),
        'latest_round': st.get('latest_round', 0),
        'target_round': st.get('target_round', st.get('latest_round', 0)),
        'is_full_history': bool(st.get('is_full_history')),
        'missing_rounds_count': int(st.get('missing_rounds_count') or 0),
        'expected_count': int(st.get('expected_count') or 0),
        'actual_count': int(st.get('actual_count') or 0),
    }

def csv_response(filename, headers, rows):
    bio=io.StringIO()
    bio.write('\ufeff')
    w=csv.writer(bio); w.writerow(headers); w.writerows(rows)
    data=bio.getvalue().encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(data), media_type='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename={filename}'})

