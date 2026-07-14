/* BBLOTTO V3 frontend split: js/30_admin.js | original lines 1168-1452 */
let activityLogCache=[]; let activityLogFilter='all';
function prettyAction(action=''){
  const a=String(action||'').toUpperCase();
  if(a.includes('LOGIN_FAILED')) return '로그인 실패';
  if(a.includes('LOGIN')) return '로그인';
  if(a.includes('LOGOUT')) return '로그아웃';
  if(a.includes('CREATE_MEMBER')) return '회원 등록';
  if(a.includes('UPDATE_MEMBER')) return '회원 수정';
  if(a.includes('DELETE_MEMBER')) return '회원 삭제';
  if(a.includes('GENERATE')) return '추천번호 생성';
  if(a.includes('WIN') || a.includes('DRAW')) return '당첨 확인';
  if(a.includes('BACKUP')) return '백업';
  if(a.includes('SMS')) return '문구 저장';
  return action || '활동';
}
function logGroup(action=''){
  const a=String(action||'').toUpperCase();
  if(a.includes('MEMBER')) return 'member';
  if(a.includes('GENERATE') || a.includes('RECOMMEND')) return 'recommend';
  if(a.includes('WIN') || a.includes('DRAW')) return 'winning';
  if(a.includes('LOGIN') || a.includes('LOGOUT')) return 'login';
  if(a.includes('BACKUP') || a.includes('RESTORE')) return 'backup';
  return 'etc';
}
function shortDetail(action='', detail=''){
  const d=String(detail||'').replace(/_/g,' ').trim();
  const a=String(action||'').toUpperCase();
  if(!d) return '';
  if(a.includes('GENERATE')){
    const round=(d.match(/(\d{3,4})회/)||[])[1];
    const combos=(d.match(/(\d+)조합/)||[])[1];
    return [round?round+'회':'', combos?combos+'조합':''].filter(Boolean).join(' · ') || d.slice(0,46);
  }
  if(a.includes('AUTO_WIN') || a.includes('DRAW')){
    const round=(d.match(/(\d{3,4})회/)||[])[1];
    return round ? round+'회 당첨 확인' : d.slice(0,46);
  }
  if(a.includes('CREATE_MEMBER')) return d.replace('회원 등록:','').trim().slice(0,46);
  if(a.includes('BACKUP')) return d.split(':').pop().trim().slice(0,46);
  return d.slice(0,46);
}
function renderActivityLogs(){
  const rows=(activityLogCache||[]).filter(l=>{ const a=String(l.action||'').toUpperCase(); return !a.includes('LOGIN_FAILED') && !a.includes('SAVE_SMS'); }).slice(0,10);
  const html=rows.map(l=>`<div class="simple-log-row"><div><time>${esc((l.created_at||'').slice(11,16) || (l.created_at||'').slice(5,16))}</time><b>${esc(l.username||'관리자')}</b><span>${esc(prettyAction(l.action))}</span>${shortDetail(l.action,l.detail)?`<small>${esc(shortDetail(l.action,l.detail))}</small>`:''}</div></div>`).join('');
  setHTML('activityLogs', html || '<p class="hint">표시할 활동이 없습니다.</p>');
}
window.filterActivityLog=function(kind){ activityLogFilter=kind||'all'; renderActivityLogs(); };
function renderBackupList(backups){
  const rows=(backups||[]).slice(0,5).map(b=>{
    const file=String(b.filename||''); const safe=esc(file); const isJson=file.toLowerCase().endsWith('.json');
    const created=esc((b.created_at||'').slice(0,16) || file.replace(/^BBLOTTO.*?_BACKUP_/,'').slice(0,15));
    const reason=esc((b.reason||'manual')==='auto_daily'?'자동백업':'수동백업');
    return `<div class="simple-backup-row"><div><b>${created}</b><small>${reason}</small></div><div><button type="button" data-action="download-api" data-url="/api/backups/download/${encodeURIComponent(file)}">다운로드</button>${isJson?` <button type="button" class="danger" data-action="backup-restore" data-file="${safe}">복원</button>`:''}</div></div>`;
  }).join('');
  setHTML('backupList', rows || '<p class="hint">백업 없음</p>');
}

function switchAdminPanel(panel){
  document.querySelectorAll('.admin-tab-btn').forEach(b=>b.classList.toggle('active', b.dataset.adminPanel===panel));
  document.querySelectorAll('[data-admin-panel-box]').forEach(box=>box.classList.toggle('active', box.dataset.adminPanelBox===panel));
}
function openAdminCreateModal(){
  const m=$('adminCreateModal');
  if(!m) return;
  // RC5.4 FIX: aria-hidden이 남아있는 상태에서 input에 포커스가 잡히면
  // Chrome이 클릭/포커스 처리를 막는 경우가 있어 열린 상태에서는 완전히 제거한다.
  m.style.display='flex';
  m.classList.add('is-open');
  m.removeAttribute('aria-hidden');
  m.removeAttribute('inert');
  m.inert=false;
  const card=m.querySelector('.modal-card');
  if(card){ card.removeAttribute('aria-hidden'); card.removeAttribute('inert'); card.inert=false; }
  setTimeout(()=>{ const first=$('newAdmin'); if(first) first.focus(); },30);
}
function closeAdminCreateModal(){
  const m=$('adminCreateModal');
  if(!m) return;
  // 닫기 전에 모달 내부 포커스를 먼저 빼야 aria-hidden 경고와 클릭 먹통을 방지한다.
  if(m.contains(document.activeElement)) document.activeElement.blur();
  m.classList.remove('is-open');
  m.style.display='none';
  m.setAttribute('aria-hidden','true');
}
window.openAdminCreateModal=openAdminCreateModal;
window.closeAdminCreateModal=closeAdminCreateModal;


function renderAiV6CacheStatus(d){
  const ok = !!d?.is_full_history;
  setText('aiV6CacheBadge', ok ? '전체 저장 완료' : '누락 있음');
  const range = Array.isArray(d?.round_range) ? d.round_range.join('~') : (d?.round_range || '-');
  const missing = Number(d?.missing_rounds_count || 0);
  const sample = Array.isArray(d?.missing_rounds_sample) ? d.missing_rounds_sample.join(', ') : '';
  setHTML('aiV6CacheStatus', `
    <b>엔진:</b> ${esc(d?.engine_version || '-')}<br>
    <b>저장방식:</b> ${esc(d?.cache_storage || '-')}<br>
    <b>분석범위:</b> ${esc(range)} / 최신 ${esc(d?.latest_round || '-')}회<br>
    <b>저장 회차:</b> ${esc(d?.actual_count || 0)} / ${esc(d?.expected_count || d?.target_round || 0)}<br>
    <b>1~${esc(d?.target_round || d?.latest_round || '-')} 전체 여부:</b> ${ok ? '예' : '아니오'}<br>
    <b>누락:</b> ${missing}개 ${sample ? '('+esc(sample)+')' : ''}
  `);
}

async function checkAiV6CacheStatus(){
  setBusy('checkAiV6Cache', true, '확인 중...');
  setText('aiV6CacheBadge','확인 중');
  try{
    let d;
    try{ d = await api('/api/admin/ai-v6/cache-status'); }
    catch(firstError){
      console.warn('관리자 캐시 상태 API 재시도', firstError);
      d = await api('/api/ai-engine/v6-cache');
    }
    renderAiV6CacheStatus(d);
    toast(`캐시 확인 완료: ${Number(d.actual_count||d.draw_count||0)}/${Number(d.expected_count||d.target_round||0)}회`);
    return d;
  }finally{ setBusy('checkAiV6Cache', false); }
}

async function syncAiV6FullHistory(){
  if(!confirm('1회차부터 현재 추첨 완료 회차까지 자동 동기화/분석을 시작할까요? Railway 오류 방지를 위해 나눠서 저장합니다.')) return;
  setBusy('syncAiV6FullHistory', true, '동기화/분석 중...');
  setText('aiV6CacheBadge', '진행 중');
  setHTML('aiV6CacheStatus', '전체 회차를 나눠서 저장 중입니다. 창을 닫지 말고 기다려주세요.');
  try{
    let last = null;
    for(let i=1;i<=40;i++){
      const d = await api('/api/admin/ai-v6/full-sync-step?chunk_size=25', {method:'POST'});
      if(d && d.ok === false && d.retryable){
        throw new Error(d.message || '회차 동기화 처리 중 오류가 발생했습니다.');
      }
      last = d;
      const c = d.cache || d;
      renderAiV6CacheStatus(c);
      const actual = Number(c.actual_count || 0);
      const expected = Number(c.expected_count || c.target_round || 0);
      setText('aiV6CacheBadge', d.completed ? '전체 저장 완료' : `진행 중 ${actual}/${expected}`);
      if(d.completed || c.is_full_history) break;
      await new Promise(r=>setTimeout(r, 350));
    }
    const done = !!(last?.completed || last?.cache?.is_full_history || last?.is_full_history);
    toast(done ? `1~${Number((last?.cache||last)?.target_round||0)} 전체 회차 분석 저장 완료` : '아직 일부 회차가 남았습니다. 버튼을 한 번 더 눌러 이어서 진행하세요.');
  }finally{
    setBusy('syncAiV6FullHistory', false);
  }
}

window.checkAiV6CacheStatus = safe(checkAiV6CacheStatus);
window.syncAiV6FullHistory = safe(syncAiV6FullHistory);

async function loadAdmin(){
  try{ currentAdmin = await api('/api/me'); setText('who', currentAdmin.name || currentAdmin.username || '관리자'); startSessionWatcher(currentAdmin); renderMyAccount(); }catch(e){ currentAdmin=null; }
  const isSuper = !!currentAdmin?.is_super_admin;
  applyAdminVisibility(isSuper);
  if(isSuper){
    try{
      const sec = await api('/api/security_status');
      const msg = `활성 세션 ${sec.active_sessions||0}개 / 오늘 로그인 실패 ${sec.failed_login_today||0}건 / 자동 로그아웃 ${sec.session_timeout_minutes||600}분`;
      const target = $('adminSecurityStatus') || $('activityLogs');
      if(target && target.id === 'adminSecurityStatus') target.textContent = msg;
    }catch(e){}
    try{
      const overview=await api('/api/admin-overview');
      setText('adminActiveCount', overview.active_admins ?? 0);
      setText('adminSessionCount', overview.active_sessions ?? 0);
      setText('adminTodayActions', overview.today_actions ?? 0);
      setText('adminBackupCount', overview.backup_count ?? 0);
    }catch(e){}
    try{ activityLogCache=await api('/api/admin-logs'); renderActivityLogs(); }catch(e){ setHTML('activityLogs','활동 로그를 불러오지 못했습니다.'); }
    try{
      const sessions = await api('/api/sessions');
      const el = $('activeSessions'); if(el) el.innerHTML = ''; // 간편 UI에서는 세션 상세 숨김
    }catch(e){}
  }else{
    setText('adminActiveCount', '-');
    setText('adminSessionCount', '-');
    setText('adminTodayActions', '-');
    setText('adminBackupCount', '-');
  }
  try{
    const admins=await api('/api/admins');
    adminCache = Array.isArray(admins) ? admins : [];
    refreshMemberAdminSelect();
    const addBox = $('addAdmin');
    ['newAdmin','newAdminName','newAdminRole','newAdminPw','newAdminMemo'].forEach(id=>{ const el=$(id); if(el) el.disabled=!isSuper; });
    if(addBox) addBox.disabled=!isSuper;
    setHTML('adminList', admins.map(a=>{
      const self = currentAdmin && Number(a.id)===Number(currentAdmin.id);
      let actions = '';
      if(isSuper){
        actions += `<button type="button" data-action="admin-edit" data-admin-id="${a.id}">수정</button>`;
        if(!self){
          actions += a.is_active ? `<button type="button" data-action="admin-toggle" data-admin-id="${a.id}" data-active="0">비활성</button>` : `<button type="button" data-action="admin-activate" data-admin-id="${a.id}">활성</button>`;
          actions += `<button type="button" class="danger" data-action="admin-delete" data-admin-id="${a.id}" data-username="${esc(a.username)}">삭제</button>`;
        }
      }else if(self){
        actions += `<button type="button" data-action="admin-my-password" data-admin-id="${a.id}">내 비밀번호 변경</button>`;
      }else{
        actions += `<span class="hint">수정 권한 없음</span>`;
      }
      return `<div class="admin-card">
        <div class="admin-info">
          <b>${esc(a.username)}</b>
          <span>${esc(a.name||'관리자')}</span>
          <small>${esc(a.role||'전체권한')} · ${a.is_active?'활성':'비활성'} · ${esc(a.last_login_at||'로그인 기록 없음')}</small>
        </div>
        <div class="admin-actions">${actions}</div>
      </div>`;
    }).join('') || '등록된 관리자가 없습니다.');
  }catch(e){ setHTML('adminList','관리자 목록을 불러오지 못했습니다.'); }
  if(isSuper){
    try{ await checkAiV6CacheStatus(); }catch(e){}
    try{
      const backups=await api('/api/backups');
      renderBackupList(backups);
      if($('backupSummary')) $('backupSummary').textContent = `최근 백업 ${backups.length}개 · 매일 자동백업 유지`;
    }catch(e){}
  }
  try{
    const settings=await api('/api/settings');
    setValue('sessionTimeout', settings.session_timeout_minutes?.value || '600');
  }catch(e){}
}

window.selectMember=function(id){
  const m=membersCache.find(x=>String(x.id)===String(id)); if(!m) return;
  setValue('mId',m.id); setValue('mName',m.name); setValue('mPhone',m.phone); setValue('mGrade',memberGradeLabel(m.grade)); setValue('mStatus',m.status||'활성'); setValue('mPriority',m.priority||'보통'); setValue('mPreferredCount',getMemberPreferredCount(m)); setValue('mCreatedAt',toDateInputValue(m.created_at)); setValue('mContractPeriod', String(m.contract_months || guessContractPeriodMonths(m.created_at, m.contract_end_at))); setValue('mContractEndAt',toDateInputValue(m.contract_end_at)||addMonthsDate(m.created_at, getContractPeriodMonths())); setValue('mSource',m.source||'직접등록'); setValue('mMemo',m.memo||''); refreshMemberAdminSelect(m.created_by||''); calcContractEnd();
  if($('genMember')) $('genMember').value=id;
  setGenCountValue(getMemberPreferredCount(m));
  refreshSmsPreview();
  toast(`${m.name} 회원을 선택했습니다.`);
};

async function copyTextToClipboard(text){
  const value = String(text || '');
  if(!value.trim()) throw new Error('복사할 문자 내용이 없습니다.');
  if(navigator.clipboard && navigator.clipboard.writeText){
    await navigator.clipboard.writeText(value);
    return;
  }
  const ta=document.createElement('textarea');
  ta.value=value;
  ta.setAttribute('readonly','');
  ta.style.position='fixed';
  ta.style.left='-9999px';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  document.execCommand('copy');
  ta.remove();
}

function closeMemberQuickResult(){
  document.getElementById('memberQuickResultModal')?.remove();
}
window.closeMemberQuickResult = closeMemberQuickResult;

function showMemberQuickResult(member, combos, analysis, copied=true, saved=false){
  closeMemberQuickResult();
  const rows=normalizeCombos(combos).map((c,i)=>`<div class="quick-result-row"><b>${i+1}</b><span>${esc(c.join(', '))}</span></div>`).join('');
  const lines=String(analysis||'').split(/\n+/).map(v=>v.trim()).filter(Boolean).map(v=>`<p>${esc(v)}</p>`).join('');
  const modal=document.createElement('div');
  modal.id='memberQuickResultModal';
  modal.className='quick-result-overlay';
  modal.innerHTML=`
    <div class="quick-result-modal" role="dialog" aria-modal="true" aria-label="회원 추천번호 생성 결과">
      <div class="quick-result-head">
        <div><small>회원관리 간편 생성</small><h3>${esc(member?.name||'회원')} · ${esc(currentRound||'')}회차</h3></div>
        <button type="button" class="quick-result-close" data-action="quick-result-close">닫기</button>
      </div>
      <div class="quick-result-status">추천번호 ${normalizeCombos(combos).length}조합 생성 완료${copied?' · 문자 복사 완료':''}${saved?' · 보낸문자 저장 완료':''}</div>
      <div class="quick-result-grid">
        <section><h4>추천번호</h4><div class="quick-result-combos">${rows}</div></section>
        <section><h4>이번 회차 핵심 분석</h4><div class="quick-result-analysis">${lines||'<p>분석요약이 없습니다.</p>'}</div></section>
      </div>
      <div class="quick-result-actions">
        <button type="button" data-action="quick-copy-sms">문자 다시 복사</button>
        <button type="button" class="primary" data-action="quick-result-close">회원관리 계속하기</button>
      </div>
    </div>`;
  modal.addEventListener('click',e=>{ if(e.target===modal) closeMemberQuickResult(); });
  document.body.appendChild(modal);
}

