# Extracted from legacy backend/app.py lines 2532-2872.
@router.get('/api/members')
def list_members(q:str='', status:str='', grade:str='', priority:str='', sort:str='priority', limit:int=5000, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    wh=[]; args=[]
    scope_sql, scope_args = member_scope_condition(admin, 'm')
    if scope_sql:
        wh.append(scope_sql); args += scope_args
    if q:
        q_norm = re.sub(r'[\s\-_.()\[\]{}+~`\'"·,/:;]', '', str(q or '').lower())
        q_digits = ''.join(ch for ch in str(q or '') if ch.isdigit())
        wh.append('''(
            LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(m.name,''), ' ', ''), '-', ''), '.', ''), '(', ''), ')', '')) LIKE ?
            OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(m.phone,''), '-', ''), ' ', ''), '.', ''), '(', ''), ')', '') LIKE ?
            OR LOWER(COALESCE(m.phone,'')) LIKE ?
            OR LOWER(COALESCE(m.grade,'')) LIKE ?
            OR LOWER(COALESCE(m.status,'')) LIKE ?
            OR LOWER(COALESCE(m.memo,'')) LIKE ?
            OR LOWER(COALESCE(m.source,'')) LIKE ?
            OR LOWER(COALESCE(m.priority,'')) LIKE ?
            OR LOWER(COALESCE(a.name,'')) LIKE ?
            OR LOWER(COALESCE(a.username,'')) LIKE ?
        )''')
        like = f"%{str(q or '').lower()}%"
        norm_like = f"%{q_norm}%"
        digits_like = "%" + q_digits + "%"
        args += [norm_like, digits_like if q_digits else norm_like, like, like, like, like, like, like, like, like]
    if status:
        wh.append('COALESCE(m.status, "활성")=?')
        args.append(status)
    if grade:
        wh.append('COALESCE(m.grade, "일반")=?')
        args.append(grade)
    if priority:
        wh.append('COALESCE(m.priority, "보통")=?')
        args.append(priority)
    sort_map={
        'priority':'CASE COALESCE(m.priority,"보통") WHEN "최우선" THEN 0 WHEN "높음" THEN 1 WHEN "보통" THEN 2 ELSE 3 END, m.id DESC',
        'recent':'m.id DESC',
        'oldest':'m.id ASC',
        'name':'m.name COLLATE NOCASE ASC, m.id DESC',
        'updated':'COALESCE(m.updated_at,m.created_at,"") DESC, m.id DESC',
        'status':'COALESCE(m.status,"활성") ASC, m.id DESC'
    }
    order=sort_map.get(sort, sort_map['priority'])
    limit=max(1, min(int(limit or 5000), 5000))
    # PostgreSQL 호환 안정화:
    # SQL 문자열 안에 LIKE '%super%' 같은 % 리터럴을 직접 쓰면 psycopg2가
    # %s 파라미터로 오인해서 IndexError: tuple index out of range가 발생할 수 있다.
    # 그래서 대표/일반 관리자 판별 패턴도 모두 바인딩 파라미터로 처리한다.
    super_case_args = [
        '%대표관리자%', '%최고관리자%', '%super%', '%owner%', '%대표관리자%', '%최고관리자%'
    ]
    sql="""
        SELECT m.*,
               COALESCE(a.name, a.username, '미지정') AS registered_by_name,
               COALESCE(a.username, '') AS registered_by_username,
               COALESCE(a.role, '') AS registered_by_role,
               CASE
                   WHEN LOWER(COALESCE(a.username,''))='admin'
                     OR REPLACE(LOWER(COALESCE(a.role,'')), ' ', '') LIKE ?
                     OR REPLACE(LOWER(COALESCE(a.role,'')), ' ', '') LIKE ?
                     OR LOWER(COALESCE(a.role,'')) LIKE ?
                     OR LOWER(COALESCE(a.role,'')) LIKE ?
                     OR REPLACE(LOWER(COALESCE(a.name,'')), ' ', '') LIKE ?
                     OR REPLACE(LOWER(COALESCE(a.name,'')), ' ', '') LIKE ?
                   THEN 1 ELSE 0 END AS registered_by_super_admin
        FROM members m
        LEFT JOIN admins a ON a.id = COALESCE(m.created_by,0)
    """ + (' WHERE ' + ' AND '.join(wh) if wh else '') + f' ORDER BY {order} LIMIT ?'
    final_args = super_case_args + args + [limit]
    with con() as c:
        rows=c.execute(sql, final_args).fetchall()
    return [dict(r) for r in rows]

@router.get('/api/members_summary')
def members_summary(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    scope_sql, scope_args = member_scope_condition(admin)
    where = (' WHERE ' + scope_sql) if scope_sql else ''
    with con() as c:
        total=c.execute('SELECT COUNT(*) c FROM members' + where, scope_args).fetchone()['c']
        grade=c.execute('SELECT COALESCE(grade,"일반") label, COUNT(*) c FROM members' + where + ' GROUP BY COALESCE(grade,"일반")', scope_args).fetchall()
        status=c.execute('SELECT COALESCE(status,"활성") label, COUNT(*) c FROM members' + where + ' GROUP BY COALESCE(status,"활성")', scope_args).fetchall()
        priority=c.execute('SELECT COALESCE(priority,"보통") label, COUNT(*) c FROM members' + where + ' GROUP BY COALESCE(priority,"보통")', scope_args).fetchall()
        no_contact=c.execute('SELECT COUNT(*) c FROM members' + (where + ' AND ' if where else ' WHERE ') + 'COALESCE(last_contact_at,"")=""', scope_args).fetchone()['c']
    return {'total':total,'grade':{r['label']:r['c'] for r in grade},'status':{r['label']:r['c'] for r in status},'priority':{r['label']:r['c'] for r in priority},'no_contact':no_contact,'is_super_admin':is_super_admin(admin)}


@router.get('/api/members_manage_overview')
def members_manage_overview(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    scope_sql, scope_args = member_scope_condition(admin)
    where = (' WHERE ' + scope_sql) if scope_sql else ''
    with con() as c:
        total=c.execute('SELECT COUNT(*) c FROM members' + where, scope_args).fetchone()['c']
        active=c.execute('SELECT COUNT(*) c FROM members' + (where + ' AND ' if where else ' WHERE ') + 'COALESCE(status,"활성")="활성"', scope_args).fetchone()['c']
        paused=c.execute('SELECT COUNT(*) c FROM members' + (where + ' AND ' if where else ' WHERE ') + 'COALESCE(status,"활성") IN ("휴면","정지")', scope_args).fetchone()['c']
        closed=c.execute('SELECT COUNT(*) c FROM members' + (where + ' AND ' if where else ' WHERE ') + 'COALESCE(status,"활성") IN ("종료","탈퇴")', scope_args).fetchone()['c']
        recent=c.execute('SELECT id,name,phone,grade,status,priority,created_at,updated_at FROM members' + where + ' ORDER BY id DESC LIMIT 10', scope_args).fetchall()
        status_rows=c.execute('SELECT COALESCE(status,"활성") label, COUNT(*) c FROM members' + where + ' GROUP BY COALESCE(status,"활성")', scope_args).fetchall()
    return {'total':total,'active':active,'paused':paused,'closed':closed,'status_counts':{r['label']:r['c'] for r in status_rows},'recent':[dict(r) for r in recent],'is_super_admin':is_super_admin(admin)}


@router.post('/api/members/{member_id}/status')
def change_member_status(member_id:int, req:MemberStatusReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    allowed={'활성','상담중','휴면','정지','종료','탈퇴'}
    if req.status not in allowed:
        raise HTTPException(400, '허용되지 않은 회원 상태입니다.')
    with con() as c:
        m=assert_member_access(c, admin, member_id)
        m=c.execute('SELECT id,name,status,memo FROM members WHERE id=?',(member_id,)).fetchone()
        memo = m['memo'] if req.memo is None else req.memo
        c.execute('UPDATE members SET status=?, memo=?, updated_at=? WHERE id=?',(req.status,memo,now(),member_id))
        c.commit()
    log_action(admin,'CHANGE_MEMBER_STATUS',f'회원 상태 변경: {m["name"]} / {m["status"] or "활성"} -> {req.status}',request)
    return {'ok':True,'id':member_id,'status':req.status}

@router.post('/api/members/bulk_status')
def bulk_member_status(req:MemberBulkStatusReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    allowed={'활성','상담중','휴면','정지','종료','탈퇴'}
    if req.status not in allowed:
        raise HTTPException(400, '허용되지 않은 회원 상태입니다.')
    ids=[int(x) for x in req.member_ids if int(x)>0]
    if not ids: raise HTTPException(400,'변경할 회원을 선택하세요.')
    placeholders=','.join(['?']*len(ids))
    with con() as c:
        scope_sql, scope_args = member_scope_condition(admin)
        scope_tail = (' AND ' + scope_sql) if scope_sql else ''
        rows=c.execute(f'SELECT id,name,status FROM members WHERE id IN ({placeholders}){scope_tail}', [*ids, *scope_args]).fetchall()
        allowed_ids=[int(r['id']) for r in rows]
        if allowed_ids:
            ph=','.join(['?']*len(allowed_ids))
            c.execute(f'UPDATE members SET status=?, updated_at=? WHERE id IN ({ph})', [req.status, now(), *allowed_ids])
        c.commit()
    log_action(admin,'BULK_MEMBER_STATUS',f'회원 {len(rows)}명 상태 일괄 변경 -> {req.status}',request)
    return {'ok':True,'changed':len(rows),'status':req.status}

@router.post('/api/members')
def add_member(req:MemberReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    created_at = normalize_date_text(req.created_at, datetime.datetime.now().strftime('%Y-%m-%d')) if is_super_admin(admin) else datetime.datetime.now().strftime('%Y-%m-%d')
    contract_months = int(req.contract_months or 12)
    if contract_months not in (6, 12, 24, 36):
        contract_months = 12
    contract_end_at = add_months_date(created_at, contract_months)
    owner_id = int(req.created_by or admin['id']) if is_super_admin(admin) else int(admin['id'])
    with con() as c:
        if owner_id:
            owner = c.execute('SELECT id FROM admins WHERE id=?', (owner_id,)).fetchone()
            if not owner:
                raise HTTPException(400, '등록 관리자를 찾을 수 없습니다.')
        preferred_count=max(1, min(int(req.preferred_count or 10), 100))
        cur=c.execute('INSERT INTO members(name,phone,grade,memo,status,priority,source,preferred_count,created_by,created_at,contract_months,contract_end_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(req.name,req.phone,req.grade,req.memo,req.status,req.priority,req.source,preferred_count,owner_id,created_at,contract_months,contract_end_at,now()))
        c.commit(); mid=cur.lastrowid
    log_action(admin,'CREATE_MEMBER',f'회원 등록: {req.name}',request); return {'id':mid}

@router.delete('/api/members/{member_id}')
def del_member(member_id:int, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        assert_member_access(c, admin, member_id)
        c.execute('DELETE FROM members WHERE id=?',(member_id,)); c.commit()
    log_action(admin,'DELETE_MEMBER',f'회원 삭제 ID {member_id}',request); return {'ok':True}

@router.put('/api/members/{member_id}')
def update_member(member_id:int, req:MemberReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        assert_member_access(c, admin, member_id)
        preferred_count=max(1, min(int(req.preferred_count or 10), 100))
        current_member = c.execute('SELECT created_at, COALESCE(contract_months,12) AS contract_months, created_by FROM members WHERE id=?', (member_id,)).fetchone()
        if not current_member:
            raise HTTPException(404, '회원 정보를 찾을 수 없습니다.')

        # V3.0.0 STABLE 실제 수정:
        # - 등록일(created_at), 계약기간(contract_months)은 모든 관리자가 수정 가능
        # - 등록 관리자(created_by) 변경만 대표관리자만 가능
        # - 계약만료일(contract_end_at)은 등록일 + 계약기간으로 서버에서 항상 재계산
        base_created = normalize_date_text(req.created_at, '') or normalize_date_text(current_member['created_at'], datetime.datetime.now().strftime('%Y-%m-%d'))
        contract_months = int(req.contract_months or current_member['contract_months'] or 12)
        if contract_months not in (6, 12, 24, 36):
            contract_months = 12
        contract_end_at = add_months_date(base_created, contract_months)

        fields=[
            'name=?','phone=?','grade=?','memo=?','status=?','priority=?','source=?',
            'preferred_count=?','created_at=?','contract_months=?','contract_end_at=?','updated_at=?'
        ]
        vals=[
            req.name, req.phone, req.grade, req.memo, req.status, req.priority, req.source,
            preferred_count, base_created, contract_months, contract_end_at, now()
        ]

        if is_super_admin(admin):
            owner_id = int(req.created_by or 0)
            if owner_id:
                owner = c.execute('SELECT id FROM admins WHERE id=?', (owner_id,)).fetchone()
                if not owner:
                    raise HTTPException(400, '등록 관리자를 찾을 수 없습니다.')
                fields.append('created_by=?'); vals.append(owner_id)

        vals.append(member_id)
        c.execute('UPDATE members SET '+', '.join(fields)+' WHERE id=?', vals)
        c.commit()

        saved = c.execute('SELECT id,created_at,contract_months,contract_end_at,created_by FROM members WHERE id=?', (member_id,)).fetchone()
    log_action(admin,'UPDATE_MEMBER',f'회원 수정 ID {member_id}: {req.name}',request)
    return {'ok':True, 'member': dict(saved) if saved else {'id': member_id}}

@router.get('/api/members/{member_id}/detail')
def member_detail(member_id:int, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        assert_member_access(c, admin, member_id)
        m=c.execute('SELECT * FROM members WHERE id=?',(member_id,)).fetchone()
        recs=c.execute('SELECT id,round_no,mode,count,numbers,analysis,avg_score,created_at FROM recommendations WHERE member_id=? ORDER BY id DESC LIMIT 50',(member_id,)).fetchall()
        sms=c.execute('SELECT id,member_id,round_no,body,status,created_at FROM sms_logs WHERE member_id=? ORDER BY id DESC LIMIT 50',(member_id,)).fetchall()
        wins=c.execute('SELECT round_no,target_numbers,win_numbers,bonus,match_count,bonus_match,rank,prize,cost,profit,roi,created_at FROM winning_checks WHERE member_id=? ORDER BY id DESC LIMIT 50',(member_id,)).fetchall()
        notes=c.execute('SELECT id,note,note_type,created_by_name,created_at FROM member_notes WHERE member_id=? ORDER BY id DESC LIMIT 50',(member_id,)).fetchall()
    rec_list=[]
    for r in recs:
        d=dict(r)
        try: d['numbers']=json.loads(d.get('numbers') or '[]')
        except Exception: d['numbers']=[]
        rec_list.append(d)
    win_list=[]
    for r in wins:
        d=dict(r)
        for key in ('target_numbers','win_numbers'):
            try: d[key]=json.loads(d.get(key) or '[]')
            except Exception: d[key]=[]
        win_list.append(d)
    total_prize=sum(w.get('prize') or 0 for w in win_list)
    total_cost=sum(w.get('cost') or 0 for w in win_list)
    total_profit=sum(w.get('profit') or 0 for w in win_list)
    ranks=collections.Counter([w.get('rank','낙첨') for w in win_list])
    best='없음'
    order={'1등':1,'2등':2,'3등':3,'4등':4,'5등':5,'낙첨':9}
    ranked=[w.get('rank','낙첨') for w in win_list]
    if ranked: best=sorted(ranked, key=lambda x:order.get(x,9))[0]
    return {
        'member':dict(m),
        'recommendations':rec_list,
        'sms_logs':[dict(r) for r in sms],
        'winning_checks':win_list,
        'notes':[dict(r) for r in notes],
        'summary':{
            'recommendations':len(rec_list),'sms':len(sms),'checks':len(win_list),'notes':len(notes),'best_rank':best,
            'rank_counts':dict(ranks),'total_prize':total_prize,'total_cost':total_cost,'total_profit':total_profit,
            'roi':round((total_profit/total_cost*100),2) if total_cost else 0,
            'latest_recommendation': rec_list[0]['created_at'] if rec_list else '',
            'latest_sms': dict(sms[0])['created_at'] if sms else '',
            'latest_note': dict(notes[0])['created_at'] if notes else ''
        }
    }

@router.put('/api/members/{member_id}/memo')
def update_member_memo(member_id:int, req:MemberMemoReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        m=assert_member_access(c, admin, member_id)
        c.execute('UPDATE members SET memo=?, updated_at=? WHERE id=?',(req.memo, now(), member_id))
        c.commit()
    log_action(admin,'UPDATE_MEMBER_MEMO',f'회원 메모 수정: {m["name"]}',request)
    return {'ok':True,'id':member_id}

@router.post('/api/members/{member_id}/notes')
def add_member_note(member_id:int, req:MemberNoteReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    note=(req.note or '').strip()
    if not note: raise HTTPException(400,'상담 내용을 입력하세요.')
    note_type=(req.note_type or '상담').strip()[:20]
    with con() as c:
        m=assert_member_access(c, admin, member_id)
        c.execute('INSERT INTO member_notes(member_id,note,note_type,created_by,created_by_name,created_at) VALUES(?,?,?,?,?,?)',(member_id,note,note_type,admin['id'],admin.get('name') or admin.get('username') or '',now()))
        c.execute('UPDATE members SET last_contact_at=?, updated_at=? WHERE id=?',(now(),now(),member_id))
        c.commit()
    log_action(admin,'CREATE_MEMBER_NOTE',f'상담 이력 추가: {m["name"]}',request)
    return {'ok':True,'member_id':member_id}


def rc312_resolve_member(c, member_id=None, member_name=''):
    """RC3-12: 추천번호/당첨확인이 회원과 끊기지 않도록 회원 ID/이름을 표준화합니다."""
    mid = None
    name = (member_name or '').strip()
    if member_id:
        m = c.execute('SELECT id,name FROM members WHERE id=?', (member_id,)).fetchone()
        if m:
            mid = int(m['id'])
            name = m['name'] or name
    if not mid and name:
        m = c.execute('SELECT id,name FROM members WHERE name=? ORDER BY id DESC LIMIT 1', (name,)).fetchone()
        if m:
            mid = int(m['id'])
            name = m['name'] or name
    return mid, name


@router.get('/api/rc3-12/member-link-status')
def rc312_member_link_status(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        members = c.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        recs = c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c']
        linked = c.execute('SELECT COUNT(*) c FROM recommendations WHERE COALESCE(member_id,0)>0').fetchone()['c']
        orphan = c.execute('SELECT COUNT(*) c FROM recommendations WHERE COALESCE(member_id,0)=0').fetchone()['c']
        latest_orphans = c.execute('SELECT id,round_no,member_name,created_at FROM recommendations WHERE COALESCE(member_id,0)=0 ORDER BY id DESC LIMIT 20').fetchall()
    return {'ok': True, 'version': 'RC3-12', 'members': members, 'recommendations': recs, 'linked_recommendations': linked, 'orphan_recommendations': orphan, 'latest_orphans': [dict(r) for r in latest_orphans], 'message': '회원 선택 없이 생성된 기존 추천이력은 공통 추천으로 표시됩니다. 특정 회원으로 연결하려면 /api/rc3-12/link-orphan-recommendations 를 사용하세요.'}


@router.post('/api/rc3-12/link-orphan-recommendations')
def rc312_link_orphan_recommendations(req: dict, request:Request, authorization: str|None = Header(default=None)):
    admin = require_admin(authorization)
    member_id = int((req or {}).get('member_id') or 0)
    round_no = int((req or {}).get('round_no') or 0)
    if member_id <= 0:
        raise HTTPException(400, '연결할 회원을 선택하세요.')
    with con() as c:
        m = c.execute('SELECT id,name FROM members WHERE id=?', (member_id,)).fetchone()
        if not m:
            raise HTTPException(404, '회원을 찾을 수 없습니다.')
        params = [member_id, m['name'], now()]
        where = 'COALESCE(member_id,0)=0'
        if round_no > 0:
            where += ' AND round_no=?'
            params.append(round_no)
        cur = c.execute(f'UPDATE recommendations SET member_id=?, member_name=?, created_at=COALESCE(NULLIF(created_at,""), ?) WHERE {where}', params)
        # 이미 당첨확인이 되어 있는 공통 추천 결과도 같은 회차 기준으로 회원명을 보정합니다.
        wc_params = [member_id, m['name']]
        wc_where = 'COALESCE(member_id,0)=0'
        if round_no > 0:
            wc_where += ' AND round_no=?'
            wc_params.append(round_no)
        c.execute(f'UPDATE winning_checks SET member_id=?, member_name=? WHERE {wc_where}', wc_params)
        c.commit()
        changed = cur.rowcount if cur.rowcount is not None else 0
    log_action(admin, 'RC3_12_LINK_ORPHAN_RECOMMENDATIONS', f'{round_no or "전체"}회차 미연결 추천이력 {changed}건을 {m["name"]} 회원으로 연결', request)
    return {'ok': True, 'version': 'RC3-12', 'updated': changed, 'member_id': member_id, 'member_name': m['name'], 'round_no': round_no or None}

