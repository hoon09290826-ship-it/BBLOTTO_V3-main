/* BBLOTTO V3 frontend split: js/40_recommendations.js | original lines 1453-1773 */
async function saveCurrentRecommendation(){
  if(currentRecId) return {id:currentRecId, saved:true, reused:true};
  const mid=$('genMember')?.value;
  if(!mid) throw new Error('회원을 선택해야 추천번호를 저장할 수 있습니다.');
  const combos=normalizeCombos(currentCombos);
  if(!combos.length) throw new Error('먼저 추천번호를 생성하세요.');
  const member=getSelectedMember();
  const payload={
    member_id:Number(mid), member_name:member?.name||'', round_no:Number(currentRound||0),
    mode:$('genMode')?.value||'balanced', combos,
    analysis:String(currentAnalysis||''), sms:String($('smsPreview')?.value||currentSms||''),
    details:Array.isArray(currentDetails)?currentDetails:[], engine:{}
  };
  const d=await api('/api/recommendations/save',{method:'POST',body:payload});
  currentRecId=d.id||null;
  saveWorkspaceState();
  return d;
}

async function saveRecommendationOnly(){
  try{
    await saveCurrentRecommendation();
    toast('추천번호를 저장했습니다. 당첨확인 대상에 등록되었습니다.');
    await Promise.all([loadDashboard(),loadMembers()]);
  }catch(e){ alert(e.message||'추천번호 저장 중 오류가 발생했습니다.'); }
}

async function saveCurrentSmsLog(){
  const mid=$('genMember')?.value;
  if(!mid){ throw new Error('회원을 선택해야 보낸문자를 저장할 수 있습니다.'); }
  const member=getSelectedMember();
  const text=($('smsPreview')?.value || currentSms || '').trim();
  if(!text){ throw new Error('저장할 문자 내용이 없습니다.'); }
  const body={
    member_id:Number(mid),
    member_name:member?.name||'',
    phone:member?.phone||'',
    round_no:Number(currentRound||0),
    body:text,
    combos:normalizeCombos(currentCombos),
    send_now:false
  };
  const savedRecommendation=await saveCurrentRecommendation();
  body.recommendation_id=Number(savedRecommendation?.id||currentRecId||0)||null;
  try{ return await api('/api/sms_log',{method:'POST',body}); }
  catch(e){ return await api('/api/sms',{method:'POST',body}); }
}

window.generateMemberAndCopy = safe(async function(id, btn){
  const m=membersCache.find(x=>String(x.id)===String(id));
  if(!m){ alert('회원을 찾을 수 없습니다.'); return; }
  const oldText = btn?.textContent;
  try{
    if(btn){ btn.disabled=true; btn.textContent='생성중'; }
    window.selectMember(id);
    setGenCountValue(getMemberPreferredCount(m));
    quickMemberGenerationMode=true;
    try{ await generate(); } finally { quickMemberGenerationMode=false; }
    const expected=getMemberPreferredCount(m);
    if(normalizeCombos(currentCombos).length!==expected) throw new Error(`추천번호 ${expected}조합 생성 확인에 실패했습니다.`);
    if(!String(currentAnalysis||'').trim()) throw new Error('분석요약 생성 확인에 실패했습니다.');
    const text = ($('smsPreview')?.value || currentSms || '').trim();
    await copyTextToClipboard(text);
    showMemberQuickResult(m, currentCombos, currentAnalysis, true, false);
    toast(`${m.name} ${expected}조합 생성·분석·문자 복사 완료`);
    if(btn) btn.textContent='복사완료';
    setTimeout(()=>{ if(btn){ btn.textContent=oldText || `${getMemberPreferredCount(m)}조합`; btn.disabled=false; } }, 1200);
  }catch(e){
    console.error(e);
    if(btn){ btn.textContent=oldText || `${getMemberPreferredCount(m)}조합`; btn.disabled=false; }
    alert('자동 생성/복사 실패: '+(e.message||e));
  }
});

window.generateMemberCopyAndSave = safe(async function(id, btn){
  const m=membersCache.find(x=>String(x.id)===String(id));
  if(!m){ alert('회원을 찾을 수 없습니다.'); return; }
  const oldText = btn?.textContent;
  try{
    if(btn){ btn.disabled=true; btn.textContent='생성중'; }
    window.selectMember(id);
    setGenCountValue(getMemberPreferredCount(m));
    quickMemberGenerationMode=true;
    try{ await generate(); } finally { quickMemberGenerationMode=false; }
    const expected=getMemberPreferredCount(m);
    if(normalizeCombos(currentCombos).length!==expected) throw new Error(`추천번호 ${expected}조합 생성 확인에 실패했습니다.`);
    if(!String(currentAnalysis||'').trim()) throw new Error('분석요약 생성 확인에 실패했습니다.');
    const text = ($('smsPreview')?.value || currentSms || '').trim();
    await copyTextToClipboard(text);
    const savedSms=await saveCurrentSmsLog();
    if(!currentRecId) throw new Error('추천번호 저장 연동 확인에 실패했습니다.');
    if(!savedSms || (!savedSms.id && !savedSms.ok)) throw new Error('보낸문자 저장 연동 확인에 실패했습니다.');
    await Promise.all([loadDashboard(), loadMembers()]);
    if($('genMember')) $('genMember').value=String(id);
    showMemberQuickResult(m, currentCombos, currentAnalysis, true, true);
    toast(`${m.name} ${getMemberPreferredCount(m)}조합 문자 복사 + 보낸문자 저장 완료`);
    if(btn) btn.textContent='저장완료';
    setTimeout(()=>{ if(btn){ btn.textContent=oldText || '복사저장'; btn.disabled=false; } }, 1200);
  }catch(e){
    console.error(e);
    if(btn){ btn.textContent=oldText || '복사저장'; btn.disabled=false; }
    alert('자동 생성/복사/저장 실패: '+(e.message||e));
  }
});
window.detailMember=safe(async function(id){
  let d; try{ d=await api('/api/members/'+id+'/detail'); }catch(e){ d=await api('/api/members/'+id); }
  const m=d.member || d;
  const title=$('memberDetailTitle');
  const sub=$('memberDetailSub');
  const body=$('memberDetailPageBody');
  if(!body) return;
  if(title) title.textContent = `${m.name || '회원'} 상세`;
  if(sub) sub.textContent = `${m.phone || '-'} / ${memberGradeLabel(m.grade)} / ${m.status || '활성'} / ${m.priority || '보통'} / ${getMemberPreferredCount(m)}조합`;
  const summary = d.summary || {};
  const ranks = summary.rank_counts || {};
  const rankText = ['1등','2등','3등','4등','5등','낙첨'].filter(k=>ranks[k]).map(k=>`${k} ${ranks[k]}건`).join(' · ') || '확인 이력 없음';
  body.innerHTML=`
    <div class="detail-profile-grid rc43-grid">
      <div class="detail-card main-profile">
        <h3>${esc(m.name||'')}</h3>
        <p>${esc(m.phone||'-')}</p>
        <div class="chip-row"><span class="chip">${esc(memberGradeLabel(m.grade))}</span><span class="chip">${esc(m.status||'활성')}</span><span class="chip">${esc(m.priority||'보통')}</span><span class="chip">${esc(getMemberPreferredCount(m))}조합</span></div>
        <small>가입 ${esc(m.created_at||'-')} · 최근상담 ${esc(m.last_contact_at||'없음')}</small>
      </div>
      <div class="detail-card"><b>${summary.recommendations||0}</b><span>추천 이력</span></div>
      <div class="detail-card"><b>${summary.sms||0}</b><span>문구 이력</span></div>
      <div class="detail-card"><b>${summary.checks||0}</b><span>당첨 확인</span></div>
      <div class="detail-card"><b>${esc(summary.best_rank||'없음')}</b><span>최고 결과</span></div>
      <div class="detail-card"><b>${formatMoney(summary.total_profit||0)}</b><span>누적 손익</span></div>
    </div>
    <div class="detail-section rc43-summary"><h4>적중 요약</h4><p>${esc(rankText)}</p><p>누적 당첨금 ${formatMoney(summary.total_prize||0)} · 누적 구매금 ${formatMoney(summary.total_cost||0)} · ROI ${esc(summary.roi||0)}%</p></div>
    <div class="detail-section"><h4>회원 메모</h4><textarea id="memberMemoEdit" class="detail-edit-textarea">${esc(m.memo||'')}</textarea><div class="btnrow"><button data-action="member-memo-save" data-member-id="${m.id}" class="primary">메모 저장</button></div></div>
    <div class="detail-section"><h4>상담 이력 추가</h4><div class="note-write"><select id="memberNoteType"><option>상담</option><option>결제</option><option>추천안내</option><option>당첨확인</option><option>기타</option></select><textarea id="memberNoteText" placeholder="상담/안내 내용을 입력하세요."></textarea><button data-action="member-note-save" data-member-id="${m.id}" class="primary">이력 추가</button></div>${renderNoteCards(d.notes)}</div>
    <div class="detail-section"><h4>문구 이력 추가</h4><div class="note-write manual-message-write"><input id="manualSmsRound" type="number" min="1" value="${esc(currentRound||'')}" placeholder="회차"><textarea id="manualSmsBody" placeholder="회원에게 전달한 문구를 직접 입력하세요."></textarea><button data-action="manual-sms-save" data-member-id="${m.id}" class="primary">문구 추가</button></div></div>
    <div class="detail-section"><h4>문구 이력</h4>${renderHistoryCards(d.sms_logs,'sms', m.id)}</div>
    <div class="detail-section rc43-winning"><h4>당첨 이력</h4>${renderWinningHistorySummary(d.winning_checks)}</div>
  `;
  const selectBtn=$('memberDetailSelect');
  if(selectBtn) selectBtn.onclick=()=>selectMember(m.id);
  openPanel('memberDetailPage','회원 상세');
});
window.saveMemberMemo=safe(async function(id){
  await api('/api/members/'+id+'/memo',{method:'PUT',body:{memo:$('memberMemoEdit')?.value||''}});
  toast('회원 메모를 저장했습니다.');
  await detailMember(id);
  await loadMembers();
});
window.saveMemberNote=safe(async function(id){
  await api('/api/members/'+id+'/notes',{method:'POST',body:{note:$('memberNoteText')?.value||'',note_type:$('memberNoteType')?.value||'상담'}});
  toast('상담 이력을 추가했습니다.');
  await detailMember(id);
  await loadMembers();
});
window.saveManualSmsLog=safe(async function(id){
  const m=membersCache.find(x=>String(x.id)===String(id));
  const body=String($('manualSmsBody')?.value||'').trim();
  const roundNo=Number($('manualSmsRound')?.value||currentRound||0);
  if(!body) return alert('추가할 문구를 입력하세요.');
  await api('/api/sms_log',{method:'POST',body:{
    member_id:Number(id),
    member_name:m?.name||'',
    phone:m?.phone||'',
    round_no:roundNo,
    body,
    combos:[],
    send_now:false
  }});
  toast('문구 이력에 추가했습니다.');
  await detailMember(id);
  await loadMembers();
  await loadDashboard();
});
window.deleteSmsLog=safe(async function(smsId, memberId){
  if(!smsId) return alert('삭제할 문구 이력을 찾지 못했습니다.');
  if(!confirm('이 문구 이력을 삭제할까요?')) return;
  await api('/api/sms/'+smsId,{method:'DELETE'});
  toast('문구 이력을 삭제했습니다.');
  if(memberId) await detailMember(memberId);
  await loadMembers();
  await loadDashboard();
});
window.quickMemberStatus=safe(async function(id, status){
  const memberId=Number(id||0);
  const nextStatus=String(status||'').trim();
  if(!memberId) return alert('회원 정보를 찾지 못했습니다.');
  if(!['활성','상담중','휴면','정지','종료','탈퇴'].includes(nextStatus)) return alert('허용되지 않은 회원 상태입니다.');
  const member=(Array.isArray(membersCache)?membersCache:[]).find(x=>Number(x.id)===memberId);
  const current=String(member?.status||'활성');
  if(current===nextStatus){ toast(`이미 ${nextStatus} 상태입니다.`); return; }
  const label=member?.name ? `${member.name} 회원을` : '이 회원을';
  if(!confirm(`${label} ${nextStatus} 상태로 변경할까요?`)) return;
  await api(`/api/members/${memberId}/status`,{method:'POST',body:{status:nextStatus}});
  toast(`회원 상태를 ${nextStatus}(으)로 변경했습니다.`);
  await loadMembers();
  await loadDashboard();
  if($('memberDetail') && String($('memberDetail').dataset?.memberId||'')===String(memberId)) await detailMember(memberId);
});
window.deleteMember=safe(async function(id){
  const memberId=Number(id||0);
  if(!memberId) return alert('회원 정보를 찾지 못했습니다.');
  const member=(Array.isArray(membersCache)?membersCache:[]).find(x=>Number(x.id)===memberId);
  const name=member?.name ? `${member.name} 회원을` : '이 회원을';
  if(!confirm(`${name} 완전히 삭제할까요?\n추천번호와 문자 이력 등 연결 데이터에 영향을 줄 수 있습니다.`)) return;
  await api('/api/members/'+memberId,{method:'DELETE'});
  toast('회원을 삭제했습니다.');
  if(String($('mId')?.value||'')===String(memberId)) $('clearMember')?.click();
  await loadMembers();
  await loadDashboard();
  const detail=$('memberDetail'); if(detail) detail.innerHTML='<p class="hint">회원 목록에서 상세를 눌러주세요.</p>';
});
window.downloadApi=function(path){ const t=token(); location.href=path+(path.includes('?')?'&':'?')+'token='+encodeURIComponent(t); };
window.revokeSession=async function(tail){ if(!confirm('이 세션을 강제 종료할까요?')) return; await api('/api/sessions/'+tail,{method:'DELETE'}); toast('세션을 종료했습니다.'); await loadAdmin(); };
window.cleanupSessions=function(){ alert('세션 정리는 관리자 설정에서 처리됩니다.'); };

function autoGrowTextarea(el){
  if(!el) return;
  try{
    el.style.height = 'auto';
    el.style.height = Math.max(180, Math.min(el.scrollHeight + 8, 720)) + 'px';
  }catch(e){}
}

function refreshSmsPreview(){
  if(!$('smsPreview')) return;
  const member=getSelectedMember();
  const txt = buildTemplateMessage(member, currentRound, currentCombos, currentAnalysis);
  currentSms = txt;
  $('smsPreview').value = txt;
  autoGrowTextarea($('smsPreview'));
}

async function generate(){
  const selectedMemberId=$('genMember')?.value||'';
  applySelectedMemberPreferredCount();
  // 생성 버튼에서 별도 회차 API를 기다리지 않습니다. 초기 로딩 값/통계 캐시를 우선 사용하고,
  // 값이 없을 때만 회차 API를 조회해 체감 지연을 줄입니다.
  let defaultRound = Number(nextGenerationRound || latestStatsCache?.next_round || 0) || undefined;
  if(!defaultRound){
    const next=await setNextDrawRound();
    defaultRound = Number(next?.next_round || next?.latest_round || 0) || undefined;
  }
  const body={
    member_id:selectedMemberId ? Number(selectedMemberId) : null,
    round_no: defaultRound,
    count: Number($('genCount')?.value||10),
    mode:$('genMode')?.value||'balanced',
    fixed:$('fixed')?.value||'',
    excluded:$('exclude')?.value||'',
    exclude:$('exclude')?.value||''
  };
  if(!selectedMemberId){ alert('회원별 당첨확인을 위해 먼저 회원을 선택한 뒤 추천번호를 생성하세요.'); return; }
  setBusy('generate',true,'회원 맞춤 추천번호 분석 중...');
  try{
    const d=await api('/api/generate',{method:'POST',body});
    currentRecId=null; // RC8.18: 생성은 미리보기이며 저장 전에는 추천이력 ID가 없습니다.
    currentCombos=normalizeCombos(d.sets||d.combos||d.numbers||[]);
    if(!currentCombos.length) throw new Error('추천번호 API가 조합을 반환하지 않았습니다.');
    if(currentCombos.length !== Number(body.count)) console.warn('요청 조합수와 생성 조합수가 다릅니다.', body.count, currentCombos.length);
    currentDetails=d.details||[];
    currentRound=d.round||d.round_no||body.round_no||'';
    const fallback = buildFallbackAnalysis(currentCombos, latestStatsCache, body.mode);
    currentAnalysis=normalizeText(d.analysis||d.ai_analysis||d.engine?.summary||fallback).trim() || fallback;
    currentRecommendationAnalysis=normalizeText(d.recommendation_analysis||'').trim() || buildRecommendationAnalysis(currentCombos,currentDetails);
    currentSms=normalizeText(d.sms||'') || buildTemplateMessage(getSelectedMember(), currentRound, currentCombos, currentAnalysis);
    setText('roundLabel', currentRound ? `${currentRound}회차 추천번호 · 심층분석 완료` : '생성 완료');
    renderCombos(currentCombos,currentDetails);
    renderAnalysis(currentAnalysis);
    renderRecommendationAnalysis(currentRecommendationAnalysis);
    renderEngine(d.engine,currentDetails);
    refreshSmsPreview();
    // Refresh statistics after rendering without blocking the generate button.
    loadStats(0).catch(e=>console.warn('생성 후 통계 갱신 실패', e));
    if(selectedMemberId && $('genMember')) $('genMember').value=selectedMemberId;
    refreshSmsPreview();
    if(!quickMemberGenerationMode) scrollToMessagePanel();
    saveWorkspaceState();
    toast('추천번호 미리보기 생성 완료 · 저장 버튼을 눌러야 당첨확인 대상에 등록됩니다.');
  }catch(e){
    console.error('추천번호 생성 실패', e);
    alert('추천번호 생성 실패: '+(e.message||e));
    throw e;
  }finally{ setBusy('generate',false); }
}
async function saveMember(){
  // RC2 Hotfix2: 생성 화면의 '회원 저장' 버튼도 실제 회원 수정/등록 버튼처럼 동작하도록 복구합니다.
  const id=$('mId')?.value;
  const name=($('mName')?.value||'').trim();
  if(!id && !name){
    alert('회원관리에서 회원을 선택하거나 이름을 입력한 뒤 저장하세요.');
    return;
  }
  await addMember();
}
async function addMember(){
  const id=$('mId')?.value;
  calcContractEnd();
  const body={name:$('mName')?.value||'', phone:$('mPhone')?.value||'', grade:memberGradeLabel($('mGrade')?.value||'일반'), status:$('mStatus')?.value||'활성', priority:$('mPriority')?.value||'보통', preferred_count:getMemberPreferredCount({preferred_count:$('mPreferredCount')?.value||10}), created_by:Number($('mCreatedBy')?.value||0)||null, created_at:$('mCreatedAt')?.value||'', contract_months:getContractPeriodMonths(), contract_end_at:$('mContractEndAt')?.value||'', source:$('mSource')?.value||'직접등록', memo:$('mMemo')?.value||''};
  if(!body.name.trim()){ alert('회원 이름을 입력하세요.'); return; }
  let savedResult;
  if(id) savedResult = await api('/api/members/'+id,{method:'PUT',body}); else savedResult = await api('/api/members',{method:'POST',body});
  const savedId = id || savedResult?.id || savedResult?.member?.id;
  await loadMembers();
  if(savedId){
    const saved = membersCache.find(x=>String(x.id)===String(savedId));
    if(saved) selectMember(saved.id);
  }else{
    ['mId','mName','mPhone','mMemo'].forEach(x=>setValue(x,''));
    setValue('mCreatedBy',''); setValue('mCreatedAt',''); setValue('mContractPeriod','12'); setValue('mContractEndAt','');
    setValue('mGrade','일반'); setValue('mStatus','활성'); setValue('mPriority','보통'); setValue('mPreferredCount','10'); setValue('mSource',''); refreshMemberAdminSelect();
  }
  await loadDashboard(); toast('회원 정보가 저장되었습니다.');
}
function autoTemplate(){
  setValue('template', getDefaultTemplate());
  refreshSmsPreview();
  toast('AI 기본 안내문을 적용했습니다.');
}
function resetTemplate(){
  setValue('template', getDefaultTemplate());
  refreshSmsPreview();
  toast('기본문구를 복원했습니다.');
}
function clearTemplate(){
  setValue('template','');
  refreshSmsPreview();
  toast('문구를 초기화했습니다.');
}
async function saveTemplate(){
  const body=normalizeText($('template')?.value||'');
  try{ await api('/api/template',{method:'POST',body:{body}}); }
  catch(e){ await api('/api/settings',{method:'POST',body:{key:'sms_template',value:body}}); }
  saveWorkspaceState();
  toast('문구 템플릿을 저장했습니다.');
}
async function saveSmsLog(){
  try{
    await saveCurrentSmsLog();
    toast('보낸문자를 회원 이력에 저장했습니다.');
    await loadDashboard();
    await loadMembers();
  }catch(e){
    alert(e.message || '문자 이력 저장 중 오류가 발생했습니다.');
  }
}
async function copyAndSaveSmsLog(){
  try{
    const text = ($('smsPreview')?.value || currentSms || '').trim();
    await copyTextToClipboard(text);
    await saveCurrentSmsLog();
    toast('문자 복사 + 보낸문자 저장 완료');
    await loadDashboard();
    await loadMembers();
  }catch(e){
    alert(e.message || '문자 복사/저장 중 오류가 발생했습니다.');
  }
}


