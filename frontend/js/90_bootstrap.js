/* BBLOTTO V3 frontend split: js/90_bootstrap.js | original lines 2351-2711 */
function initMobileNavigation(){
  const aside=document.querySelector('aside');
  const main=document.querySelector('main');
  if(aside && !$('mobileMenuToggle')){
    const toggle=document.createElement('button');
    toggle.id='mobileMenuToggle';
    toggle.className='mobile-menu-toggle';
    toggle.type='button';
    toggle.textContent='✕ 메뉴 닫기';
    aside.insertBefore(toggle, aside.querySelector('.nav'));
    toggle.addEventListener('click',()=>aside.classList.toggle('nav-open'));
  }
  if(main && !document.querySelector('.mobile-quick-nav')){
    const quick=document.createElement('nav');
    quick.className='mobile-quick-nav';
    quick.setAttribute('aria-label','모바일 바로가기');
    quick.innerHTML='<strong>BBLOTTO</strong><button class="nav" data-tab="generator">추천</button><button class="nav" data-tab="members">회원</button><button type="button" data-mobile-menu="1">전체메뉴</button>';
    main.prepend(quick);
    quick.querySelector('[data-mobile-menu]')?.addEventListener('click',()=>aside?.classList.toggle('nav-open'));
  }
  const members=$('members');
  if(members && !members.querySelector('.mobile-member-switch')){
    const controls=document.createElement('div');
    controls.className='mobile-member-switch';
    controls.innerHTML='<button type="button" data-member-view="list" class="active">회원 목록</button><button type="button" data-member-view="form">회원 등록/수정</button>';
    members.prepend(controls);
    members.classList.add('member-mobile-list');
    window.setMobileMemberView=(view='list')=>{
      const button=controls.querySelector(`[data-member-view="${view}"]`);
      members.classList.toggle('member-mobile-list',view==='list');
      members.classList.toggle('member-mobile-form',view==='form');
      controls.querySelectorAll('button').forEach(item=>item.classList.toggle('active',item===button));
    };
    controls.addEventListener('click',(event)=>{
      const button=event.target.closest('[data-member-view]');
      if(!button) return;
      const view=button.dataset.memberView;
      window.setMobileMemberView(view);
      members.scrollIntoView({behavior:'smooth',block:'start'});
    });
  }
  const memberFilter=document.querySelector('#members .member-filter');
  if(memberFilter && !memberFilter.querySelector('.mobile-filter-toggle')){
    const filterToggle=document.createElement('button');
    filterToggle.type='button';
    filterToggle.className='mobile-filter-toggle';
    filterToggle.textContent='필터';
    memberFilter.append(filterToggle);
    filterToggle.addEventListener('click',()=>{
      const open=memberFilter.classList.toggle('filters-open');
      filterToggle.textContent=open?'필터 닫기':'필터';
    });
  }
}
function bind(){
  initMobileNavigation();
  // RC11.7: 왼쪽 메뉴는 한 개의 위임 라우터로만 처리합니다.
  // 기존 브라우저 캐시나 일부 초기 로딩 실패가 있어도 메뉴 전환은 항상 동작합니다.
  if(!window.__bbPrimaryNavBound){
    window.__bbPrimaryNavBound=true;
    document.addEventListener('click', function(e){
      const btn=e.target && e.target.closest ? e.target.closest('button.nav[data-tab]') : null;
      if(!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const tab=String(btn.dataset.tab||'dashboard');
      openPanel(tab, btn.textContent.trim());
      if(tab==='members' && typeof window.setMobileMemberView==='function') window.setMobileMemberView('list');
      document.querySelector('aside')?.classList.remove('nav-open');
      const loaders={
        dashboard:()=>loadDashboard(),
        members:()=>loadMembers(),
        winning:()=>Promise.allSettled([loadDraws(),setNextDrawRound()]),
        stats:()=>loadStats(0),
        account:()=>loadMyAccount(),
        admin:()=>loadAdmin()
      };
      try{
        const job=loaders[tab]?.();
        if(job && typeof job.catch==='function') job.catch(err=>{ console.error(tab+' 화면 로딩 실패',err); toast((err&&err.message)||'화면 데이터를 불러오지 못했습니다.'); });
      }catch(err){ console.error(tab+' 메뉴 실행 실패',err); }
    }, true);
  }
  $('logout')?.addEventListener('click',safe(async()=>{ try{await api('/api/logout',{method:'POST'});}catch(e){} localStorage.removeItem('bb_v34_token'); location.href='/'; }));
  $('saveMyProfile')?.addEventListener('click',safe(saveMyProfile));
  $('saveMyPassword')?.addEventListener('click',safe(saveMyPassword));
  $('generate')?.addEventListener('click',safe(generate));
  $('addMember')?.addEventListener('click',safe(addMember));
  $('saveMemberBtn')?.addEventListener('click',safe(saveMember));
  $('clearMember')?.addEventListener('click',()=>{ ['mId','mName','mPhone','mMemo'].forEach(x=>setValue(x,'')); setValue('mCreatedBy',''); setValue('mCreatedAt',''); setValue('mContractPeriod','12'); setValue('mContractEndAt',''); setValue('mPreferredCount','10'); refreshMemberAdminSelect(); });
  $('mCreatedAt')?.addEventListener('change', calcContractEnd);
  $('mContractPeriod')?.addEventListener('change', calcContractEnd);
  $('memberDetailBack')?.addEventListener('click',()=>openPanel('members','회원 관리'));
  $('memberSearch')?.addEventListener('input',()=>scheduleMemberRefresh());
  $('memberSearch')?.addEventListener('keydown',(e)=>{ if(e.key==='Enter'){ e.preventDefault(); clearTimeout(memberSearchTimer); saveMemberFilterState(); refreshMemberView(); } });
  $('memberStatusFilter')?.addEventListener('change',()=>{ saveMemberFilterState(); refreshMemberView(); });
  $('memberGradeFilter')?.addEventListener('change',()=>{ saveMemberFilterState(); refreshMemberView(); });
  $('memberPriorityFilter')?.addEventListener('change',()=>{ saveMemberFilterState(); refreshMemberView(); });
  $('memberAdminFilter')?.addEventListener('change',()=>{ saveMemberFilterState(); refreshMemberView(); });
  $('memberSort')?.addEventListener('change',()=>{ memberPage=1; saveMemberFilterState(); applyMemberFilters(); renderMembers(memberFilteredCache); });
  $('genMember')?.addEventListener('change',()=>{ applySelectedMemberPreferredCount(); refreshSmsPreview(); });
  $('saveTemplate')?.addEventListener('click',safe(saveTemplate));
  $('autoTemplate')?.addEventListener('click',autoTemplate);
  $('resetTemplate')?.addEventListener('click',resetTemplate);
  $('clearTemplate')?.addEventListener('click',clearTemplate);
  $('template')?.addEventListener('input',()=>{ refreshSmsPreview(); saveWorkspaceState(); });
  $('genMember')?.addEventListener('change',saveWorkspaceState);
  $('genCount')?.addEventListener('change',saveWorkspaceState);
  $('genMode')?.addEventListener('change',saveWorkspaceState);
  $('copyNums')?.addEventListener('click',safe(async()=>{
    const text=currentCombos.map((a,i)=>`${i+1}. ${a.join(', ')}`).join('\n');
    await copyTextToClipboard(text);
    toast('번호를 복사했습니다.');
  }));
  $('copySms')?.addEventListener('click',async()=>{try{await copyTextToClipboard($('smsPreview')?.value||currentSms); toast('회원 안내 문구를 복사했습니다.');}catch(e){alert(e.message||'복사 실패');}});
  $('copyAndSaveSmsLog')?.addEventListener('click',copyAndSaveSmsLog);
  $('saveRecommendationOnly')?.addEventListener('click',saveRecommendationOnly);
  $('sendSmsBtn')?.addEventListener('click',()=>{refreshSmsPreview(); scrollToMessagePanel(); $('smsPreview')?.focus();});
  $('saveSmsLog')?.addEventListener('click',safe(saveSmsLog));
  $('exportSmsCsvAll')?.addEventListener('click',()=>downloadSmsCsv('all'));
  $('exportSmsCsvSelected')?.addEventListener('click',()=>downloadSmsCsv('selected'));
  $('copySmsBulk')?.addEventListener('click',copyBulkSmsText);
  $('applyBulkTemplate')?.addEventListener('click',applyBulkTemplateToPreview);
  $('bulkSmsTemplate')?.addEventListener('input',()=>{ saveWorkspaceState(); setText('smsExportInfo','수정한 문구가 CSV/복사에 적용됩니다.'); });
  if(typeof initSmsSegments === 'function') initSmsSegments();
  $('smsCsvScope')?.addEventListener('change',()=>{ refreshSmsScopeInfo(); if(typeof refreshSmsSegmentPreview === 'function') refreshSmsSegmentPreview(); setText('smsExportInfo', getSmsScopeLabel(getSmsScopeValue()) + ' 기준으로 파일이 생성됩니다.'); });
  $('checkWinning')?.addEventListener('click',safe(checkWinning));
  $('saveDraw')?.addEventListener('click',safe(saveDraw));
  $('searchDraw')?.addEventListener('click',safe(searchDrawByRound));
  $('drawSearchRound')?.addEventListener('keydown',e=>{ if(e.key==='Enter') searchDrawByRound(); });
  $('applySearchedDraw')?.addEventListener('click',safe(applySearchedDrawToCheck));
  $('addAdmin')?.addEventListener('click',safe(addAdmin));
  $('openAdminModal')?.addEventListener('click',openAdminCreateModal);
  $('closeAdminModal')?.addEventListener('click',closeAdminCreateModal);
  $('cancelAdminModal')?.addEventListener('click',closeAdminCreateModal);
  $('adminCreateModal')?.addEventListener('click',e=>{ if(e.target && e.target.id==='adminCreateModal') closeAdminCreateModal(); });
  document.querySelectorAll('.admin-tab-btn').forEach(b=>b.addEventListener('click',()=>switchAdminPanel(b.dataset.adminPanel)));

  $('saveSessionTimeout')?.addEventListener('click',safe(saveSessionTimeout));
  $('createBackup')?.addEventListener('click',safe(createBackup));
  $('rc44AutoUpdate')?.addEventListener('click',safe(rc44RunAutoUpdate));
  $('rc44Refresh')?.addEventListener('click',safe(async()=>{ await loadDashboard(); await loadStats(0); await loadMembers(); toast('RC4-4 화면을 새로고침했습니다.'); }));
  document.querySelectorAll('.statBtn').forEach(b=>b.addEventListener('click',()=>loadStats(b.dataset.limit).catch(e=>alert(e.message))));
  $('pdfBtn')?.addEventListener('click',()=>window.print());
  $('checkAiV6Cache')?.addEventListener('click', safe(checkAiV6CacheStatus));
  $('syncAiV6FullHistory')?.addEventListener('click', safe(syncAiV6FullHistory));

  // RC11.1: CSP가 인라인 onclick을 차단해도 모든 동적 버튼이 작동하도록
  // 허용된 data-action만 처리하는 단일 이벤트 위임기를 사용한다.
  if(!window.__bbActionRouterBound){
    window.__bbActionRouterBound=true;
    document.addEventListener('click', safe(async function(e){
      const btn=e.target?.closest?.('button[data-action]');
      if(!btn || btn.disabled) return;
      const a=btn.dataset.action;
      const n=(k)=>Number(btn.dataset[k]||0);
      if(a==='download-api') return downloadApi(btn.dataset.url||'');
      if(a==='page-call'){
        const allowed=['setMemberPage','setStatsPage','setDrawPage','setWinCheckPage','setWinningPage','setSmsLogPage','setRecommendationPage'];
        const fn=btn.dataset.pageFn;
        if(allowed.includes(fn) && typeof window[fn]==='function') return window[fn](n('page'));
        return;
      }
      if(a==='member-generate-copy') return generateMemberAndCopy(n('memberId'),btn);
      if(a==='member-generate-save') return generateMemberCopyAndSave(n('memberId'),btn);
      if(a==='member-select') return selectMember(n('memberId'));
      if(a==='member-detail') return detailMember(n('memberId'));
      if(a==='member-status') return quickMemberStatus(n('memberId'),btn.dataset.status||'활성');
      if(a==='member-delete') return deleteMember(n('memberId'));
      if(a==='winning-toggle') return toggleWinMember(btn.dataset.key||'');
      if(a==='sms-delete'){ e.preventDefault(); e.stopPropagation(); return deleteSmsLog(n('logId'),n('memberId')); }
      if(a==='backup-restore') return restoreBackup(btn.dataset.file||'');
      if(a==='admin-edit') return window.editAdmin(n('adminId'));
      if(a==='admin-toggle') return toggleAdmin(n('adminId'),n('active'));
      if(a==='admin-activate') return activateAdmin(n('adminId'));
      if(a==='admin-delete') return deleteAdmin(n('adminId'),btn.dataset.username||'');
      if(a==='admin-my-password') return changeMyPassword(n('adminId'));
      if(a==='quick-result-close') return closeMemberQuickResult();
      if(a==='quick-copy-sms'){ await copyTextToClipboard($('smsPreview')?.value||currentSms); return toast('문자 내용을 다시 복사했습니다.'); }
      if(a==='member-memo-save') return saveMemberMemo(n('memberId'));
      if(a==='member-note-save') return saveMemberNote(n('memberId'));
      if(a==='manual-sms-save') return saveManualSmsLog(n('memberId'));
    }));
  }
  if(!window.__bbPageSizeRouterBound){
    window.__bbPageSizeRouterBound=true;
    document.addEventListener('change', safe(function(e){
      const select=e.target?.closest?.('select[data-action="page-size-call"]');
      if(!select) return;
      const allowed=['setMemberPageSize','setStatsPageSize','setDrawPageSize','setWinCheckPageSize','setWinningPageSize','setSmsLogPageSize','setRecommendationPageSize'];
      const fn=select.dataset.sizeFn;
      if(allowed.includes(fn) && typeof window[fn]==='function') return window[fn](select.value);
    }));
  }
  // STABLE-5: 핵심 버튼 바인딩 완료 신호. 별도 안전망은 이 신호가 없을 때만 작동합니다.
  window.__bbBindingsReady = true;
  document.documentElement.dataset.bblottoBindings = 'ready';
}

async function init(){
  if(!token()){ location.href='/'; return; }
  bind();
  try{
    // RC5.3 FIX: 관리자 권한을 먼저 확정한 뒤 화면을 불러온다.
    // 이전 버전은 /api/me 응답 전에 loadAdmin()이 실행되어 최고관리자도
    // 생성/수정 버튼이 disabled 상태로 남는 문제가 있었다.
    currentAdmin = await api('/api/me');
    setText('who', currentAdmin.name || currentAdmin.username || '관리자');
    startSessionWatcher(currentAdmin);
    applyAdminVisibility(!!currentAdmin?.is_super_admin);
  }catch(e){
    console.error(e);
    setText('who','관리자');
  }
  try{
    const tasks = [
      ['dashboard', loadDashboard()],
      ['members', loadMembers()],
      ['template', loadTemplate()],
      ['stats', loadStats(0)],
      ['draws', loadDraws()],
      ['nextRound', setNextDrawRound()]
    ];
    const results = await Promise.allSettled(tasks.map(x=>x[1]));
    const failed = results.map((r,i)=>({r,name:tasks[i][0]})).filter(x=>x.r.status==='rejected');
    if(failed.length){
      console.warn('초기 로딩 일부 실패', failed.map(x=>x.name), failed);
      toast('일부 현황 데이터 로딩 실패 · 기능은 계속 사용 가능합니다.');
    }
    const restored = restoreWorkspaceState() || await restoreLatestRecommendationFromServer();
    if(!restored){ renderCombos([]); refreshSmsPreview(); }
  }catch(e){ console.error(e); toast(e.message || e); }
}

// ===================== RC7-1: 회원별 문자 CSV AI Engine V2 =====================
// 전체/선택 CSV 생성 시 회원마다 추천번호와 분석요약이 달라지도록 프론트에서도 분산 생성합니다.
function rc71HashSeed(){
  const raw = Array.from(arguments).map(v=>String(v||'')).join('|');
  let h = 2166136261;
  for(let i=0;i<raw.length;i++){ h ^= raw.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function rc71Rand(seed){
  let x = seed >>> 0;
  return function(){ x = (Math.imul(1664525, x) + 1013904223) >>> 0; return x / 4294967296; };
}
function rc71NormalizeCombo(c){
  const nums = (Array.isArray(c) ? c : parseNums(c)).map(n=>Number(n)).filter(n=>n>=1&&n<=45);
  return Array.from(new Set(nums)).sort((a,b)=>a-b).slice(0,6);
}
function rc71MakeComboFromBase(base, rng, salt){
  let nums = rc71NormalizeCombo(base);
  if(nums.length < 6){ nums = []; }
  const out = new Set();
  nums.forEach((n,idx)=>{
    const move = 1 + Math.floor(rng()*9) + ((salt + idx) % 5);
    let v = ((n + move - 1) % 45) + 1;
    let guard = 0;
    while(out.has(v) && guard < 60){ v = (v % 45) + 1; guard++; }
    out.add(v);
  });
  while(out.size < 6){
    let v = 1 + Math.floor(rng()*45);
    let guard = 0;
    while(out.has(v) && guard < 60){ v = (v % 45) + 1; guard++; }
    out.add(v);
  }
  return Array.from(out).sort((a,b)=>a-b);
}
function rc71ComboKey(c){ return rc71NormalizeCombo(c).join('-'); }
function rc71MemberCombos(member, index, count){
  const base = normalizeCombos(currentCombos);
  const target = Math.max(1, Math.min(50, count || base.length || 10));
  const seed = rc71HashSeed(currentRound||'', member?.id||'', member?.name||'', member?.phone||'', index, target);
  const rng = rc71Rand(seed);
  const rows = [];
  const seen = new Set();
  for(let i=0;i<target*8 && rows.length<target;i++){
    const b = base.length ? base[(i + Math.floor(rng()*base.length)) % base.length] : [];
    const combo = rc71MakeComboFromBase(b, rng, i + index);
    const key = rc71ComboKey(combo);
    if(seen.has(key)) continue;
    // 회원 간/조합 간 너무 똑같은 느낌을 줄이기 위해 합계와 홀짝 기본 범위만 가볍게 확인
    const sum = combo.reduce((a,b)=>a+b,0);
    const odd = combo.filter(n=>n%2).length;
    if(sum < 85 || sum > 200 || odd < 1 || odd > 5) continue;
    seen.add(key); rows.push(combo);
  }
  while(rows.length<target){
    const combo = rc71MakeComboFromBase([], rng, rows.length + index + 99);
    const key = rc71ComboKey(combo);
    if(!seen.has(key)){ seen.add(key); rows.push(combo); }
  }
  return rows.slice(0,target);
}
function rc71MemberAnalysis(member, combos, index){
  const seed = rc71HashSeed(currentRound||'', member?.id||'', member?.name||'', member?.phone||'', index, JSON.stringify(combos));
  const pick = (arr,salt)=>arr[(seed+salt)%arr.length];
  const flat = combos.flat().map(Number);
  const unique = Array.from(new Set(flat));
  const counts = {};
  flat.forEach(n=>{ counts[n]=(counts[n]||0)+1; });
  const core = unique.sort((a,b)=>(counts[b]||0)-(counts[a]||0)||a-b).slice(0,6).join(', ');
  const low = flat.filter(n=>n<=15).length, mid = flat.filter(n=>n>=16&&n<=30).length, high = flat.filter(n=>n>=31).length;
  const odd = flat.filter(n=>n%2).length, even = flat.length - odd;
  const openers = [
    `${currentRound||'-'}회차는 회원별 추천 흐름을 분리해 맞춤형 조합으로 구성했습니다.`,
    `${currentRound||'-'}회차는 최근 흐름과 누적 데이터를 함께 비교해 회원별 조합을 선별했습니다.`,
    `이번 회차는 특정 번호대에 치우치지 않도록 회원별 번호 분산을 적용했습니다.`,
    `최근 강세 구간과 보강 후보를 함께 반영해 ${member?.name||'회원'}님 전용 조합을 구성했습니다.`
  ];
  const middles = [
    `핵심 후보는 ${core||'자동 산출'} 중심이며, 조합 간 중복을 줄이는 방향으로 정리했습니다.`,
    `홀짝 흐름은 홀수 ${odd}개/짝수 ${even}개 기준으로 점검했습니다.`,
    `저·중·고 구간 분포는 ${low}/${mid}/${high} 흐름으로 맞춰 편중을 줄였습니다.`,
    `끝수 반복과 연속수 과다 사용을 제한해 조합별 형태가 겹치지 않도록 했습니다.`
  ];
  const closers = [
    `단순 빈도보다 번호 간 균형과 최근 흐름을 함께 본 추천입니다.`,
    `최근 데이터와 누적 통계를 함께 고려한 심층 추천 결과입니다.`,
    `안정성과 변화 가능성을 함께 반영한 회원별 추천입니다.`,
    ``
  ];
  return [pick(openers,1), pick(middles,7), pick(middles,13), pick(closers,19)].filter((v,i,a)=>v && a.indexOf(v)===i).slice(0,4).join('\n');
}
function buildSmsExportRows(scope='all'){
  const members = smsExportMembers(scope);
  if(!members.length) return [];
  const round = currentRound || '';
  const baseCount = normalizeCombos(currentCombos).length || 10;
  return members.map((m, idx)=>{
    const memberCombos = rc71MemberCombos(m, idx, baseCount);
    const memberAnalysis = rc71MemberAnalysis(m, memberCombos, idx);
    const segs = (typeof buildSmsSegmentsForMember === 'function') ? buildSmsSegmentsForMember(m, round, memberCombos, memberAnalysis) : {};
    const message = (typeof buildSmsSegmentFullMessage === 'function') ? buildSmsSegmentFullMessage(m, round, memberCombos, memberAnalysis) : buildBulkSmsMessage(m, round, memberCombos, memberAnalysis);
    return {
      name: m.name || '',
      phone: String(m.phone || '').replace(/[^0-9]/g, ''),
      message: normalizeSmsLineBreaks(message),
      round,
      numbers: formatComboLines(memberCombos),
      grade: m.grade || '',
      status: m.status || '활성',
      seg1: normalizeSmsLineBreaks(segs.seg1 || ''),
      seg2: normalizeSmsLineBreaks(segs.seg2 || ''),
      seg3: normalizeSmsLineBreaks(segs.seg3 || ''),
      seg4: normalizeSmsLineBreaks(segs.seg4 || '')
    };
  });
}
function applyBulkTemplateToPreview(){
  const m = getSelectedMember() || (membersCache && membersCache[0]) || {name:'회원'};
  const combos = rc71MemberCombos(m, 0, normalizeCombos(currentCombos).length || 10);
  const analysis = rc71MemberAnalysis(m, combos, 0);
  const txt = (typeof buildSmsSegmentFullMessage === 'function') ? buildSmsSegmentFullMessage(m, currentRound || '', combos, analysis) : buildBulkSmsMessage(m, currentRound || '', combos, analysis);
  if($('smsPreview')){ $('smsPreview').value = txt; autoGrowTextarea($('smsPreview')); }
  if($('smsSegmentPreview')){ $('smsSegmentPreview').value = txt; autoGrowTextarea($('smsSegmentPreview')); }
  setText('smsExportInfo', '회원별 추천번호와 분석요약을 다르게 적용했습니다. CSV 생성 시 각 회원별로 자동 치환됩니다.');
  toast('회원별 문구 미리보기를 적용했습니다.');
}
// ===================== /RC7-1 =====================

init();

// ===== RC2 Sprint 4: operations helper =====
async function loadOpsHealth(){
  try{
    const d = await api('/api/ops/health');
    console.log('[BBLOTTO OPS]', d);
    const el = document.getElementById('engineStatus');
    if(el){
      const free = d.disk && d.disk.free_mb ? d.disk.free_mb : '-';
      el.textContent = `운영상태 ${d.ok?'정상':'점검필요'} · DB ${d.db?.size_bytes||0} bytes · 여유 ${free}MB`;
    }
    return d;
  }catch(e){ console.warn('ops health failed', e); return null; }
}
setTimeout(()=>{ if(typeof token==='function' && token()) loadOpsHealth(); }, 1200);




// RC8.18: manual message-history addition and saved-only recommendation workflow preparation.
