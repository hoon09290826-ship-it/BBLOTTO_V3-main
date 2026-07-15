# Extracted from legacy backend/app.py lines 2109-2531.
@router.post('/api/login')
def login(req:LoginReq, request:Request):
    username = str(req.username or '').strip()[:80]
    if not username or not req.password or len(str(req.password)) > 256:
        raise HTTPException(400, '아이디와 비밀번호를 확인해주세요.')
    _rc11_check_login_limit(request, username)
    with con() as c:
        admin = c.execute('SELECT * FROM admins WHERE username=? AND is_active=1', (username,)).fetchone()
        stored_hash = admin['password_hash'] if admin else 'pbkdf2_sha256$260000$00000000000000000000000000000000$' + ('0' * 64)
        password_ok = verify_password(req.password, stored_hash)
        if not admin or not password_ok:
            _rc11_record_login_failure(request, username)
            ip = _rc113_client_ip(request)
            c.execute('INSERT INTO admin_logs(admin_id,username,action,detail,ip,created_at) VALUES(?,?,?,?,?,?)', (None, username, 'LOGIN_FAILED', '로그인 실패', ip, now()))
            c.commit()
            log_login_event(0, username, 0, '로그인 실패', request)
            raise HTTPException(401, '아이디 또는 비밀번호가 맞지 않습니다.')
        _rc11_clear_login_failures(request, username)
        # 구형 또는 평문 해시는 로그인 성공 시 자동으로 RC11 방식으로 올립니다.
        if password_needs_rehash(admin['password_hash']):
            c.execute('UPDATE admins SET password_hash=? WHERE id=?', (hash_password(req.password), admin['id']))
        # 만료 세션과 오래된 중복 세션을 정리합니다.
        # SQLite와 PostgreSQL에서 동일하게 동작하도록 현재 시각을 파라미터로 전달합니다.
        c.execute('DELETE FROM sessions WHERE expires_at <= ?', (now(),))
        old_sessions = c.execute('SELECT token FROM sessions WHERE admin_id=? ORDER BY created_at DESC', (admin['id'],)).fetchall()
        for old in old_sessions[2:]:
            c.execute('DELETE FROM sessions WHERE token=?', (old['token'],))
        timeout_minutes = 600
        row_timeout = c.execute('SELECT value FROM settings WHERE key=?', ('session_timeout_minutes',)).fetchone()
        if row_timeout:
            try: timeout_minutes = max(10, min(1440, int(row_timeout['value'])))
            except Exception: timeout_minutes = 600
        token=secrets.token_urlsafe(32); exp=(datetime.datetime.now()+datetime.timedelta(minutes=timeout_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        ip = _rc113_client_ip(request)
        ua = request.headers.get('user-agent','')[:240]
        c.execute('INSERT INTO sessions(token,admin_id,created_at,expires_at,last_seen_at,ip,user_agent) VALUES(?,?,?,?,?,?,?)', (token,admin['id'],now(),exp,now(),ip,ua))
        c.execute('UPDATE admins SET last_login_at=?, last_ip=? WHERE id=?', (now(), ip, admin['id']))
        c.commit()
    log_action(dict(admin), 'LOGIN', '관리자 로그인', request)
    log_login_event(admin['id'], admin['username'], 1, '로그인 성공', request)
    return {'token':token,'admin':{'id':admin['id'],'username':admin['username'],'name':admin['name'],'role':admin['role'] if 'role' in admin.keys() else '전체권한','is_super_admin':is_super_admin(admin)},'expires_at':exp,'expires_in_seconds':timeout_minutes*60,'session_timeout_minutes':timeout_minutes}

@router.post('/api/logout')
def logout(request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); token=authorization.split(' ',1)[1].strip()
    with con() as c: c.execute('DELETE FROM sessions WHERE token=?',(token,)); c.commit()
    log_action(admin,'LOGOUT','관리자 로그아웃',request); return {'ok':True}

@router.get('/api/me')
def me(authorization: str|None = Header(default=None)):
    a=require_admin(authorization)
    
    left_seconds = 0
    try:
        exp_dt = datetime.datetime.strptime(a.get('expires_at',''), '%Y-%m-%d %H:%M:%S')
        left_seconds = max(0, int((exp_dt - datetime.datetime.now()).total_seconds()))
    except Exception:
        left_seconds = 0
    return {'id':a['id'],'username':a['username'],'name':a['name'],'phone':a.get('phone',''),'memo':a.get('memo',''),'role':a.get('role','전체권한'),'is_super_admin':is_super_admin(a),'expires_at':a.get('expires_at',''),'expires_in_seconds':left_seconds,'last_seen_at':a.get('last_seen_at',''),'last_login_at':a.get('last_login_at',''),'last_ip':a.get('last_ip','')}


@router.put('/api/me')
def update_my_account(req:MyAccountReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    fields=[]; vals=[]
    if req.name is not None:
        fields.append('name=?'); vals.append(req.name.strip() or '관리자')
    if req.phone is not None:
        fields.append('phone=?'); vals.append(req.phone.strip())
    if req.memo is not None:
        fields.append('memo=?'); vals.append(req.memo.strip())
    if req.new_password:
        validate_password_strength(req.new_password)
        with con() as c:
            row=c.execute('SELECT password_hash FROM admins WHERE id=?', (admin['id'],)).fetchone()
        if not row or not verify_password(req.current_password or '', row['password_hash']):
            raise HTTPException(400,'현재 비밀번호가 맞지 않습니다.')
        fields.append('password_hash=?'); vals.append(hash_password(req.new_password))
    if not fields:
        return {'ok':True,'changed':0}
    fields.append('updated_at=?'); vals.append(now()); vals.append(admin['id'])
    with con() as c:
        c.execute('UPDATE admins SET '+', '.join(fields)+' WHERE id=?', vals)
        c.commit()
    action='UPDATE_MY_PASSWORD' if req.new_password and len(fields)<=2 else ('UPDATE_MY_ACCOUNT_WITH_PASSWORD' if req.new_password else 'UPDATE_MY_ACCOUNT')
    log_action(admin, action, '본인 계정 정보 수정', request)
    return {'ok':True,'changed':1}

@router.get('/api/admins')
def admins(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        if is_super_admin(admin):
            rows=c.execute('SELECT id,username,name,phone,role,memo,is_active,created_at,updated_at,last_login_at,last_ip FROM admins ORDER BY id').fetchall()
        else:
            rows=c.execute('SELECT id,username,name,phone,role,memo,is_active,created_at,updated_at,last_login_at,last_ip FROM admins WHERE id=?', (admin['id'],)).fetchall()
    return [dict(r) for r in rows]

@router.post('/api/admins')
def create_admin(req:AdminReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    validate_password_strength(req.password)
    username = validate_admin_username(req.username)
    try:
        with con() as c:
            cur = c.execute('INSERT INTO admins(username,name,password_hash,is_active,created_at,updated_at,role,memo) VALUES(?,?,?,?,?,?,?,?)', (username,req.name.strip(),hash_password(req.password),1,now(),now(),req.role.strip() or '전체권한',req.memo.strip()))
            c.commit()
            if getattr(cur, 'rowcount', 1) == 0:
                raise HTTPException(400,'이미 존재하는 관리자 아이디입니다.')
        log_action(admin,'CREATE_ADMIN',f'관리자 생성: {username}',request); return {'ok':True}
    except sqlite3.IntegrityError:
        raise HTTPException(400,'이미 존재하는 관리자 아이디입니다.')
    except Exception as e:
        if 'duplicate' in str(e).lower() or 'unique' in str(e).lower():
            raise HTTPException(400,'이미 존재하는 관리자 아이디입니다.')
        raise

@router.delete('/api/admins/{admin_id}')
def delete_admin(admin_id:int, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    if admin_id == admin['id']:
        raise HTTPException(400,'현재 로그인한 본인 계정은 삭제할 수 없습니다.')
    with con() as c:
        target=c.execute('SELECT id,username,is_active FROM admins WHERE id=?',(admin_id,)).fetchone()
        if not target:
            raise HTTPException(404,'관리자를 찾을 수 없습니다.')
        active_count=c.execute('SELECT COUNT(*) c FROM admins WHERE is_active=1').fetchone()['c']
        if int(target['is_active'] or 0)==1 and active_count <= 1:
            raise HTTPException(400,'마지막 활성 관리자는 삭제할 수 없습니다.')
        c.execute('DELETE FROM sessions WHERE admin_id=?',(admin_id,))
        c.execute('DELETE FROM admins WHERE id=?',(admin_id,))
        c.commit()
    log_action(admin,'DELETE_ADMIN',f'관리자 삭제: {target["username"]} / ID {admin_id}',request)
    return {'ok':True,'deleted':admin_id}


@router.get('/api/admins/{admin_id}')
def admin_detail(admin_id:int, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    if not is_super_admin(admin) and int(admin_id) != int(admin['id']):
        raise HTTPException(403, '일반 관리자는 본인 계정만 조회할 수 있습니다.')
    with con() as c:
        row=c.execute('SELECT id,username,name,phone,role,memo,is_active,created_at,updated_at,last_login_at,last_ip FROM admins WHERE id=?',(admin_id,)).fetchone()
        if not row: raise HTTPException(404,'관리자를 찾을 수 없습니다.')
        recent=c.execute('SELECT action,detail,ip,created_at FROM admin_logs WHERE admin_id=? ORDER BY id DESC LIMIT 30',(admin_id,)).fetchall()
    data=dict(row); data['recent_logs']=[dict(r) for r in recent]
    return data

@router.put('/api/admins/{admin_id}')
def update_admin(admin_id:int, req:AdminUpdateReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    is_self = int(admin_id) == int(admin['id'])
    super_user = is_super_admin(admin)

    # 일반 관리자는 본인 비밀번호만 변경 가능
    if not super_user:
        if not is_self:
            raise HTTPException(403, '일반 관리자는 다른 관리자를 수정할 수 없습니다.')
        if req.name is not None or req.role is not None or req.memo is not None or req.is_active is not None:
            raise HTTPException(403, '일반 관리자는 본인 비밀번호만 변경할 수 있습니다.')
        if not req.password:
            raise HTTPException(400, '변경할 비밀번호를 입력하세요.')

    fields=[]; vals=[]
    if super_user:
        if req.name is not None:
            fields.append('name=?'); vals.append(req.name.strip() or '관리자')
        if req.role is not None:
            fields.append('role=?'); vals.append(req.role.strip() or '전체권한')
        if req.memo is not None:
            fields.append('memo=?'); vals.append(req.memo.strip())
        if req.is_active is not None:
            if is_self and int(req.is_active) == 0:
                raise HTTPException(400,'현재 로그인한 본인은 비활성화할 수 없습니다.')
            fields.append('is_active=?'); vals.append(1 if int(req.is_active) else 0)

    if req.password:
        validate_password_strength(req.password)
        fields.append('password_hash=?'); vals.append(hash_password(req.password))

    if not fields: return {'ok':True, 'changed':0}
    fields.append('updated_at=?'); vals.append(now()); vals.append(admin_id)
    with con() as c:
        target = c.execute('SELECT id,username,is_active FROM admins WHERE id=?', (admin_id,)).fetchone()
        if not target:
            raise HTTPException(404, '관리자를 찾을 수 없습니다.')
        if req.is_active is not None and int(req.is_active)==0 and int(target['is_active'] or 0)==1:
            active_count=c.execute('SELECT COUNT(*) c FROM admins WHERE is_active=1').fetchone()['c']
            if active_count <= 1:
                raise HTTPException(400,'마지막 활성 관리자는 비활성화할 수 없습니다.')
        c.execute('UPDATE admins SET '+', '.join(fields)+' WHERE id=?', vals)
        if req.is_active is not None and int(req.is_active)==0:
            c.execute('DELETE FROM sessions WHERE admin_id=?', (admin_id,))
        c.commit()
    log_action(admin,'UPDATE_ADMIN',f'관리자 수정 ID {admin_id}',request)
    return {'ok':True, 'changed':1}

@router.post('/api/admins/{admin_id}/activate')
def activate_admin(admin_id:int, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        target=c.execute('SELECT id,username,is_active FROM admins WHERE id=?', (admin_id,)).fetchone()
        if not target:
            raise HTTPException(404, '관리자를 찾을 수 없습니다.')
        c.execute('UPDATE admins SET is_active=1, updated_at=? WHERE id=?', (now(), admin_id))
        c.commit()
    log_action(admin,'ACTIVATE_ADMIN',f'관리자 활성화: {target["username"]} / ID {admin_id}',request)
    return {'ok':True,'changed':0 if int(target['is_active'] or 0)==1 else 1}

@router.post('/api/sessions/cleanup')
def cleanup_sessions(request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    with con() as c:
        cur=c.execute('DELETE FROM sessions WHERE expires_at<?', (now(),)); deleted=cur.rowcount; c.commit()
    log_action(admin,'CLEANUP_SESSIONS',f'만료 세션 정리 {deleted}건',request)
    return {'ok':True,'deleted':deleted}

@router.get('/api/security_status')
def security_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    with con() as c:
        active_sessions = c.execute('SELECT COUNT(*) c FROM sessions WHERE expires_at>=?', (now(),)).fetchone()['c']
        failed_today = c.execute('SELECT COUNT(*) c FROM admin_logs WHERE action=? AND created_at LIKE ?', ('LOGIN_FAILED', datetime.datetime.now().strftime('%Y-%m-%d')+'%')).fetchone()['c']
        timeout = c.execute('SELECT value FROM settings WHERE key=?', ('session_timeout_minutes',)).fetchone()
        warn = c.execute('SELECT value FROM settings WHERE key=?', ('auto_logout_warning_minutes',)).fetchone()
    return {'ok':True,'active_sessions':active_sessions,'failed_login_today':failed_today,'session_timeout_minutes':int((timeout or {'value':600})['value'] or 600),'auto_logout_warning_minutes':int((warn or {'value':5})['value'] or 5),'is_super_admin':is_super_admin(admin),'password_hash':'PBKDF2-SHA256/260000','login_limit':'7회/15분','security_headers':True,'origin_check':True,'request_size_limit_mb':2}

@router.get('/api/sessions')
def list_sessions(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    with con() as c:
        rows=c.execute('''SELECT s.token,a.username,a.name,s.created_at,s.last_seen_at,s.expires_at,s.ip,s.user_agent
                          FROM sessions s JOIN admins a ON a.id=s.admin_id
                          WHERE s.expires_at>=? ORDER BY s.last_seen_at DESC, s.created_at DESC''', (now(),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['token_tail']=str(d.pop('token'))[-8:]; out.append(d)
    return out

@router.delete('/api/sessions/{token_tail}')
def revoke_session(token_tail:str, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    require_super_admin(admin)
    suffix = re.sub(r'[^A-Za-z0-9_-]', '', str(token_tail or ''))[-8:]
    if len(suffix) != 8:
        raise HTTPException(400, '잘못된 세션 식별자입니다.')
    with con() as c:
        matches = c.execute('SELECT token FROM sessions').fetchall()
        tokens = [str(r['token']) for r in matches if str(r['token']).endswith(suffix)]
        if len(tokens) > 1:
            raise HTTPException(409, '세션 식별자가 중복됩니다. 목록을 새로고침해주세요.')
        deleted = 0
        if tokens:
            cur = c.execute('DELETE FROM sessions WHERE token=?', (tokens[0],)); deleted = cur.rowcount
        c.commit()
    log_action(admin,'REVOKE_SESSION',f'세션 종료: *{suffix}',request)
    return {'ok':True,'deleted':deleted}


@router.get('/api/dashboard')
def dashboard(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        members=c.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        admins_count=c.execute('SELECT COUNT(*) c FROM admins WHERE is_active=1').fetchone()['c']
        recs=c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c']
        checks=c.execute('SELECT COUNT(*) c, COALESCE(SUM(prize),0) prize, COALESCE(SUM(cost),0) cost, COALESCE(SUM(profit),0) profit FROM winning_checks').fetchone()
        latest=c.execute('SELECT * FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
    roi=round((checks['profit']/checks['cost']*100),2) if checks['cost'] else 0
    return {'members':members,'admins':admins_count,'recommendations':recs,'checks':checks['c'],'total_prize':checks['prize'],'total_cost':checks['cost'],'total_profit':checks['profit'],'roi':roi,'latest_draw':dict(latest) if latest else None}

@router.get('/api/dashboard_summary')
def dashboard_summary(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        members=c.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        active_members=c.execute('SELECT COUNT(*) c FROM members WHERE COALESCE(status,"활성")="활성"').fetchone()['c']
        vip_members=c.execute('SELECT COUNT(*) c FROM members WHERE grade IN ("1등","2등","VIP","다이아","프리미엄")').fetchone()['c']
        high_priority=c.execute('SELECT COUNT(*) c FROM members WHERE COALESCE(priority,"보통") IN ("높음","최우선")').fetchone()['c']
        recs=c.execute('SELECT COUNT(*) c FROM recommendations').fetchone()['c']
        sms=c.execute('SELECT COUNT(*) c FROM sms_logs').fetchone()['c']
        latest=c.execute('SELECT round_no FROM draws ORDER BY round_no DESC LIMIT 1').fetchone()
        recent=c.execute('SELECT id,member_id,member_name,round_no,mode,count,created_at FROM recommendations ORDER BY id DESC LIMIT 12').fetchall()
        grade_rows=c.execute('SELECT COALESCE(grade,"일반") label, COUNT(*) c FROM members GROUP BY COALESCE(grade,"일반")').fetchall()
        status_rows=c.execute('SELECT COALESCE(status,"활성") label, COUNT(*) c FROM members GROUP BY COALESCE(status,"활성")').fetchall()
    return {'members':members,'active_members':active_members,'vip_members':vip_members,'high_priority_members':high_priority,'recommendations':recs,'sms':sms,'latest_round': latest['round_no'] if latest else None,'recent_recommendations':[dict(r) for r in recent],'grade_counts':{r['label']:r['c'] for r in grade_rows},'status_counts':{r['label']:r['c'] for r in status_rows}}

@router.get('/api/settings')
def get_settings(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        rows=c.execute('SELECT key,value,updated_at FROM settings').fetchall()
    allowed = None if is_super_admin(admin) else {'sms_template'}
    result={}
    for r in rows:
        if allowed is not None and r['key'] not in allowed:
            continue
        result[r['key']]={'value':clean_template_text(r['value']) if r['key']=='sms_template' else r['value'],'updated_at':r['updated_at']}
    return result

@router.get('/api/template')
def get_template(authorization: str|None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        r=c.execute('SELECT value,updated_at FROM settings WHERE key=?', ('sms_template',)).fetchone()
    return {'body': clean_template_text(r['value'] if r else ''), 'updated_at': r['updated_at'] if r else ''}

@router.post('/api/template')
def save_template(req: dict, request: Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    body=clean_template_text(req.get('body') or req.get('value') or '')
    with con() as c:
        c.execute('INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)', ('sms_template', body, now()))
        c.commit()
    log_action(admin,'SAVE_TEMPLATE','회원 안내 문구 템플릿 저장',request)
    return {'ok': True, 'body': body}

@router.post('/api/settings')
def save_setting(req:SettingReq, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    allowed={'sms_template','sms_provider','sms_sender','sms_api_url','sms_api_key','session_timeout_minutes','auto_logout_warning_minutes'}
    if req.key not in allowed:
        raise HTTPException(400,'허용되지 않은 설정입니다.')
    if req.key != 'sms_template':
        require_super_admin(admin)
    with con() as c:
        c.execute('INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)',(req.key,clean_template_text(req.value) if req.key=='sms_template' else req.value,now()))
        c.commit()
    log_action(admin,'SAVE_SETTING',f'설정 저장: {req.key}',request)
    return {'ok':True,'key':req.key}

@router.get('/api/admin-stats')
def admin_stats(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    with con() as c:
        rows=c.execute('''SELECT a.id,a.username,a.name,a.last_login_at,
          SUM(CASE WHEN l.action='LOGIN' THEN 1 ELSE 0 END) login_count,
          SUM(CASE WHEN l.action='CREATE_MEMBER' THEN 1 ELSE 0 END) member_created,
          SUM(CASE WHEN l.action='GENERATE' THEN 1 ELSE 0 END) generated_count,
          COUNT(l.id) total_actions
          FROM admins a LEFT JOIN admin_logs l ON a.id=l.admin_id GROUP BY a.id ORDER BY a.id''').fetchall()
    return [dict(r) for r in rows]

@router.get('/api/admin-logs')
def admin_logs(limit:int=100, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    limit=max(1,min(int(limit or 100),500))
    with con() as c: rows=c.execute('SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]

@router.get('/api/admin-overview')
def admin_overview(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    with con() as c:
        active_admins = c.execute('SELECT COUNT(*) c FROM admins WHERE is_active=1').fetchone()['c']
        active_sessions = c.execute('SELECT COUNT(*) c FROM sessions WHERE expires_at>=?', (now(),)).fetchone()['c']
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        today_logins = c.execute('SELECT COUNT(*) c FROM admin_logs WHERE action=? AND created_at LIKE ?', ('LOGIN', today+'%')).fetchone()['c']
        today_actions = c.execute('SELECT COUNT(*) c FROM admin_logs WHERE created_at LIKE ?', (today+'%',)).fetchone()['c']
        backups = c.execute('SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) size FROM backup_history').fetchone()
        latest_backup = c.execute('SELECT * FROM backup_history ORDER BY id DESC LIMIT 1').fetchone()
    return {'active_admins':active_admins,'active_sessions':active_sessions,'today_logins':today_logins,'today_actions':today_actions,'backup_count':backups['c'],'backup_size':backups['size'],'latest_backup':dict(latest_backup) if latest_backup else None}

@router.get('/api/backups')
def backup_list(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    known = set()
    rows = []
    with con() as c:
        dbrows = c.execute('SELECT * FROM backup_history ORDER BY id DESC LIMIT 100').fetchall()
        for r in dbrows:
            d = dict(r); known.add(d.get('filename')); rows.append(d)
    for pattern in ('BBLOTTO*_BACKUP_*.db', 'BBLOTTO*_BACKUP_*.json', 'BBLOTTO_RC3_BACKUP_*.json'):
        for f in sorted(EXPORT_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.name not in known:
                rows.append({'id':None,'filename':f.name,'reason':'file','size_bytes':f.stat().st_size,'created_by':None,'created_at':datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'), 'format': f.suffix.lstrip('.')})
    return rows[:100]

@router.post('/api/backups/create')
def backup_create(request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    b=create_db_backup('manual', admin)
    log_action(admin, 'CREATE_BACKUP', f'DB 백업 생성: {b["filename"]}', request)
    return b

@router.post('/api/backups/restore/{filename}')
def backup_restore(filename:str, request:Request, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    safe = Path(filename).name
    path = EXPORT_DIR / safe
    result = _restore_json_backup(path, admin, request)
    return result

@router.get('/api/backups/validate/{filename}')
def backup_validate(filename:str, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    safe = Path(filename).name
    path = EXPORT_DIR / safe
    data = _validate_backup_json(path)
    tables = data.get('tables') or {}
    return {'ok': True, 'filename': safe, 'engine': data.get('engine'), 'created_at': data.get('created_at'), 'table_counts': {k: len(v or []) for k, v in tables.items()}}

@router.post('/api/backups/cleanup')
def backup_cleanup(keep:int=20, authorization: str|None = Header(default=None)):
    admin=require_admin(authorization); require_super_admin(admin)
    keep = max(3, min(int(keep or 20), 100))
    files = []
    for pattern in ('BBLOTTO*_BACKUP_*.db', 'BBLOTTO*_BACKUP_*.json', 'BBLOTTO_RC3_BACKUP_*.json'):
        files.extend(EXPORT_DIR.glob(pattern))
    files = sorted(set(files), key=lambda x: x.stat().st_mtime, reverse=True)
    removed=[]
    for f in files[keep:]:
        try:
            removed.append(f.name); f.unlink()
        except Exception:
            _log_suppressed_exception("20_auth_admin_settings.py:403")
    return {'ok': True, 'keep': keep, 'removed': removed, 'remaining': len(files)-len(removed)}

@router.get('/api/rc3-4/status')
def rc3_4_status(authorization: str|None = Header(default=None)):
    admin=require_admin(authorization)
    with con() as c:
        hist = c.execute('SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) size FROM backup_history').fetchone()
        latest = c.execute('SELECT * FROM backup_history ORDER BY id DESC LIMIT 1').fetchone()
    return {'ok': True, 'version': 'RC3-4_BACKUP_RESTORE', 'engine': DB_ENGINE, 'backup_dir': str(EXPORT_DIR), 'backup_count': hist['c'] if hist else 0, 'backup_size': hist['size'] if hist else 0, 'latest_backup': dict(latest) if latest else None, 'supports': ['json_backup', 'json_restore', 'sqlite_db_download', 'postgresql_export']}

@router.get('/api/backups/download/{filename}')
def backup_download(filename:str, token: str|None=None, authorization: str|None = Header(default=None)):
    require_admin_any(authorization, token)
    safe = Path(filename).name
    path = EXPORT_DIR / safe
    if not path.exists() or path.suffix.lower() not in ('.db', '.json'):
        raise HTTPException(404, '백업 파일을 찾을 수 없습니다.')
    media = 'application/json' if path.suffix.lower() == '.json' else 'application/octet-stream'
    return FileResponse(path, media_type=media, filename=safe)


