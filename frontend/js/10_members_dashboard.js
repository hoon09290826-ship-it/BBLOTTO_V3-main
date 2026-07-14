/* BBLOTTO V3 frontend split: js/10_members_dashboard.js | original lines 616-860 */
function normalizeSearchText(v){ return String(v||'').toLowerCase().replace(/[\s\-_.()\[\]{}+~`'"·,/:;]/g,'').trim(); }
function ensureMemberSearchStatus(){
  const filter = document.querySelector('.member-filter');
  if(!filter) return null;
  let el = $('memberSearchStatus');
  if(!el){
    el = document.createElement('div');
    el.id = 'memberSearchStatus';
    el.className = 'member-search-status hint';
    filter.insertAdjacentElement('afterend', el);
  }
  return el;
}
function normalizePhoneText(v){ return String(v||'').replace(/\D/g,''); }
function normalizePhoneForSearch(v){ return normalizePhoneText(v); }
function getMemberSearchText(m){
  return normalizeSearchText([
    m.name, m.phone, normalizePhoneText(m.phone), m.grade, memberGradeLabel(m.grade), m.status, m.priority, (m.preferred_count||10)+'조합', m.source, m.memo,
    m.registered_by_name, m.created_by_name, m.registered_by_username, m.created_by, m.admin_name
  ].join(' '));
}
function memberMatchesSearch(m, q){
  if(!q) return true;
  const haystack = getMemberSearchText(m);
  const qDigits = normalizePhoneText(q);
  const tokens = String(q||'').split(/\s+/).map(normalizeSearchText).filter(Boolean);
  const tokenOk = tokens.length ? tokens.every(t => haystack.includes(t)) : false;
  return haystack.includes(q) || tokenOk || (!!qDigits && normalizePhoneText(m.phone).includes(qDigits));
}
function saveMemberFilterState(){
  try{
    localStorage.setItem('bblotto_member_filters', JSON.stringify({
      q: $('memberSearch')?.value || '',
      status: $('memberStatusFilter')?.value || '',
      grade: $('memberGradeFilter')?.value || '',
      priority: $('memberPriorityFilter')?.value || '',
      admin: $('memberAdminFilter')?.value || '',
      sort: $('memberSort')?.value || 'priority',
      pageSize: memberPageSize
    }));
  }catch(e){}
}
function restoreMemberFilterState(){
  try{
    const st = JSON.parse(localStorage.getItem('bblotto_member_filters') || '{}');
    if($('memberSearch')) $('memberSearch').value = st.q || '';
    if($('memberStatusFilter')) $('memberStatusFilter').value = st.status || '';
    if($('memberGradeFilter')) $('memberGradeFilter').value = st.grade || '';
    if($('memberPriorityFilter')) $('memberPriorityFilter').value = st.priority || '';
    if($('memberAdminFilter')) $('memberAdminFilter').value = st.admin || '';
    if($('memberSort')) $('memberSort').value = st.sort || 'priority';
    if(st.pageSize) memberPageSize = Number(st.pageSize) || 10;
  }catch(e){}
}
let memberSearchTimer = null;
function scheduleMemberRefresh(){
  clearTimeout(memberSearchTimer);
  memberSearchTimer = setTimeout(()=>{ saveMemberFilterState(); refreshMemberView(); }, 120);
}
function applyMemberFilters(){
  const q = normalizeSearchText($('memberSearch')?.value || '');
  const status=$('memberStatusFilter')?.value||'';
  const grade=$('memberGradeFilter')?.value||'';
  const priority=$('memberPriorityFilter')?.value||'';
  const adminFilter=$('memberAdminFilter')?.value||'';
  const sort=$('memberSort')?.value||'priority';
  let list = Array.isArray(membersCache) ? [...membersCache] : [];
  if(q) list = list.filter(m => memberMatchesSearch(m, q));
  if(status) list = list.filter(m => String(m.status||'활성') === status);
  if(grade) list = list.filter(m => memberGradeLabel(m.grade) === grade || String(m.grade||'') === grade);
  if(priority) list = list.filter(m => String(m.priority||'보통') === priority);
  if(adminFilter){
    list = list.filter(m => {
      const ownerId=String(m.created_by ?? m.registered_by ?? m.admin_id ?? '');
      const ownerName=normalizeSearchText(m.registered_by_name || m.created_by_name || m.registered_by_username || m.admin_name || '');
      return ownerId===String(adminFilter) || ownerName===normalizeSearchText(adminFilter);
    });
  }
  const pri = {'최우선':0,'높음':1,'보통':2,'낮음':3};
  list.sort((a,b)=>{
    if(sort==='name') return String(a.name||'').localeCompare(String(b.name||''),'ko');
    if(sort==='status') return String(a.status||'활성').localeCompare(String(b.status||'활성'),'ko');
    if(sort==='recent') return String(b.created_at||'').localeCompare(String(a.created_at||''));
    if(sort==='updated') return String(b.updated_at||b.created_at||'').localeCompare(String(a.updated_at||a.created_at||''));
    return (pri[a.priority||'보통']??9)-(pri[b.priority||'보통']??9) || String(b.created_at||'').localeCompare(String(a.created_at||''));
  });
  memberFilteredCache = list;
  const st = ensureMemberSearchStatus();
  if(st){
    const rawQ = $('memberSearch')?.value || '';
    const activeFilters = [rawQ && `검색어 "${rawQ}"`, status && `상태 ${status}`, grade && `등급 ${grade}`, priority && `우선순위 ${priority}`, adminFilter && `등록관리자 ${$('memberAdminFilter')?.selectedOptions?.[0]?.textContent || adminFilter}`].filter(Boolean);
    const maxPageText = Math.max(1, Math.ceil(list.length / memberPageSize));
    st.textContent = activeFilters.length ? `검색 결과 ${list.length.toLocaleString()}명 · ${activeFilters.join(' · ')} · ${memberPage}/${maxPageText}페이지` : `전체 회원 ${list.length.toLocaleString()}명 · ${memberPage}/${maxPageText}페이지`;
  }
  const maxPage = Math.max(1, Math.ceil(list.length / memberPageSize));
  if(memberPage > maxPage) memberPage = maxPage;
  if(memberPage < 1) memberPage = 1;
  return list;
}
function renderPagination(containerId, total, page, pageSize, onPageFn, onSizeFn){
  const box = $(containerId); if(!box) return;
  const maxPage = Math.max(1, Math.ceil((Number(total)||0) / Number(pageSize||10)));
  const start = total ? ((page-1)*pageSize + 1) : 0;
  const end = Math.min(total, page*pageSize);
  const pages=[];
  const from=Math.max(1, page-2), to=Math.min(maxPage, page+2);
  for(let i=from;i<=to;i++) pages.push(`<button type="button" class="page-btn ${i===page?'active':''}" data-action="page-call" data-page-fn="${onPageFn}" data-page="${i}">${i}</button>`);
  box.innerHTML = `<div class="pager-info">총 ${Number(total||0).toLocaleString()}건 · ${start}-${end} 표시</div>
    <div class="pager-actions">
      <select data-action="page-size-call" data-size-fn="${onSizeFn}"><option ${pageSize==10?'selected':''}>10</option><option ${pageSize==20?'selected':''}>20</option><option ${pageSize==30?'selected':''}>30</option><option ${pageSize==50?'selected':''}>50</option><option ${pageSize==100?'selected':''}>100</option></select>
      <button type="button" data-action="page-call" data-page-fn="${onPageFn}" data-page="1" ${page<=1?'disabled':''}>처음</button>
      <button type="button" data-action="page-call" data-page-fn="${onPageFn}" data-page="${page-1}" ${page<=1?'disabled':''}>이전</button>
      ${pages.join('')}
      <button type="button" data-action="page-call" data-page-fn="${onPageFn}" data-page="${page+1}" ${page>=maxPage?'disabled':''}>다음</button>
      <button type="button" data-action="page-call" data-page-fn="${onPageFn}" data-page="${maxPage}" ${page>=maxPage?'disabled':''}>마지막</button>
    </div>`;
}
window.setMemberPage=function(p){ memberPage=Number(p)||1; saveMemberFilterState(); renderMembers(); };
window.setMemberPageSize=function(v){ memberPageSize=Number(v)||10; memberPage=1; saveMemberFilterState(); renderMembers(); };
function renderMembers(list){
  const box=$('memberList'); if(!box) return;
  const source = Array.isArray(list) ? list : applyMemberFilters();
  const start=(memberPage-1)*memberPageSize;
  const pageItems=source.slice(start, start+memberPageSize);
  if(!source.length){
    box.innerHTML='<p class="hint">검색/필터 조건에 맞는 회원이 없습니다.</p>';
    renderPagination('memberPager', 0, 1, memberPageSize, 'setMemberPage', 'setMemberPageSize');
    return;
  }
  box.innerHTML=pageItems.map(m=>{
    const st=m.status||'활성';
    const muted=['휴면','정지','종료','탈퇴'].includes(st);
    const registeredBy = m.registered_by_name || m.created_by_name || m.registered_by_username || m.admin_name || '미지정';
    return `<div class="member-row member-card ${muted?'muted':''}">
      <div>
        <b>${esc(m.name||'')}</b>
        <p>${esc(m.phone||'')} · ${esc(memberGradeLabel(m.grade))} · ${esc(st)} · ${esc(m.priority||'보통')} · 🎯 ${esc(getMemberPreferredCount(m))}조합</p>
        <small class="member-owner-line">등록 관리자: <strong>${esc(registeredBy)}</strong>${m.created_at ? ' · 등록일 ' + esc(toDateInputValue(m.created_at)||m.created_at) : ''}${m.contract_end_at ? ' · 계약만료 ' + esc(toDateInputValue(m.contract_end_at)||m.contract_end_at) : ''}</small>
        <small>${esc(m.memo||'')}</small>
      </div>
      <div class="member-actions"><button class="combo-count-badge combo-generate-copy" data-action="member-generate-copy" data-member-id="${m.id}" title="이 회원 조합수로 추천번호 생성 후 문자 자동 복사">${esc(getMemberPreferredCount(m))}조합</button><button class="sms-save-copy-badge" data-action="member-generate-save" data-member-id="${m.id}" title="추천번호 생성 후 문자 복사와 보낸문자 저장을 같이 실행">복사저장</button><button data-action="member-select" data-member-id="${m.id}">선택</button><button data-action="member-detail" data-member-id="${m.id}">상세페이지</button><button data-action="member-status" data-member-id="${m.id}" data-status="활성">활성</button><button data-action="member-status" data-member-id="${m.id}" data-status="정지">정지</button><button data-action="member-status" data-member-id="${m.id}" data-status="탈퇴">탈퇴</button><button data-action="member-delete" data-member-id="${m.id}">삭제</button></div>
    </div>`;
  }).join('');
  renderPagination('memberPager', source.length, memberPage, memberPageSize, 'setMemberPage', 'setMemberPageSize');
}
function fillMemberSelect(list){
  const sel=$('genMember'); if(!sel) return;
  const prev=String(sel.value||'');
  sel.innerHTML='<option value="">회원 선택 없음</option>'+list.map(m=>`<option value="${m.id}">${esc(m.name)}${m.phone? ' ('+esc(m.phone)+')':''} · ${esc(getMemberPreferredCount(m))}조합</option>`).join('');
  if(prev && Array.from(sel.options).some(o=>String(o.value)===prev)) sel.value=prev;
}

function refreshMemberAdminFilter(){
  const sel=$('memberAdminFilter'); if(!sel) return;
  const prev=String(sel.value||'');
  const map=new Map();
  (Array.isArray(adminCache)?adminCache:[]).forEach(a=>{ if(a?.id) map.set(String(a.id), a.name||a.username||'관리자'); });
  (Array.isArray(membersCache)?membersCache:[]).forEach(m=>{
    const id=String(m.created_by ?? m.registered_by ?? m.admin_id ?? '');
    const name=m.registered_by_name || m.created_by_name || m.registered_by_username || m.admin_name || '';
    if(id && name) map.set(id,name);
  });
  sel.innerHTML='<option value="">전체 등록관리자</option>'+Array.from(map.entries()).sort((a,b)=>String(a[1]).localeCompare(String(b[1]),'ko')).map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
  if(prev && Array.from(sel.options).some(o=>String(o.value)===prev)) sel.value=prev;
}

async function loadMembers(){
  restoreMemberFilterState();
  const params = new URLSearchParams();
  params.set('limit', '5000');
  const sort=$('memberSort')?.value||'priority';
  if(sort) params.set('sort', sort);
  // 서버에는 권한 범위만 맡기고, 검색/필터/페이지는 전체 목록 기준으로 프론트에서 처리합니다.
  membersCache = await api('/api/members' + (params.toString() ? '?'+params.toString() : ''));
  refreshMemberAdminSelect();
  refreshMemberAdminFilter();
  applyMemberFilters();
  renderMembers(memberFilteredCache); fillMemberSelect(membersCache); refreshSmsScopeInfo();
  setText('memberActive', membersCache.filter(m=>(m.status||'활성')==='활성').length);
  setText('memberVip', membersCache.filter(m=>['1등','2등','VIP','다이아','프리미엄'].includes(String(m.grade||''))).length);
  setText('memberPriority', membersCache.filter(m=>(m.priority||'').includes('높') || (m.priority||'').includes('최')).length);
}
function refreshMemberView(){ memberPage=1; applyMemberFilters(); renderMembers(memberFilteredCache); }
function rc44Money(v){ return Number(v||0).toLocaleString() + '원'; }
function rc44Rows(items, empty){
  if(!Array.isArray(items) || !items.length) return `<div class="empty-detail">${esc(empty||'데이터가 없습니다.')}</div>`;
  return items.map(x=>`<div class="rc44-row"><div><b>${esc(x.title||x.name||x.member_name||x.username||'-')}</b><small>${esc(x.sub||x.detail||x.created_at||'')}</small></div><strong>${esc(x.value||x.action||x.rank||'')}</strong></div>`).join('');
}
async function loadRc44Dashboard(){
  const d = await api('/api/rc4-4/admin-dashboard');
  const k = d.kpi || {};
  setText('memberCount', k.total_members ?? 0);
  setText('latestRound', d.latest_draw?.round_no ?? '-');
  setText('recCount', k.recommendations_total ?? 0);
  setText('smsCount', k.sms_today ?? 0);
  setText('rc44TodayRec', k.recommendations_today ?? 0);
  setText('rc44TodayLogin', k.login_today ?? 0);
  const sub=$('rc44AdminSub'); if(sub) sub.textContent=`활성 ${k.active_members||0}명 · 1등/2등 ${k.vip_members||0}명 · 우선관리 ${k.priority_members||0}명 · 총 당첨금 ${rc44Money(k.total_prize||0)}`;
  const alerts=$('rc44Alerts'); if(alerts) alerts.innerHTML=(d.alerts||[]).map(a=>`<div class="rc44-alert ${esc(a.type||'')}">${esc(a.message||'')}</div>`).join('');
  const ops=$('rc44Ops'); if(ops) ops.innerHTML=`<div class="rc44-mini-grid"><div class="rc44-mini"><b>${k.activity_today||0}</b><span>오늘 활동</span></div><div class="rc44-mini"><b>${k.wins_today||0}</b><span>오늘 적중</span></div><div class="rc44-mini"><b>${k.max_ai_score||0}</b><span>최고 AI점수</span></div></div>` + rc44Rows((d.recent_members||[]).map(m=>({title:m.name, sub:`${m.grade||'일반'} · ${m.status||'활성'} · ${m.priority||'보통'}`, value:m.created_at||''})), '최근 가입 회원이 없습니다.');
  const recent=$('recentRecs'); if(recent) recent.innerHTML=rc44Rows((d.recent_recommendations||[]).map(r=>({title:`${r.round_no||'-'}회 · ${r.member_name||'회원'}`, sub:`${r.mode||'balanced'} · ${r.count||0}조합 · ${r.created_at||''}`, value:`AI ${Number(r.avg_score||0).toFixed(1)}`})), '최근 생성 이력이 없습니다.');
  const logs=$('rc44Logs'); if(logs) logs.innerHTML=rc44Rows((d.recent_logs||[]).map(l=>({title:l.username||'admin', sub:l.detail||l.created_at||'', value:l.action||''})), '최근 관리자 활동이 없습니다.');
}
async function loadRc44AiStatus(){
  const d = await api('/api/rc4-4/ai-status');
  const engineMini=$('engineMini');
  const total=(d.today||[]).reduce((a,r)=>a+Number(r.count||0),0);
  if(engineMini) engineMini.textContent=`RC4-4 AI 추천 현황 · 오늘 ${d.today?.length||0}건 / ${total}조합`;
  const box=$('rc44AiStatus'); if(!box) return;
  const modeRows=(d.by_mode||[]).map(r=>({title:r.mode||'balanced', sub:`평균 AI ${Number(r.avg_score||0).toFixed(1)}점`, value:`${r.c||0}건`}));
  const todayRows=(d.today||[]).slice(0,6).map(r=>({title:`${r.round_no||'-'}회 · ${r.member_name||'회원'}`, sub:`${r.mode||'balanced'} · ${r.count||0}조합 · ${r.created_at||''}`, value:`${Number(r.avg_score||0).toFixed(1)}점`}));
  box.innerHTML=`<h4>모드별 추천</h4>${rc44Rows(modeRows,'모드별 데이터 없음')}<h4>오늘 생성 로그</h4>${rc44Rows(todayRows,'오늘 생성 이력 없음')}`;
}
async function loadDashboard(){
  try{
    await loadRc44Dashboard();
    return true;
  }catch(e){
    console.warn('RC4-4 대시보드 실패, 기본 대시보드 사용', e);
  }
  try{
    let d;
    try{ d=await api('/api/dashboard_v2'); }
    catch(_){ d=await api('/api/dashboard_summary'); }
    setText('memberCount', d.members ?? 0); setText('latestRound', d.latest_round ?? '-'); setText('recCount', d.recommendations ?? 0); setText('smsCount', d.sms ?? 0);
    const engineMini=$('engineMini'); if(engineMini) engineMini.textContent=`${d.engine_version||'AI'} · 평균 ${d.avg_ai_score||0}점 · 오늘 ${d.today_recommendations||0}건`;
    const recent=$('recentRecs'); if(recent) recent.innerHTML=(d.recent_recommendations||[]).map(r=>`<p>${r.round_no}회 · ${esc(r.member_name||'회원')} · ${esc(r.created_at||'')}</p>`).join('') || '최근 생성 이력이 없습니다.';
    return true;
  }catch(e){
    console.error('대시보드 로딩 실패', e);
    setText('memberCount', '0'); setText('latestRound', '-'); setText('recCount', '0'); setText('smsCount', '0');
    const sub=$('rc44AdminSub'); if(sub) sub.textContent='대시보드 일부 데이터를 불러오지 못했습니다. 회원관리/추천번호 기능은 계속 사용할 수 있습니다.';
    return false;
  }
}
async function rc44RunAutoUpdate(){
  if(!confirm('최신회차 조회, 통계 갱신, 회원 적중 계산을 실행할까요?')) return;
  const box=$('rc44AutoResult'); if(box){ box.style.display='block'; box.innerHTML='자동 업데이트 실행 중입니다...'; }
  try{
    const d=await api('/api/rc4-4/auto-update?backfill=12',{method:'POST'});
    if(box) box.innerHTML=`<h3>자동 업데이트 결과</h3>${(d.steps||[]).map(s=>`<div class="rc44-step"><b>${esc(s.name)}</b><span class="${s.ok?'ok':'fail'}">${s.ok?'완료':'실패'}</span></div>`).join('')}<p class="hint">성공 ${d.success_count||0}건 / 실패 ${d.failed_count||0}건</p>`;
    await Promise.allSettled([loadDashboard(), loadStats(0), loadDraws(), loadMembers()]);
    toast('RC4-4 자동 업데이트가 완료되었습니다.');
  }catch(e){ if(box) box.innerHTML=`<b>자동 업데이트 실패</b><p>${esc(e.message||e)}</p>`; }
}
