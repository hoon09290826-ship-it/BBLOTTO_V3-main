/* BBLOTTO V3 frontend split: js/50_exports_sms.js | original lines 1774-2130 */
function csvCell(value){
  const s = String(value ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  return '"' + s.replace(/"/g, '""') + '"';
}
function downloadTextFile(filename, text, mime='text/csv;charset=utf-8;'){
  const blob = new Blob(['\ufeff' + text], {type:mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 500);
}
function isRepresentativeRegisteredMember(m){
  if(!m) return false;
  if(Number(m.registered_by_super_admin || 0) === 1) return true;
  const txt = [m.registered_by_role, m.registered_by_name, m.registered_by_username].map(v=>String(v||'').replace(/\s+/g,'').toLowerCase()).join(' ');
  return txt.includes('대표관리자') || txt.includes('최고관리자') || txt.includes('super') || txt.includes('owner') || String(m.registered_by_username||'').toLowerCase()==='admin';
}
function getSmsScopeLabel(scope){
  if(scope === 'selected') return '선택회원';
  if(scope === 'representative') return '대표관리자 등록회원';
  if(scope === 'general') return '일반관리자 등록회원';
  return '전체회원';
}
function getSmsScopeValue(){
  return $('smsCsvScope')?.value || 'all';
}
function smsExportMembers(scope){
  const valid = (m)=> String(m.status || '활성') !== '탈퇴' && normalizePhoneText(m.phone || '');
  if(scope === 'selected'){
    const m = getSelectedMember();
    return (m && valid(m)) ? [m] : [];
  }
  let list = (membersCache || []).filter(valid);
  if(scope === 'representative') list = list.filter(isRepresentativeRegisteredMember);
  if(scope === 'general') list = list.filter(m => !isRepresentativeRegisteredMember(m));
  return list;
}
function refreshSmsScopeInfo(){
  const all = smsExportMembers('all').length;
  const rep = smsExportMembers('representative').length;
  const gen = smsExportMembers('general').length;
  const selected = smsExportMembers('selected').length;
  const info = $('smsScopeInfo');
  if(info) info.textContent = `전체 ${all}명 · 대표관리자 등록 ${rep}명 · 일반관리자 등록 ${gen}명 · 현재 선택 ${selected}명`;
}
function buildSmsExportRows(scope='all'){
  const members = smsExportMembers(scope);
  if(!members.length) return [];
  const combos = normalizeCombos(currentCombos);
  const analysis = normalizeText(currentAnalysis || '').trim();
  const round = currentRound || '';
  return members.map(m=>{
    const memberCombos = (typeof rc71MemberCombos === 'function') ? rc71MemberCombos(m, 0, combos.length || 10) : combos;
    const memberAnalysis = (typeof rc71MemberAnalysis === 'function') ? rc71MemberAnalysis(m, memberCombos, 0) : analysis;
    const message = buildBulkSmsMessage(m, round, memberCombos, memberAnalysis);
    const seg = (typeof buildSmsSegmentsForMember === 'function') ? buildSmsSegmentsForMember(m, round, memberCombos, memberAnalysis) : {seg1:'',seg2:'',seg3:'',seg4:''};
    return {
      name: m.name || '',
      phone: String(m.phone || '').replace(/[^0-9]/g, ''),
      message: normalizeSmsLineBreaks(message),
      round,
      numbers: formatComboLines(memberCombos),
      seg1: normalizeSmsLineBreaks(seg.seg1 || ''),
      seg2: normalizeSmsLineBreaks(seg.seg2 || ''),
      seg3: normalizeSmsLineBreaks(seg.seg3 || ''),
      seg4: normalizeSmsLineBreaks(seg.seg4 || ''),
      grade: m.grade || '',
      status: m.status || '활성'
    };
  });
}

function getBulkSmsTemplate(){
  const custom = normalizeText($('bulkSmsTemplate')?.value || '').trim();
  return custom || normalizeText($('template')?.value || '').trim() || normalizeText(currentSms || '').trim();
}


// ===================== RC7-8 SMSGANDA SEGMENT CENTER =====================
const BB_SMS_SEG_DEFAULTS = {
  1: '안녕하세요 {회원명}님, BBLOTTO입니다.\n\n{회차}회차 추천번호 및 이번회차 분석입니다.',
  2: '[이번회차 핵심 분석]\n\n{분석}',
  3: '[추천번호]\n\n{추천번호}',
  4: '좋은 결과 있으시길 바랍니다.'
};
function getSmsSegment(n){
  const el = $('smsSeg'+n);
  const saved = localStorage.getItem('bb_sms_seg_'+n);
  return normalizeText(el?.value || saved || BB_SMS_SEG_DEFAULTS[n] || '');
}
function setSmsSegment(n, value){
  const v = normalizeText(value || '');
  const el = $('smsSeg'+n);
  if(el) el.value = v;
  localStorage.setItem('bb_sms_seg_'+n, v);
}
function initSmsSegments(){
  [1,2,3,4].forEach(n=>{
    const v = localStorage.getItem('bb_sms_seg_'+n) || BB_SMS_SEG_DEFAULTS[n];
    if($('smsSeg'+n)) $('smsSeg'+n).value = v;
    $('smsSeg'+n)?.addEventListener('input',()=>{ saveSmsSegments(false); refreshSmsSegmentPreview(); });
  });
  refreshSmsSegmentPreview();
}
function saveSmsSegments(show=true){
  [1,2,3,4].forEach(n=>{ if($('smsSeg'+n)) localStorage.setItem('bb_sms_seg_'+n, normalizeText($('smsSeg'+n).value || '')); });
  if(show){ setText('smsExportInfo','문자간다 [*1*]~[*4*] 문구를 저장했습니다.'); toast('문자간다 문구 저장 완료'); }
}
function resetSmsSegment(n){
  setSmsSegment(n, BB_SMS_SEG_DEFAULTS[n]);
  refreshSmsSegmentPreview();
  setText('smsExportInfo', `[*${n}*] 문구를 기본값으로 복원했습니다.`);
}
function resetAllSmsSegments(){
  [1,2,3,4].forEach(n=>setSmsSegment(n, BB_SMS_SEG_DEFAULTS[n]));
  refreshSmsSegmentPreview();
  setText('smsExportInfo','문자간다 문구 전체를 기본값으로 복원했습니다.');
}
function buildSmsSegmentsForMember(member, round, combos, analysis){
  return {
    seg1: applyTemplate(getSmsSegment(1), member, round, combos, analysis),
    seg2: applyTemplate(getSmsSegment(2), member, round, combos, analysis),
    seg3: applyTemplate(getSmsSegment(3), member, round, combos, analysis),
    seg4: applyTemplate(getSmsSegment(4), member, round, combos, analysis)
  };
}
function buildSmsSegmentFullMessage(member, round, combos, analysis){
  const seg = buildSmsSegmentsForMember(member, round, combos, analysis);
  return [seg.seg1, seg.seg2, seg.seg3, seg.seg4].map(v=>normalizeText(v).trim()).filter(Boolean).join('\n\n');
}
function refreshSmsSegmentPreview(){
  const m = getSelectedMember() || (membersCache && membersCache[0]) || {name:'회원'};
  const combos = (typeof rc71MemberCombos === 'function') ? rc71MemberCombos(m, 0, normalizeCombos(currentCombos).length || 10) : normalizeCombos(currentCombos);
  const analysis = (typeof rc71MemberAnalysis === 'function') ? rc71MemberAnalysis(m, combos, 0) : (currentAnalysis || '분석 내용이 여기에 표시됩니다.');
  const txt = buildSmsSegmentFullMessage(m, currentRound || '', combos, analysis);
  if($('smsSegmentPreview')){ $('smsSegmentPreview').value = txt; autoGrowTextarea($('smsSegmentPreview')); }
  return txt;
}
window.bbSaveSmsSegments = ()=>saveSmsSegments(true);
window.bbResetSmsSegment = resetSmsSegment;
window.bbResetAllSmsSegments = resetAllSmsSegments;
window.bbRefreshSmsSegmentPreview = refreshSmsSegmentPreview;
// ===================== /RC7-8 SMSGANDA SEGMENT CENTER =====================

// RC6-5: 독립 템플릿 치환 함수. bulkSmsTemplate 사용 시 필수입니다.
function applyTemplate(template, member, round, combos, analysis){
  const tpl = normalizeText(template || '').trim() || getDefaultTemplate();
  const name = member?.name || member?.member_name || '회원';
  const today = new Date().toLocaleDateString('ko-KR');
  const analysisText = normalizeText(analysis || currentAnalysis).trim() || '분석 결과 없음';
  const numbers = formatComboLines(combos || currentCombos);
  return normalizeSmsLineBreaks(tpl
    .replaceAll('{회원명}', name)
    .replaceAll('{회원이름}', name)
    .replaceAll('{이름}', name)
    .replaceAll('{회차}', String(round || currentRound || '-'))
    .replaceAll('{추천번호}', numbers)
    .replaceAll('{번호}', numbers)
    .replaceAll('{분석}', analysisText)
    .replaceAll('{발송일}', today)
    .replaceAll('{AI점수}', String(getBestAiScore())));
}

function buildBulkSmsMessage(member, round, combos, analysis){
  const tpl = getBulkSmsTemplate();
  if(tpl){
    return applyTemplate(tpl, member || {}, round || currentRound || '', combos || normalizeCombos(currentCombos), analysis || currentAnalysis || '');
  }
  return buildTemplateMessage(member, round, combos, analysis);
}
function applyBulkTemplateToPreview(){
  const m = getSelectedMember() || (membersCache && membersCache[0]) || {name:'회원'};
  const txt = buildBulkSmsMessage(m, currentRound || '', normalizeCombos(currentCombos), currentAnalysis || '');
  if($('smsPreview')) $('smsPreview').value = txt;
  setText('smsExportInfo', '수정한 전체회원 문구를 미리보기에 적용했습니다. CSV 생성 시 회원별 이름/번호가 자동 치환됩니다.');
  toast('전체회원 발송 문구를 적용했습니다.');
}

function downloadSmsCsv(scope='all'){
  if(!normalizeCombos(currentCombos).length && !confirm('추천번호 생성 결과가 없습니다. 그래도 CSV를 만들까요?')) return;
  const rows = buildSmsExportRows(scope);
  if(!rows.length){ alert(scope === 'selected' ? '선택된 회원이 없거나 연락처가 없습니다.' : '발송용 회원 연락처가 없습니다.'); return; }
  const header = ['이름','전화번호','문자내용','회차','추천번호','등급','상태'];
  const csv = [header.map(csvCell).join(',')].concat(rows.map(r=>[r.name,r.phone,r.message,r.round,r.numbers,r.grade,r.status].map(csvCell).join(','))).join('\n');
  const roundPart = currentRound ? `${currentRound}회차_` : '';
  downloadTextFile(`BBLOTTO_${roundPart}문자간다_업로드_${getSmsScopeLabel(scope)}.csv`, csv);
  setText('smsExportInfo', `${getSmsScopeLabel(scope)} ${rows.length}명 발송용 CSV 생성 완료 · 문자간다 대량등록에 업로드하세요.`);
  toast(`문자 발송용 CSV ${rows.length}건 생성 완료`);
}


// RC7-2: 문자간다 전용 XLS/TXT 생성 (A열=이름, B열=전화번호)
function escapeHtml(value){
  return String(value ?? '')
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}
async function downloadSmsGandaXls(scope='all'){
  const members = smsExportMembers(scope);
  if(!members.length){ alert(scope === 'selected' ? '선택된 회원이 없거나 연락처가 없습니다.' : '문자간다 업로드용 회원 연락처가 없습니다.'); return; }
  const rows = buildSmsExportRows(scope).map(r=>({
    name: String(r.name || '회원').trim(),
    phone: String(r.phone || '').replace(/[^0-9]/g, ''),
    // RC7-22: 문자간다 엑셀 치환값 내부 줄바꿈 제거 문제 때문에
    // XLS는 이름/전화번호 주소록 전용으로만 사용합니다. 본문은 '문자내용 복사'로 입력창에 붙여넣습니다.
    seg1: '',
    seg2: '',
    seg3: '',
    seg4: ''
  })).filter(r=>r.name && r.phone);
  if(!rows.length){ alert('이름과 전화번호가 있는 회원이 없습니다.'); return; }
  setText('smsExportInfo', `${getSmsScopeLabel(scope)} ${rows.length}명 문자간다 실제 XLS 생성 중입니다...`);
  const r = await fetch('/api/export/smsganda_xls', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({rows, scope, round_no: currentRound || ''})
  });
  if(r.status === 401){ localStorage.removeItem('bb_v34_token'); location.href='/'; return; }
  if(!r.ok){
    let msg = '문자간다 XLS 생성 실패';
    try{
      const j = await r.json();
      msg = j.detail || j.message || j.error?.message || j.error?.type || msg;
      if(typeof msg !== 'string') msg = JSON.stringify(msg);
    }catch(e){
      try{ msg = await r.text(); }catch(_){}
    }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const roundPart = currentRound ? `${currentRound}회차_` : '';
  const filename = `BBLOTTO_${roundPart}문자간다_주소록_${getSmsScopeLabel(scope)}.xls`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
  setText('smsExportInfo', `${getSmsScopeLabel(scope)} ${rows.length}명 문자간다 주소록 XLS 생성 완료 · 먼저 문자내용 복사를 눌러 입력창에 붙여넣으세요.`);
  toast(`문자간다 실제 XLS ${rows.length}명 생성 완료`);
}
async function downloadSmsGandaTxt(scope='all'){
  const members = smsExportMembers(scope);
  if(!members.length){ alert(scope === 'selected' ? '선택된 회원이 없거나 연락처가 없습니다.' : '문자간다 업로드용 회원 연락처가 없습니다.'); return; }
  const rows = members.map(m=>({
    name: String(m.name || m.member_name || '회원').trim(),
    phone: String(m.phone || '').replace(/[^0-9]/g, '')
  })).filter(r=>r.name && r.phone);
  if(!rows.length){ alert('이름과 전화번호가 있는 회원이 없습니다.'); return; }
  setText('smsExportInfo', `${getSmsScopeLabel(scope)} ${rows.length}명 문자간다 TXT 생성 중입니다...`);
  const r = await fetch('/api/export/smsganda_txt', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({rows, scope, round_no: currentRound || ''})
  });
  if(r.status === 401){ localStorage.removeItem('bb_v34_token'); location.href='/'; return; }
  if(!r.ok){
    let msg = '문자간다 TXT 생성 실패';
    try{
      const j = await r.json();
      msg = j.detail || j.message || j.error?.message || j.error?.type || msg;
      if(typeof msg !== 'string') msg = JSON.stringify(msg);
    }catch(e){
      try{ msg = await r.text(); }catch(_){}
    }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const roundPart = currentRound ? `${currentRound}회차_` : '';
  const filename = `BBLOTTO_${roundPart}문자간다_주소록_${getSmsScopeLabel(scope)}.txt`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
  setText('smsExportInfo', `${getSmsScopeLabel(scope)} ${rows.length}명 문자간다 TXT 생성 완료 · ANSI/CP949, 이름,전화번호 형식`);
  toast(`문자간다 TXT ${rows.length}명 생성 완료`);
}
function buildSmsGandaPasteTemplate(){
  // RC7-22: 문자간다는 엑셀 치환값([*1*]~[*4*]) 내부 줄바꿈을 제거합니다.
  // 그래서 줄바꿈이 필요한 본문은 문자간다 입력창에 직접 붙여넣는 공통 템플릿으로 생성합니다.
  // 이름만 문자간다 기본 치환값 [*이름*]을 사용하고, 추천번호/분석은 입력창 본문에 직접 넣습니다.
  const round = String(currentRound || '-');
  const combos = normalizeCombos(currentCombos);
  const numbers = formatComboLines(combos);
  const analysis = normalizeSmsLineBreaks(currentAnalysis || '').trim() || `${round}회차는 균형형 기준으로 최근 흐름과 누적 데이터를 함께 비교했습니다.
끝수 반복과 연속수 과다 사용을 제한해 조합별 형태가 겹치지 않게 했습니다.
`;
  return normalizeSmsLineBreaks([
    '안녕하세요 [*이름*]님, BBLOTTO입니다.',
    `${round}회차 추천번호 및 이번회차 분석입니다.`,
    '',
    '[이번회차 핵심 분석]',
    analysis,
    '',
    '[추천번호]',
    numbers,
    '',
    '',
    '좋은 결과 있으시길 바랍니다.'
  ].join('\n'));
}
function copySmsGandaMessage(){
  try{
    const text = buildSmsGandaPasteTemplate();
    if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(text); }
    else { const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
    setText('smsExportInfo', '문자간다 입력창에는 방금 복사한 본문을 그대로 붙여넣고, XLS는 주소록용으로만 업로드하세요. [*1*]~[*4*]는 사용하지 않습니다.');
    toast('문자간다 붙여넣기용 본문 복사 완료');
  }catch(e){ console.error(e); alert('문자내용 복사 중 오류: '+(e.message||e)); }
}
async function bbDownloadSmsGandaXls(){ try{ await downloadSmsGandaXls(getSmsScopeValue()); }catch(e){ console.error(e); alert('문자간다 XLS 생성 중 오류: '+(e.message||e)); } }
async function bbDownloadSmsGandaXlsAll(){ try{ await downloadSmsGandaXls('all'); }catch(e){ console.error(e); alert('문자간다 XLS 생성 중 오류: '+(e.message||e)); } }
async function bbDownloadSmsGandaXlsSelected(){ try{ await downloadSmsGandaXls('selected'); }catch(e){ console.error(e); alert('문자간다 XLS 생성 중 오류: '+(e.message||e)); } }
async function bbDownloadSmsGandaTxt(){ try{ await downloadSmsGandaTxt(getSmsScopeValue()); }catch(e){ console.error(e); alert('문자간다 TXT 생성 중 오류: '+(e.message||e)); } }
window.bbDownloadSmsGandaXls = bbDownloadSmsGandaXls;
window.bbDownloadSmsGandaXlsAll = bbDownloadSmsGandaXlsAll;
window.bbDownloadSmsGandaXlsSelected = bbDownloadSmsGandaXlsSelected;
window.bbDownloadSmsGandaTxt = bbDownloadSmsGandaTxt;
window.bbCopySmsGandaMessage = copySmsGandaMessage;

function copyBulkSmsText(){
  const rows = buildSmsExportRows('all');
  if(!rows.length){ alert('복사할 회원 연락처가 없습니다.'); return; }
  const text = rows.map(r=>`${r.phone}\t${r.message}`).join('\n\n');
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(text); } else { const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  setText('smsExportInfo', `${rows.length}명 문자내용을 클립보드에 복사했습니다.`);
  toast('전체 회원 문자 내용을 복사했습니다.');
}


// RC6-5: 문자간다 CSV 버튼/템플릿 함수 HOTFIX
function bbDownloadSmsCsvAll(){ try{ downloadSmsCsv('all'); }catch(e){ console.error(e); alert('CSV 생성 중 오류: '+(e.message||e)); } }
function bbDownloadSmsCsvSelected(){ try{ downloadSmsCsv('selected'); }catch(e){ console.error(e); alert('CSV 생성 중 오류: '+(e.message||e)); } }
function bbDownloadSmsCsvScoped(){ try{ downloadSmsCsv(getSmsScopeValue()); }catch(e){ console.error(e); alert('CSV 생성 중 오류: '+(e.message||e)); } }
function bbCopySmsBulk(){ try{ copyBulkSmsText(); }catch(e){ console.error(e); alert('문자 복사 중 오류: '+(e.message||e)); } }
function bbApplyBulkTemplate(){ try{ applyBulkTemplateToPreview(); }catch(e){ console.error(e); alert('문구 적용 중 오류: '+(e.message||e)); } }
window.bbDownloadSmsCsvAll = bbDownloadSmsCsvAll;
window.bbDownloadSmsCsvSelected = bbDownloadSmsCsvSelected;
window.bbDownloadSmsCsvScoped = bbDownloadSmsCsvScoped;
window.bbCopySmsBulk = bbCopySmsBulk;
window.bbApplyBulkTemplate = bbApplyBulkTemplate;


let lastSearchedDraw = null;
