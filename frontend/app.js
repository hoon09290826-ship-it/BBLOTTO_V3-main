/* BBLOTTO V3 STABLE CORE SAME NUMBER SAVE - single event owner: app.js */
(function(){
  'use strict';
  function prepareUi(){
    document.querySelectorAll('button').forEach(function(button){
      if(!button.hasAttribute('type')) button.type='button';
    });
    var modal=document.getElementById('adminCreateModal');
    if(modal && !modal.classList.contains('is-open')){
      modal.style.display='none';
      modal.setAttribute('aria-hidden','true');
    }
    document.documentElement.dataset.bblottoUi='same-number-save-1';
  }
  window.addEventListener('error',function(event){
    console.error('[BBLOTTO STABLE CORE]',event.error||event.message);
  });
  window.addEventListener('unhandledrejection',function(event){
    console.error('[BBLOTTO STABLE CORE PROMISE]',event.reason);
  });
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',prepareUi,{once:true});
  else prepareUi();
  window.BBLOTTO_STABLE_CORE='same-number-save-1';
})();

/* BBLOTTO PRO V40 PHASE2 FRONTEND CORE
   목표: 버튼 안정화, 추천결과 상세표시, 회원 안내문구 자동 생성, 분석 표시 강화 */
const $ = (id) => document.getElementById(id);
const token = () => localStorage.getItem('bb_v34_token') || '';
const headers = () => ({'Content-Type':'application/json','Authorization':'Bearer '+token(),'X-Token': token()});

let currentCombos = [];
let currentDetails = [];
let currentSms = '';
let currentAnalysis = '';
let currentRecommendationAnalysis = '';
let currentRound = '';
let currentRecId = null;
let membersCache = [];
let memberFilteredCache = [];
let memberPage = 1;
let memberPageSize = 10;
let winCheckCache = [];
let winCheckSummaryCache = null;
let winCheckMetaCache = {};
let winCheckPage = 1;
let winCheckPageSize = 10;
let statsRecentDrawsCache = [];
let statsPage = 1;
let statsPageSize = 10;
let drawRowsCache = [];
let drawPage = 1;
let drawPageSize = 10;
let latestStatsCache = null;
let currentAdmin = null;
let quickMemberGenerationMode = false;
const memberQuickResults = new Map(); // 회원별 마지막 생성 결과: 복사저장은 이 결과만 사용
let adminCache = [];
let sessionWatchTimer = null;
let sessionWarned = false;
const WORKSPACE_KEY = 'bb_v50_workspace_state';

function saveWorkspaceState(){
  try{
    const state = {
      currentCombos, currentDetails, currentSms, currentAnalysis, currentRecommendationAnalysis, currentRound, currentRecId,
      selectedMemberId: $('genMember')?.value || '',
      template: $('template')?.value || '',
      bulkSmsTemplate: $('bulkSmsTemplate')?.value || '',
      savedAt: new Date().toISOString()
    };
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify(state));
  }catch(e){ console.warn('작업 상태 저장 실패', e); }
}
function restoreWorkspaceState(){
  try{
    const raw = localStorage.getItem(WORKSPACE_KEY);
    if(!raw) return false;
    const st = JSON.parse(raw);
    if(!st || !Array.isArray(st.currentCombos) || st.currentCombos.length===0) return false;
    currentCombos = normalizeCombos(st.currentCombos);
    currentDetails = Array.isArray(st.currentDetails) ? st.currentDetails : [];
    currentSms = normalizeText(st.currentSms || '');
    currentAnalysis = normalizeText(st.currentAnalysis || '');
    currentRound = st.currentRound || '';
    currentRecId = st.currentRecId || null;
    if(st.selectedMemberId && $('genMember')) $('genMember').value = st.selectedMemberId;
    if(!($('template')?.value) && st.template) setValue('template', normalizeText(st.template));
    if(!($('bulkSmsTemplate')?.value) && st.bulkSmsTemplate) setValue('bulkSmsTemplate', normalizeText(st.bulkSmsTemplate));
    if(currentRound) setText('roundLabel', `${currentRound}회차 추천번호 · 저장된 작업 복원`);
    renderCombos(currentCombos, currentDetails);
    renderAnalysis(currentAnalysis);
    refreshSmsPreview();
    return true;
  }catch(e){ console.warn('작업 상태 복원 실패', e); return false; }
}
async function restoreLatestRecommendationFromServer(){
  try{
    const list = await api('/api/recommendations');
    if(!Array.isArray(list) || !list.length) return false;
    const latest = list[0];
    const d = await api('/api/recommendations/' + latest.id);
    currentRecId = d.id || latest.id || null;
    currentCombos = normalizeCombos(d.numbers || []);
    currentDetails = d.details || [];
    currentRound = d.round_no || latest.round_no || '';
    currentAnalysis = normalizeText(d.analysis || latest.analysis || '');
    currentSms = normalizeText(d.sms || latest.sms || '');
    if(d.member_id && $('genMember')) $('genMember').value = String(d.member_id);
    if(currentRound) setText('roundLabel', `${currentRound}회차 추천번호 · 마지막 이력 복원`);
    renderCombos(currentCombos, currentDetails);
    renderAnalysis(currentAnalysis);
    refreshSmsPreview();
    saveWorkspaceState();
    return true;
  }catch(e){ console.warn('마지막 추천이력 복원 실패', e); return false; }
}


function parseServerTime(s){
  if(!s) return null;
  const t = String(s).replace(' ', 'T');
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d;
}
function forceLogout(msg){
  localStorage.removeItem('bb_v34_token');
  alert(msg || '로그인이 만료되었습니다. 다시 로그인해주세요.');
  location.href='/';
}
function startSessionWatcher(admin){
  if(sessionWatchTimer) clearInterval(sessionWatchTimer);
  sessionWarned = false;
  let exp = null;
  // PHASE25: Render 서버 시간대(UTC)와 브라우저 시간대(KST) 차이로 즉시 로그아웃되는 문제 방지
  if(admin?.expires_in_seconds){
    exp = new Date(Date.now() + Number(admin.expires_in_seconds) * 1000);
  } else {
    exp = parseServerTime(admin?.expires_at);
  }
  if(!exp) return;
  sessionWatchTimer = setInterval(()=>{
    const leftMs = exp.getTime() - Date.now();
    if(leftMs <= 0){ clearInterval(sessionWatchTimer); forceLogout('자동 로그아웃 시간이 지나 로그아웃됩니다.'); return; }
    const leftMin = Math.ceil(leftMs / 60000);
    const userBox = document.querySelector('.user');
    if(userBox && leftMin <= 30) userBox.title = `자동 로그아웃까지 약 ${leftMin}분`;
    if(!sessionWarned && leftMin <= 5){ sessionWarned = true; toast(`자동 로그아웃까지 약 ${leftMin}분 남았습니다.`); }
  }, 30000);
}

async function api(path, opts={}){
  const method = opts.method || 'GET';
  const init = {method, headers: headers()};
  if(opts.body !== undefined) init.body = JSON.stringify(opts.body);
  const r = await fetch(path, init);
  if(r.status === 401){
    localStorage.removeItem('bb_v34_token');
    location.href='/';
    throw new Error('로그인이 필요합니다.');
  }
  const text = await r.text();
  let data;
  try{ data = text ? JSON.parse(text) : {}; }catch(e){ data = {raw:text}; }
  if(!r.ok){
    const err = data.error || data.detail || data.message || text || '요청 실패';
    const msg = (err && typeof err === 'object') ? (err.message || err.detail || JSON.stringify(err)) : String(err);
    throw new Error((path || 'API') + ' : ' + msg);
  }
  return data;
}

function toast(msg){
  const el = $('toast');
  if(el){
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(()=>el.classList.remove('show'), 1800);
  }else{
    console.log(msg);
  }
}
function setText(id, v){ const el=$(id); if(el) el.textContent = v ?? ''; }
function setHTML(id, v){ const el=$(id); if(el) el.innerHTML = v ?? ''; }
function setValue(id, v){ const el=$(id); if(el) el.value = v ?? ''; }
function safe(fn){
  return async (...args)=>{
    try{return await fn(...args)}
    catch(e){ console.error(e); alert(e.message || e); }
  };
}
function setBusy(btnId, busy, text){
  const btn=$(btnId); if(!btn) return;
  if(busy){ btn.dataset.oldText = btn.textContent; btn.textContent = text || '처리 중...'; btn.disabled = true; }
  else{ btn.textContent = btn.dataset.oldText || btn.textContent; btn.disabled = false; }
}
function esc(s){ return String(s ?? '').replace(/[&<>"]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }
function memberGradeLabel(v){
  v=String(v||'일반').trim();
  const map={'VIP':'1등','다이아':'1등','다이아몬드':'1등','프리미엄':'2등','1등관리':'1등','2등관리':'2등','일반관리':'일반'};
  return map[v] || (['1등','2등','일반'].includes(v)?v:'일반');
}
function numberListText(arr){ return (arr||[]).map(x=>Array.isArray(x)?x.join(', '):String(x)).join('\n'); }
function ballClass(n){ n=Number(n); if(n<=10)return'b1'; if(n<=20)return'b2'; if(n<=30)return'b3'; if(n<=40)return'b4'; return'b5'; }
function gradeLabel(d){
  const g = memberGradeLabel(d?.member_grade || d?.grade || '일반');
  return g === '1등' ? '🥇 1등' : (g === '2등' ? '🥈 2등' : '⭐ 일반');
}
function engineLabel(d){
  const g = memberGradeLabel(d?.member_grade || d?.grade || '일반');
  return d?.engine_label || (g === '1등' ? 'AI MASTER' : (g === '2등' ? 'AI PREMIUM' : 'AI BASIC'));
}
function starLabel(d){ const s=Number(d?.score ?? d?.vip_score ?? d?.ai_score ?? 0); return s>=97?'★★★★★':(s>=94?'★★★★☆':'★★★★'); }
function top3FromDetails(sets, details=[]){ return (sets||[]).map((nums,i)=>({nums, detail:details[i]||{}, idx:i+1})).sort((a,b)=>Number(b.detail.score||0)-Number(a.detail.score||0)).slice(0,3); }
function parseNumsInput(v){ return String(v||'').match(/\d+/g)?.map(Number).filter(n=>n>=1&&n<=45) || []; }
function getSelectedMember(){ const id=String($('genMember')?.value||''); return membersCache.find(m=>String(m.id)===id) || null; }
function getMemberPreferredCount(m){
  const n = Number(m?.preferred_count || m?.combo_count || m?.recommend_count || 10);
  return Math.max(1, Math.min(Number.isFinite(n) ? n : 10, 100));
}

function toDateInputValue(value){
  const s=String(value||'').trim();
  const m=s.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '';
}
function addMonthsDate(value, months){
  const base=toDateInputValue(value) || new Date().toISOString().slice(0,10);
  const d=new Date(base+'T00:00:00');
  if(Number.isNaN(d.getTime())) return '';
  const day=d.getDate();
  d.setMonth(d.getMonth()+Number(months||12));
  // 말일 보정: 1/31 + 1개월 같은 경우 다음달로 밀리면 해당 월 마지막 날로 맞춥니다.
  if(d.getDate() !== day) d.setDate(0);
  return d.toISOString().slice(0,10);
}
function oneYearAfter(value){ return addMonthsDate(value, 12); }
function getContractPeriodMonths(){
  const v=Number($('mContractPeriod')?.value || 12);
  return [6,12,24,36].includes(v) ? v : 12;
}
function calcContractEnd(){
  const start=toDateInputValue($('mCreatedAt')?.value) || new Date().toISOString().slice(0,10);
  setValue('mContractEndAt', addMonthsDate(start, getContractPeriodMonths()));
}
function guessContractPeriodMonths(start, end){
  const a=toDateInputValue(start), b=toDateInputValue(end);
  if(!a || !b) return 12;
  const da=new Date(a+'T00:00:00'), db=new Date(b+'T00:00:00');
  if(Number.isNaN(da.getTime()) || Number.isNaN(db.getTime())) return 12;
  const days=Math.round((db-da)/86400000);
  if(days <= 220) return 6;
  if(days <= 550) return 12;
  if(days <= 920) return 24;
  return 36;
}
function isRepresentativeAdmin(){
  if(!currentAdmin) return false;
  const superFlag = currentAdmin.is_super_admin === true || currentAdmin.is_super_admin === 1 || String(currentAdmin.is_super_admin).toLowerCase() === 'true';
  if(superFlag) return true;
  const txt=[currentAdmin.role,currentAdmin.name,currentAdmin.username]
    .map(v=>String(v||'').replace(/\s+/g,'').toLowerCase()).join(' ');
  return txt.includes('대표관리자') || txt.includes('대표') || txt.includes('최고관리자') || txt.includes('최고') || txt.includes('전체권한') || txt.includes('super') || txt.includes('owner') || String(currentAdmin.username||'').toLowerCase()==='admin';
}
function refreshMemberAdminSelect(selectedValue){
  const sel=$('mCreatedBy'); if(!sel) return;
  const current=String((selectedValue ?? sel.value) || '');
  let admins=Array.isArray(adminCache)?adminCache.slice():[];
  if(currentAdmin && !admins.some(a=>String(a.id)===String(currentAdmin.id))){
    admins.unshift(currentAdmin);
  }
  sel.innerHTML='<option value="">현재 로그인 관리자</option>'+admins.map(a=>`<option value="${a.id}">${esc(a.name||a.username||'관리자')} (${esc(a.username||'')})</option>`).join('');
  if(current && Array.from(sel.options).some(o=>String(o.value)===current)) sel.value=current;
  // 등록 관리자 변경만 대표관리자 권한입니다.
  // 등록일/계약기간은 모든 관리자가 수정할 수 있도록 잠그지 않습니다.
  const editable=isRepresentativeAdmin();
  sel.disabled=!editable;
  const created=$('mCreatedAt'); if(created) created.disabled=false;
  const period=$('mContractPeriod'); if(period) period.disabled=false;
  const end=$('mContractEndAt'); if(end){ end.disabled=false; end.readOnly=true; }
}

function setGenCountValue(count){
  const sel=$('genCount'); if(!sel) return;
  const v=String(getMemberPreferredCount({preferred_count:count}));
  if(!Array.from(sel.options).some(o=>String(o.value)===v)){
    const opt=document.createElement('option'); opt.value=v; opt.textContent=v; sel.appendChild(opt);
  }
  sel.value=v;
}
function applySelectedMemberPreferredCount(){
  const m=getSelectedMember();
  if(m) setGenCountValue(getMemberPreferredCount(m));
}

function normalizeText(value){
  // V50 13차: textarea/미리보기에는 JSON 객체가 아니라 실제 문구만 표시한다.
  if(value === null || value === undefined) return '';
  if(typeof value === 'string') {
    let text = value;
    // DB에 {"value":"..."} 또는 {"body":"..."} 형태로 잘못 저장된 경우 자동 복구
    for(let i=0;i<3;i++){
      const t = String(text).trim();
      if(!((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']')))) break;
      try{
        const parsed = JSON.parse(t);
        const extracted = extractTextField(parsed);
        if(!extracted || extracted === text) break;
        text = extracted;
      }catch(e){ break; }
    }
    return String(text).replace(/\\n/g,'\n').replace(/\\t/g,'\t');
  }
  if(Array.isArray(value)) return value.map(normalizeText).filter(Boolean).join('\n');
  if(typeof value === 'object'){
    const direct = extractTextField(value);
    if(direct) return normalizeText(direct);
    const parts = [];
    const keys = ['summary','message','text','body','value','analysis','overview','comment','safe_message','member_message','copy_text'];
    keys.forEach(k=>{ if(value[k]) parts.push(normalizeText(value[k])); });
    ['reasons','reason','tags','points','items','warnings','notes','lines'].forEach(k=>{
      if(Array.isArray(value[k]) && value[k].length) parts.push(value[k].map(x=>'• '+normalizeText(x)).join('\n'));
    });
    if(value.score || value.ai_score || value.avg_score) parts.push(`AI SCORE ${value.score || value.ai_score || value.avg_score}`);
    return parts.filter(Boolean).join('\n');
  }
  return String(value);
}
function extractTextField(obj){
  if(!obj || typeof obj !== 'object') return '';
  const keys = ['body','value','text','message','sms_template','template','content'];
  for(const k of keys){
    if(obj[k] !== undefined && obj[k] !== null){
      // /api/settings 응답처럼 sms_template: {value: '...'} 형태도 처리
      if(typeof obj[k] === 'object') return extractTextField(obj[k]);
      return String(obj[k]);
    }
  }
  return '';
}
function normalizeCombo(combo){
  if(Array.isArray(combo)) return combo.map(Number).filter(n=>Number.isFinite(n));
  if(combo && typeof combo === 'object'){
    const arr = combo.numbers || combo.combo || combo.set || combo.nums;
    if(Array.isArray(arr)) return arr.map(Number).filter(n=>Number.isFinite(n));
  }
  return parseNumsInput(String(combo));
}
function normalizeCombos(combos){
  // RC7-10: 서버/저장소/엑셀 복원값이 문자열(JSON, 줄글, 쉼표 나열)이어도
  // 반드시 6개 번호 단위의 조합 배열로 정규화한다.
  if(!combos) return [];
  if(typeof combos === 'string'){
    const raw = normalizeText(combos).trim();
    if(!raw) return [];
    try{
      const parsed = JSON.parse(raw);
      if(parsed !== raw) return normalizeCombos(parsed);
    }catch(e){}
    const lines = raw.split(/\n+/).map(x=>x.trim()).filter(Boolean);
    if(lines.length > 1){
      const byLine = lines.map(line=>{
        const cleaned = line.replace(/^\s*\d+\s*[\.\)조합:-]*\s*/, '');
        return parseNumsInput(cleaned).slice(0, 6);
      }).filter(c=>c.length >= 6);
      if(byLine.length) return byLine;
    }
    const nums = parseNumsInput(raw);
    const grouped = [];
    for(let i=0; i<nums.length; i+=6){
      const chunk = nums.slice(i, i+6);
      if(chunk.length === 6) grouped.push(chunk);
    }
    return grouped;
  }
  if(Array.isArray(combos)){
    if(combos.every(v=>typeof v === 'number' || /^\d+$/.test(String(v||'').trim()))){
      const nums = combos.map(Number).filter(n=>Number.isFinite(n));
      if(nums.length > 6){
        const grouped=[];
        for(let i=0;i<nums.length;i+=6){ const chunk=nums.slice(i,i+6); if(chunk.length===6) grouped.push(chunk); }
        return grouped;
      }
    }
    return combos.map(normalizeCombo).filter(c=>c.length);
  }
  if(typeof combos === 'object') return normalizeCombos(combos.numbers || combos.combos || combos.sets || combos.value || []);
  return [];
}
function getDefaultTemplate(){
  return '안녕하세요 {회원명}님, BBLOTTO입니다.\n\n{회차}회차 추천번호 안내드립니다.\n\n[추천번호]\n{추천번호}\n\n[AI 분석 요약]\n{분석}\n\nAI SCORE: {AI점수}\n최근 데이터와 조합 균형을 기준으로 선별했습니다.\n좋은 결과 있으시길 바랍니다.\n\n발송일: {발송일}';
}
function getBestAiScore(){
  const scores = (currentDetails || []).map(d=>Number(d.score ?? d.vip_score ?? d.ai_score ?? 0)).filter(Boolean);
  if(!scores.length) return '-';
  return Math.max(...scores).toFixed(1);
}
function formatComboLines(combos){
  const normalized = normalizeCombos(combos).map(c=>c.slice(0,6).map(Number).filter(n=>Number.isFinite(n)));
  return normalized.map((c,i)=>`${i+1}. ${c.join(', ')}`).join('\n') || '추천번호 없음';
}
function normalizeSmsLineBreaks(text){
  return normalizeText(text || '').replace(/\r\n/g,'\n').replace(/\r/g,'\n').replace(/\n{3,}/g,'\n\n');
}
function toSmsGandaCellBreaks(text){
  // RC7-11: 문자간다 구형 XLS 업로드 호환용. 내부 줄바꿈을 CRLF로 전달한다.
  return normalizeSmsLineBreaks(text || '').replace(/\n/g,'\r\n');
}
function buildTemplateMessage(member, round, combos, analysis){
  const tplRaw = $('template')?.value || '';
  const tpl = normalizeText(tplRaw).trim() || getDefaultTemplate();
  const name = member?.name || '회원';
  const today = new Date().toLocaleDateString('ko-KR');
  const analysisText = normalizeText(analysis || currentAnalysis).trim() || '분석 결과 없음';
  const numbers = formatComboLines(combos || currentCombos);
  return normalizeSmsLineBreaks(tpl
    .replaceAll('{회원명}', name)
    .replaceAll('{회차}', String(round || currentRound || '-'))
    .replaceAll('{추천번호}', numbers)
    .replaceAll('{분석}', analysisText)
    .replaceAll('{발송일}', today)
    .replaceAll('{AI점수}', String(getBestAiScore())));
}
function scrollToMessagePanel(){
  const target = $('memberMessagePanel') || $('smsPreview') || $('comboList');
  if(target) setTimeout(()=>target.scrollIntoView({behavior:'smooth', block:'center'}), 150);
}


function renderCombos(sets, details=[]){
  const box=$('comboList'); if(!box) return;
  if(!sets || !sets.length){
    box.classList.add('empty');
    box.innerHTML='추천번호를 생성하면 카드형 결과가 표시됩니다.';
    return;
  }
  box.classList.remove('empty');
  const top3 = top3FromDetails(sets, details);
  const topHtml = `<div class="top3-panel rc38-top3"><h4>TOP 3 우선 추천 <small>AI Engine V1.0</small></h4><div class="top3-grid">${top3.map(t=>{
    const d=t.detail||{}; const score=Number(d.score ?? d.vip_score ?? d.ai_score ?? 0);
    const nums=(t.nums||[]).map(n=>`<span class="mini-ball ${ballClass(n)}">${n}</span>`).join('');
    return `<div class="top3-card"><b>${t.idx}조합</b><div class="mini-nums">${nums}</div><span>${gradeLabel(d)} · ${engineLabel(d)}</span><strong>${score?score.toFixed(1):'-'}점</strong><em>${starLabel(d)}</em></div>`;
  }).join('')}</div></div>`;
  const cards = sets.map((arr,i)=>{
    const d = details[i] || {};
    const score = d.score ?? d.vip_score ?? d.ai_score ?? '';
    const sum = d.sum ?? arr.reduce((a,b)=>a+Number(b),0);
    const odd = d.odd ?? arr.filter(n=>Number(n)%2).length;
    const even = d.even ?? (6-odd);
    const zones = d.zones || [arr.filter(n=>n<=15).length, arr.filter(n=>n>=16&&n<=30).length, arr.filter(n=>n>=31).length];
    const tags = d.tags || d.reasons || [];
    const grade = `${gradeLabel(d)} · ${engineLabel(d)}`;
    const star = starLabel(d);
    return `<div class="combo-card v40-card ${i<3?'top-combo':''}">
      <div class="idx"><span>${i+1}조합</span><em>${grade} · ${score!=='' ? `${Number(score).toFixed(1)}점` : '점수 대기'}</em></div>
      <div class="nums">${arr.map(n=>`<span class="ball ${ballClass(n)}">${n}</span>`).join('')}</div>
      <div class="combo-meta">
        <span>${star}</span><span>합계 ${sum}</span><span>홀짝 ${odd}:${even}</span><span>구간 ${zones.join('/')}</span>
      </div>
      <div class="chip-row">${tags.slice(0,4).map(t=>`<span class="chip">${esc(t)}</span>`).join('')}</div>
    </div>`;
  }).join('');
  box.innerHTML = topHtml + `<div class="combo-card-grid">${cards}</div>`;
}

function buildFallbackAnalysis(combos, stats, mode){
  if(!combos || !combos.length) return '추천번호를 생성하면 실제 조합 기준 분석이 표시됩니다.';
  const flat = combos.flat().map(Number);
  const freq = new Map(); flat.forEach(n=>freq.set(n,(freq.get(n)||0)+1));
  const core = [...freq.entries()].sort((a,b)=>b[1]-a[1] || a[0]-b[0]).slice(0,6).map(x=>x[0]);
  const sums = combos.map(c=>c.reduce((a,b)=>a+Number(b),0));
  const avgSum = Math.round(sums.reduce((a,b)=>a+b,0)/sums.length);
  const odds = combos.map(c=>c.filter(n=>Number(n)%2).length);
  const avgOdd = (odds.reduce((a,b)=>a+b,0)/odds.length);
  const hot = stats?.hot?.slice?.(0,4) || [];
  const cold = stats?.cold?.slice?.(0,4) || [];
  const modeText = {balanced:'균형형',conservative:'안정형',aggressive:'공격형'}[mode] || mode || '균형형';
  const seed = Math.abs(flat.reduce((a,b,i)=>a + b*(i+3), 0) + Math.round(avgSum*7) + Math.round(avgOdd*11));
  const pick=(arr,salt=0)=>arr[(seed+salt)%arr.length];
  const openers = {
    balanced:[
      '이번 회차는 최근 흐름과 누적 데이터를 함께 비교해 안정적인 분포의 조합으로 구성했습니다.',
      '특정 번호대에 치우치지 않도록 전체 흐름을 기준으로 추천 조합을 선별했습니다.',
      '최근 당첨 흐름과 장기 통계를 함께 반영해 균형 중심으로 구성했습니다.'
    ],
    conservative:[
      '이번 회차는 과도한 변동보다 안정적인 번호 흐름을 우선해 조합을 선별했습니다.',
      '최근 흐름 안에서 무리한 편중을 줄이고 안정성을 높이는 방향으로 구성했습니다.',
      '누적 통계와 반복 패턴을 함께 살펴 안정적인 조합을 중심으로 선별했습니다.'
    ],
    aggressive:[
      '최근 흐름 변화가 큰 구간을 함께 반영해 적극적인 조합으로 구성했습니다.',
      '출현 가능성이 높아진 후보를 중심으로 변화를 준 조합을 선별했습니다.',
      '최근 강세 번호와 보강 후보를 함께 반영해 흐름 전환 가능성을 고려했습니다.'
    ]
  };
  const middles = [
    `주요 후보는 ${core.join(', ')}이며, 최근 흐름과 보강 후보를 함께 배분했습니다.`,
    hot.length ? `최근 흐름 번호(${hot.join(', ')})와 보강 후보(${cold.join(', ')})를 조합해 편중을 줄였습니다.` : `평균 합계 ${avgSum}와 홀짝 흐름을 함께 확인해 조합 균형을 맞췄습니다.`,
    `핵심 후보군은 ${core.join(', ')} 중심이며, 전체 조합 간 중복 가능성을 낮췄습니다.`,
    '최근 반복된 패턴은 일부만 반영하고, 새롭게 움직일 가능성이 있는 번호를 함께 보강했습니다.'
  ];
  const balances = [
    '홀짝 비율과 저·중·고 구간 분포를 함께 맞춰 전체적인 안정성을 높였습니다.',
    '끝수 흐름과 번호 간 간격을 확인해 비슷한 형태의 조합 반복을 줄였습니다.',
    '연속수와 반복 패턴은 필요한 범위 안에서만 반영해 조합 간 차이를 살렸습니다.',
    `${modeText} 기준에 맞춰 번호대, 끝수, 반복 흐름을 함께 점검했습니다.`
  ];
  const closers = [
    '전체적으로 최근 데이터와 누적 통계를 함께 고려한 심층 추천 결과입니다.',
    '이번 추천은 안정성과 변화 가능성을 함께 반영한 구성입니다.',
    '단순 빈도보다 번호 간 균형과 최근 흐름을 함께 본 추천입니다.',
    '최근 흐름을 유지하면서도 새로운 출현 가능성을 함께 고려했습니다.'
  ];
  const openerPool = openers[mode] || openers.balanced;
  const lines = [pick(openerPool,1), pick(middles,5), pick(balances,9)];
  if(seed % 3 !== 0) lines.push(pick(closers,13));
  return [...new Set(lines)].slice(0,4).join('\n');
}

function buildMemberMessage(member, round, combos, analysis){
  const name = member?.name || '회원';
  const numbers = formatComboLines(combos || currentCombos);
  const analysisText = normalizeText(analysis || currentAnalysis).trim() || '분석 결과 없음';
  const today = new Date().toLocaleDateString('ko-KR');
  return `안녕하세요 ${name}님, BBLOTTO입니다.\n\n${round || '-'}회차 추천번호 안내드립니다.\n\n[추천번호]\n${numbers}\n\n[AI 분석 요약]\n${analysisText}\n\nAI SCORE: ${getBestAiScore()}\n최근 데이터와 조합 균형을 기준으로 선별했습니다.\n좋은 결과 있으시길 바랍니다.\n\n발송일: ${today}`;
}

function renderAnalysis(text){
  const an=$('analysis'); if(!an) return;
  const lines = normalizeText(text).split('\n').map(x=>x.trim()).filter(Boolean);
  if(!lines.length){ an.textContent='추천번호를 생성하면 3~5줄 분석이 표시됩니다.'; return; }
  an.innerHTML = `<ul class="analysis-list">${lines.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>`;
}

function buildRecommendationAnalysis(combos, details=[]){
  const sets=normalizeCombos(combos);
  if(!sets.length) return '';
  const flat=sets.flat().map(Number).filter(Number.isFinite);
  const counts={}; flat.forEach(n=>counts[n]=(counts[n]||0)+1);
  const repeated=Object.entries(counts).filter(([,c])=>c>1).sort((a,b)=>b[1]-a[1]||Number(a[0])-Number(b[0])).slice(0,5).map(([n])=>Number(n));
  const low=flat.filter(n=>n<=15).length, mid=flat.filter(n=>n>=16&&n<=30).length, high=flat.filter(n=>n>=31).length;
  const zone=[['낮은 번호대',low],['중간 번호대',mid],['높은 번호대',high]].sort((a,b)=>b[1]-a[1])[0][0];
  const consecutive=sets.reduce((t,c)=>t+c.slice(0,-1).filter((n,i)=>Number(c[i+1])-Number(n)===1).length,0);
  const maxOverlap=sets.reduce((mx,a,i)=>Math.max(mx,...sets.slice(i+1).map(b=>a.filter(n=>b.includes(n)).length),0),0);
  const seed=(Date.now()+Math.floor(Math.random()*1000000)+flat.reduce((a,b,i)=>a+b*(i+1),0))>>>0;
  const pick=(arr,salt=0)=>arr[(seed+salt)%arr.length];

  const opening=[
    `이번 ${sets.length}개 조합은 서로 비슷한 모양이 반복되지 않도록 나누어 구성했습니다.`,
    `추천번호는 한 가지 흐름에 몰리지 않도록 여러 형태로 나누어 만들었습니다.`,
    `${sets.length}개 조합마다 번호 구성을 다르게 해 선택의 폭을 넓혔습니다.`,
    `이번 추천은 조합마다 특징이 겹치지 않도록 번호를 고르게 배치했습니다.`
  ];
  const zones=[
    `${zone}의 흐름이 조금 더 보이지만 다른 번호대도 함께 섞어 균형을 맞췄습니다.`,
    `낮은 번호부터 높은 번호까지 한쪽에 몰리지 않도록 나누어 넣었습니다.`,
    `번호대가 한 구간에 치우치지 않도록 조합별로 다르게 배치했습니다.`,
    `여러 번호대를 섞어 조합마다 비슷한 모습이 반복되지 않게 했습니다.`
  ];
  const repeats=repeated.length ? [
    `${repeated.join(', ')}번은 여러 조합에서 중심 역할을 하도록 나누어 반영했습니다.`,
    `공통으로 활용한 번호는 ${repeated.join(', ')}번이며, 나머지는 조합마다 다르게 구성했습니다.`,
    `${repeated.join(', ')}번을 중심 후보로 두고 주변 번호는 다양하게 바꿨습니다.`
  ] : [
    '같은 번호가 여러 조합에 지나치게 반복되지 않도록 구성했습니다.',
    '조합별 번호 중복을 줄여 각 조합의 차이를 살렸습니다.',
    '공통 번호를 최소화해 서로 다른 가능성을 나누어 담았습니다.'
  ];
  const shapes=[
    maxOverlap<=2 ? '조합끼리 겹치는 번호를 줄여 각각의 구성을 분명하게 했습니다.' : '겹치는 번호는 중심 후보에만 남기고 나머지는 다르게 배치했습니다.',
    consecutive ? '연속번호는 일부 조합에만 넣어 흐름을 살리면서 반복은 줄였습니다.' : '연속번호가 과하게 몰리지 않도록 전체 조합을 고르게 정리했습니다.',
    '홀수와 짝수, 번호 간 간격을 함께 살펴 자연스러운 구성을 우선했습니다.',
    '끝자리와 번호 간격이 비슷한 조합은 줄이고 서로 다른 형태를 선택했습니다.'
  ];
  const closing=[
    '전체적으로 보기 쉬우면서도 조합마다 차이가 나도록 정리한 추천입니다.',
    '최근 흐름을 반영하되 한 가지 패턴에만 치우치지 않도록 구성했습니다.',
    '비슷한 번호 조합을 줄이고 여러 가능성을 나누어 담았습니다.',
    '단순 반복보다 조합의 다양성과 균형을 우선한 결과입니다.'
  ];
  return [pick(opening,1),pick(zones,5),pick(repeats,9),pick(shapes,13),pick(closing,17)]
    .filter((v,i,a)=>v && a.indexOf(v)===i).slice(0,4).join('\n');
}

function renderRecommendationAnalysis(text){
  const an=$('recommendationAnalysis'); if(!an) return;
  const lines=normalizeText(text).split('\n').map(x=>x.trim()).filter(Boolean);
  if(!lines.length){ an.textContent='추천번호를 생성하면 조합별 선별 근거가 표시됩니다.'; return; }
  an.innerHTML=`<ul class="analysis-list">${lines.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>`;
}

function renderEngine(engine, details=[]){
  const eb=$('engineBox'); if(!eb) return;
  const scores = details.map(d=>Number(d.score ?? d.vip_score ?? d.ai_score ?? 0)).filter(Boolean);
  const avg = engine?.avg_score ?? (scores.length ? (scores.reduce((a,b)=>a+b,0)/scores.length).toFixed(1) : '');
  const candidate = engine?.candidate_count ?? engine?.combo_count ?? engine?.total_candidates ?? '';
  const filter = engine?.filter_count ?? engine?.passed_count ?? details.length;
  const top = scores.length ? Math.max(...scores).toFixed(1) : '';
  const min = scores.length ? Math.min(...scores).toFixed(1) : (engine?.min_score ?? '');
  const gradeEngine = engine?.engine_label || (details[0] ? engineLabel(details[0]) : 'AI BASIC');
  const memberGrade = engine?.member_grade ? memberGradeLabel(engine.member_grade) : (details[0] ? memberGradeLabel(details[0].member_grade || details[0].grade) : '일반');
  const v2 = engine?.v2_pipeline_report || engine?.v10_pipeline_report || {};
  const pipeline = engine?.rc38_report?.quality_message || v2.pipeline || '후보 생성 → 필터 → 중복/분산 보정 → 최종선별';
  const stage1 = v2.stage1_candidates ?? candidate ?? '-';
  const stage2 = v2.stage2_top500 ?? v2.stage2_filters ?? '-';
  const stage3 = v2.stage3_top100 ?? v2.stage3_portfolio ?? '-';
  eb.innerHTML = `<div class="engine-grid">
    <span><b>${gradeEngine}</b><small>${memberGrade} 엔진</small></span>
    <span><b>${avg || '-'}</b><small>평균 AI점수</small></span>
    <span><b>${top || '-'}</b><small>최고 점수</small></span>
    <span><b>${min || '-'}</b><small>최저 점수</small></span>
    <span><b>${filter || '-'}</b><small>최종 선별</small></span>
  </div>`;
}

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
      <div class="member-actions"><button class="combo-count-badge combo-generate-copy" data-action="member-generate-copy" data-member-id="${m.id}" title="이 회원 조합수로 추천번호 생성 후 문자 자동 복사">${esc(getMemberPreferredCount(m))}조합</button><button class="sms-save-copy-badge" data-action="member-generate-save" data-member-id="${m.id}" title="직전에 생성한 동일 추천번호를 복사하고 저장">복사저장</button><button data-action="member-select" data-member-id="${m.id}">선택</button><button data-action="member-detail" data-member-id="${m.id}">상세페이지</button><button data-action="member-status" data-member-id="${m.id}" data-status="활성">활성</button><button data-action="member-status" data-member-id="${m.id}" data-status="정지">정지</button><button data-action="member-status" data-member-id="${m.id}" data-status="탈퇴">탈퇴</button><button data-action="member-delete" data-member-id="${m.id}">삭제</button></div>
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
async function loadTemplate(){
  let text = '';
  try{ const d=await api('/api/template'); text = normalizeText(d); }
  catch(e){ try{ const s=await api('/api/settings'); text = normalizeText(s); }catch(_){} }
  setValue('template', text);
  refreshSmsPreview();
}
window.setStatsPage=function(p){ statsPage=Number(p)||1; renderStatsRecentDraws(); };
window.setStatsPageSize=function(v){ statsPageSize=Number(v)||10; statsPage=1; renderStatsRecentDraws(); };
function renderStatsRecentDraws(){
  const wrap=$('statsRecentDraws'); if(!wrap) return;
  const maxPage=Math.max(1, Math.ceil(statsRecentDrawsCache.length/statsPageSize));
  if(statsPage>maxPage) statsPage=maxPage;
  const items=statsRecentDrawsCache.slice((statsPage-1)*statsPageSize, (statsPage-1)*statsPageSize+statsPageSize);
  wrap.innerHTML = items.map(r=>`<div class="draw-row"><b>${r.round_no}회</b><span>${(r.numbers||[]).join(', ')} + ${r.bonus||''}</span><small>${r.draw_date||''}</small></div>`).join('') || '최근 회차 데이터 없음';
  renderPagination('statsPager', statsRecentDrawsCache.length, statsPage, statsPageSize, 'setStatsPage', 'setStatsPageSize');
}
function renderStats(d){
  latestStatsCache=d;
  const box=$('statsBox'); if(!box) return;
  if(!d || !d.count){ box.innerHTML='<div class="hint">저장된 당첨번호가 없어서 통계를 만들 수 없습니다. 당첨번호를 먼저 저장하세요.</div>'; return; }
  const hot=(d.hot||[]).map(n=>`<span class="ball ${ballClass(n)}">${n}</span>`).join('');
  const cold=(d.cold||[]).map(n=>`<span class="ball ${ballClass(n)}">${n}</span>`).join('');
  const miss=(d.missing20||d.overdue||[]).map(n=>`<span class="ball ${ballClass(n)}">${n}</span>`).join('');
  const pairs=(d.top_pairs||[]).map(p=>`<span class="mini-chip">${(p.pair||[]).join('-')} · ${p.count}회</span>`).join('');
  statsRecentDrawsCache=(d.recent_draws||[]);
  const freq=d.freq || d.freq100 || {};
  const maxFreq=Math.max(1, ...Object.values(freq).map(Number));
  const bars=Object.entries(freq).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,15).map(([n,c])=>`<div class="stats-bar"><b>${n}</b><div><i style="width:${Math.round(Number(c)/maxFreq*100)}%"></i></div><span>${c}회</span></div>`).join('');
  box.innerHTML=`<div class="stats-dashboard">
    <div class="stats-kpi">
      <div class="stat-card"><b>${d.count}</b><span>전체 분석 회차</span></div>
      <div class="stat-card"><b>${d.sum_avg}</b><span>평균 합계</span></div>
      <div class="stat-card"><b>${d.odd}:${d.even}</b><span>홀짝 누적</span></div>
      <div class="stat-card"><b>${(d.sections||[]).join(' / ')}</b><span>구간 1~15 / 16~30 / 31~45</span></div>
    </div>
    <div class="detail-section full-history-status"><h4>전체 회차 분석 상태</h4><div class="history-range"><b>${(d.round_range||[])[0]||1}회차부터 ${(d.round_range||[])[1]||d.latest_round||'-'}회차까지</b><span>총 ${d.count||0}개 회차 분석</span></div><div class="hint">${d.analysis_confirm||'분석 상태 확인 중'} · 누락 ${d.missing_rounds_count||0}개 · 전체분석 ${d.is_full_history?'완료':'미완료'}</div></div>
    <div class="stats-panels">
      <div class="detail-section"><h4>HOT 번호</h4><div class="nums-line">${hot}</div><h4>COLD 번호</h4><div class="nums-line">${cold}</div><h4>미출현/공백 번호</h4><div class="nums-line">${miss}</div></div>
      <div class="detail-section"><h4>번호 발생 빈도 TOP 15</h4><div class="stats-bars">${bars||'데이터 없음'}</div></div>
    </div>
    <div class="detail-section"><h4>동반출현 TOP</h4><div class="pair-line">${pairs||'데이터 없음'}</div></div>
    <div class="detail-section"><h4>회차별 당첨번호 · 전체 ${(d.count||0).toLocaleString()}회차를 페이지로 확인</h4><div id="statsRecentDraws" class="recent-draws-100"></div><div id="statsPager" class="pager"></div></div>
  </div>`;
  renderStatsRecentDraws();
}
async function loadStats(limit=0){
  const d=await api('/api/stats?limit='+limit);
  renderStats(d);
  const live = buildRealtimeRoundAnalysis(d);
  if(live && (!currentAnalysis || currentAnalysis.includes('데이터 없음') || currentAnalysis.includes('분석 준비'))){
    currentAnalysis = live;
    renderAnalysis(currentAnalysis);
    refreshSmsPreview();
  }
  return d;
}
function buildRealtimeRoundAnalysis(stats){
  if(!stats || !stats.count) return '';
  const latest = stats.latest || (stats.recent_draws||[])[0] || {};
  const nextRound = Number(latest.round_no || 0) ? Number(latest.round_no) + 1 : (currentRound || '');
  const hot = (stats.hot||[]).slice(0,6).join(', ') || '데이터 없음';
  const cold = (stats.cold||[]).slice(0,6).join(', ') || '데이터 없음';
  const miss = (stats.missing20||[]).slice(0,6).join(', ') || '데이터 없음';
  const sections = (stats.sections||[]).join(' / ') || '-';
  const pair = (stats.top_pairs||[]).slice(0,3).map(p=>(p.pair||[]).join('-')).filter(Boolean).join(', ') || '데이터 없음';
  return `${nextRound?nextRound+'회차 ':''}실시간 분석입니다.\n최근 ${stats.count}회 기준 강세번호는 ${hot}, 보완번호는 ${cold}입니다.\n구간 흐름은 ${sections}, 공백수는 ${miss}, 동반출현 핵심은 ${pair}입니다.`;
}
window.setDrawPage=function(p){ drawPage=Number(p)||1; renderDrawList(); };
window.setDrawPageSize=function(v){ drawPageSize=Number(v)||10; drawPage=1; renderDrawList(); };
function renderDrawList(){
  const box=$('drawList'); if(!box) return;
  const maxPage=Math.max(1, Math.ceil(drawRowsCache.length/drawPageSize));
  if(drawPage>maxPage) drawPage=maxPage;
  const rows=drawRowsCache.slice((drawPage-1)*drawPageSize, (drawPage-1)*drawPageSize+drawPageSize);
  box.innerHTML = `<div class="draw-page-list">${rows.map(r=>`<p><b>${r.round_no}회</b> ${(r.numbers||[]).join(', ')} + ${r.bonus||''} <small>${r.draw_date||''}</small></p>`).join('') || '저장된 당첨번호가 없습니다.'}</div><div id="drawPager" class="pager"></div>`;
  renderPagination('drawPager', drawRowsCache.length, drawPage, drawPageSize, 'setDrawPage', 'setDrawPageSize');
}
async function loadDraws(){
  try{
    drawRowsCache=await api('/api/draws?limit=100');
    drawPage=1;
    renderDrawList();
  }catch(e){ console.error(e); }
}
async function setNextDrawRound(){
  try{
    const d=await api('/api/draws/next');
    const latest=d.latest || {};
    const current=d.current || {};
    // PHASE19: 당첨확인은 오늘/현재 추첨 회차를 우선 표시하고, 추천생성은 다음 관리 회차를 사용합니다.
    if($('checkRound')) $('checkRound').value = d.check_round || d.expected_round || d.latest_round || d.next_round || '';
    const check=d.check || {};
    const drawObj=(check.numbers?.length ? check : (current.numbers?.length ? current : {}));
    if(drawObj.numbers?.length){
      if($('winningNums')) $('winningNums').value = drawObj.numbers.join(' ');
      if($('bonusNum')) $('bonusNum').value = drawObj.bonus || '';
    }else{
      // 추첨 전/번호 미공개 상태에서는 직전 회차 번호가 오늘 회차 당첨번호처럼 들어가지 않도록 비웁니다.
      if($('winningNums')) $('winningNums').value = '';
      if($('bonusNum')) $('bonusNum').value = '';
    }
    if($('autoRoundInfo')){
      const msg=d.message || '';
      const latestText=d.latest_round ? `최신 저장 ${d.latest_round}회` : '저장된 회차 없음';
      const checkText=d.check_round ? `당첨확인 ${d.check_round}회` : '';
      const genText=d.next_round ? `추천생성 ${d.next_round}회` : '';
      $('autoRoundInfo').textContent = `${latestText} · ${checkText} · ${genText}${msg ? ' / '+msg : ''}`;
    }
    if(d.next_round) currentRound = d.next_round;
    else if(d.expected_round) currentRound = d.expected_round;
    else if(d.latest_round) currentRound = d.latest_round;
    if(latestStatsCache){
      const live = buildRealtimeRoundAnalysis(latestStatsCache);
      if(live && (!currentAnalysis || currentAnalysis.includes('분석 준비'))) currentAnalysis = live;
    }
    refreshSmsPreview();
    return d;
  }catch(e){ console.error(e); return null; }
}
function rankBadgeClass(rank){
  const r=String(rank||'낙첨');
  if(r.includes('1')) return 'rank-1';
  if(r.includes('2')) return 'rank-2';
  if(r.includes('3')) return 'rank-3';
  if(r.includes('4')) return 'rank-4';
  if(r.includes('5')) return 'rank-5';
  return 'rank-lose';
}
function renderWinNumberChips(nums){
  const arr=Array.isArray(nums) ? nums : String(nums||'').split(/[^0-9]+/).filter(Boolean).map(Number);
  return arr.slice(0,6).map(n=>`<span class="num-chip">${esc(n)}</span>`).join('');
}
window.toggleWinMember=function(mid){
  const el=$('winMemberDetail_'+mid);
  const btn=$('winMemberArrow_'+mid);
  if(!el) return;
  const open=el.style.display==='block';
  el.style.display=open?'none':'block';
  if(btn) btn.textContent=open?'›':'⌄';
};
window.setWinCheckPage=function(p){ winCheckPage=Number(p)||1; renderWinningResult({member_results:winCheckCache, summary:winCheckSummaryCache, ...winCheckMetaCache}); };
window.setWinCheckPageSize=function(v){ winCheckPageSize=Number(v)||10; winCheckPage=1; renderWinningResult({member_results:winCheckCache, summary:winCheckSummaryCache, ...winCheckMetaCache}); };
function renderWinningResult(d){
  const box=$('winningResult'); if(!box) return;
  const members=Array.isArray(d.member_results) ? d.member_results : [];
  const fallbackGroup={};
  if(!members.length && Array.isArray(d.results)){
    d.results.forEach(r=>{
      if(!r.member_id) return;
      const key=r.member_id;
      if(!fallbackGroup[key]) fallbackGroup[key]={member_id:r.member_id,member_name:r.member_name||'회원명 미확인',total_combos:0,hit_count:0,lose_count:0,total_prize:0,best_rank:'낙첨',best_prize:0,combos:[]};
      const g=fallbackGroup[key];
      g.total_combos++; g.total_prize+=Number(r.prize||0); g.combos.push(r);
      if(r.rank && r.rank!=='낙첨') g.hit_count++; else g.lose_count++;
      const order={'1등':1,'2등':2,'3등':3,'4등':4,'5등':5,'낙첨':9};
      if((order[r.rank]||9) < (order[g.best_rank]||9)){ g.best_rank=r.rank; g.best_prize=Number(r.prize||0); }
    });
  }
  const list=members.length ? members : Object.values(fallbackGroup);
  winCheckCache = list;
  winCheckSummaryCache = d.summary||{};
  winCheckMetaCache = {round_no:d.round_no||d.round, round:d.round_no||d.round, wins:d.wins||[], bonus:d.bonus||''};
  const maxPage=Math.max(1, Math.ceil(list.length/winCheckPageSize));
  if(winCheckPage>maxPage) winCheckPage=maxPage;
  const pageItems=list.slice((winCheckPage-1)*winCheckPageSize, (winCheckPage-1)*winCheckPageSize+winCheckPageSize);
  const summary=d.summary||{};
  const rows=pageItems.map((m,idx)=>{
    const best=m.best_rank||'낙첨';
    const key=String(m.member_id || ((winCheckPage-1)*winCheckPageSize+idx));
    const combos=(m.combos||[]).map((c,i)=>`<tr>
      <td>${esc(c.combo_index||i+1)}번</td>
      <td>${renderWinNumberChips(c.combo||[])}</td>
      <td>${esc(c.match_count||0)}개${c.bonus_match?' + 보너스':''}</td>
      <td><span class="rank-badge ${rankBadgeClass(c.rank)}">${esc(c.rank||'낙첨')}</span></td>
      <td>${Number(c.prize||0).toLocaleString()}원</td>
    </tr>`).join('');
    return `<div class="win-member-card">
      <div class="win-member-row">
        <div class="win-member-name"><b>${esc(m.member_name||'회원명 미확인')}</b><small>${esc(m.total_combos||0)}조합 확인</small></div>
        <div><b>${esc(m.hit_count||0)}</b><small>당첨</small></div>
        <div><b>${esc(m.lose_count||0)}</b><small>낙첨</small></div>
        <div><span class="rank-badge ${rankBadgeClass(best)}">${esc(best)}</span><small>최고당첨</small></div>
        <div><b>${Number(m.total_prize||0).toLocaleString()}원</b><small>총 당첨금</small></div>
        <button class="icon-btn" id="winMemberArrow_${esc(key)}" data-action="winning-toggle" data-key="${esc(key)}">›</button>
      </div>
      <div class="win-member-detail" id="winMemberDetail_${esc(key)}" style="display:none">
        <div class="win-detail-head"><b>${esc(d.round_no || d.round)}회 추천 조합 상세</b><span>당첨번호 ${renderWinNumberChips(d.wins||[])} ${d.bonus?`+ <span class="num-chip bonus">${esc(d.bonus)}</span>`:''}</span></div>
        <table class="simple-table win-combo-table"><thead><tr><th>조합</th><th>추천번호</th><th>일치</th><th>결과</th><th>당첨금</th></tr></thead><tbody>${combos||'<tr><td colspan="5">확인된 조합이 없습니다.</td></tr>'}</tbody></table>
      </div>
    </div>`;
  }).join('');
  box.innerHTML=`<div class="result-summary rc44-win-summary"><b>${esc(d.round_no || d.round)}회차 회원별 자동 확인 완료</b><br>
    회원 ${summary.members||list.length||0}명 / 추천 ${summary.recommendations||0}건 / 조합 ${summary.checked_combos||0}개 / 당첨조합 ${summary.hit_combos||0}개 / 낙첨조합 ${summary.lose_combos||0}개 / 총 당첨금 ${Number(summary.prize||0).toLocaleString()}원</div>
    <div class="win-member-list">${rows||'<div class="empty-detail">해당 회차 회원별 추천 이력이 없습니다.</div>'}</div><div id="winCheckPager" class="pager"></div>`;
  renderPagination('winCheckPager', list.length, winCheckPage, winCheckPageSize, 'setWinCheckPage', 'setWinCheckPageSize');
}
function openPanel(tabId, title){
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active', b.dataset.tab===tabId));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  const p=$(tabId); if(p) p.classList.add('active');
  if(title) setText('pageTitle', title);
  window.scrollTo({top:0, behavior:'smooth'});
}

function formatLongText(text, maxLen=900){
  const value = normalizeText(text || '');
  if(!value) return '<span class="hint">내용 없음</span>';
  const safeText = esc(value.length > maxLen ? value.slice(0, maxLen) + '…' : value);
  return `<pre class="detail-pre">${safeText}</pre>`;
}

function formatMoney(v){ return Number(v||0).toLocaleString() + '원'; }
function renderRecommendCards(items){
  if(!Array.isArray(items) || !items.length) return '<div class="empty-detail">추천 이력이 없습니다.</div>';
  return items.slice(0,20).map(r=>{
    const sets = normalizeCombos(r.numbers || []);
    const nums = sets.slice(0,5).map((c,i)=>`<div class="mini-rec-line"><b>${i+1}</b><span>${c.join(', ')}</span></div>`).join('') || '<span class="hint">번호 없음</span>';
    return `<details class="detail-history rec-history" open>
      <summary><b>${esc(r.round_no || '-')}회 추천</b><small>${esc(r.created_at || '')} · ${esc(r.mode||'balanced')} · 평균 ${esc(r.avg_score||'-')}</small></summary>
      <div class="mini-rec-list">${nums}</div>
      ${formatLongText(r.analysis || '', 500)}
    </details>`;
  }).join('');
}
function renderNoteCards(items){
  if(!Array.isArray(items) || !items.length) return '<div class="empty-detail">상담 이력이 없습니다.</div>';
  return items.slice(0,30).map(r=>`<div class="note-card"><div><b>${esc(r.note_type||'상담')}</b><small>${esc(r.created_at||'')} · ${esc(r.created_by_name||'관리자')}</small></div>${formatLongText(r.note||'', 700)}</div>`).join('');
}
function renderHistoryCards(items, type, memberId){
  if(!Array.isArray(items) || !items.length) return '<div class="empty-detail">이력이 없습니다.</div>';
  return items.slice(0, 30).map((r)=>{
    if(type==='sms'){
      const mid = memberId || r.member_id || '';
      return `<details class="detail-history sms-history" open>
        <summary>
          <span><b>${esc(r.round_no || '-')}회 문구</b><small>${esc(r.created_at || '')}</small></span>
          <button class="danger small sms-delete-btn" data-action="sms-delete" data-log-id="${Number(r.id)||0}" data-member-id="${Number(mid)||0}">삭제</button>
        </summary>
        ${formatLongText(r.body || r.message || r.content || '', 900)}
      </details>`;
    }
    return renderWinningHistoryCard(r);
  }).join('');
}
function rankClass(rank){
  const txt=String(rank||'낙첨');
  if(txt.includes('1등')) return 'rank-1';
  if(txt.includes('2등')) return 'rank-2';
  if(txt.includes('3등')) return 'rank-3';
  if(txt.includes('4등')) return 'rank-4';
  if(txt.includes('5등')) return 'rank-5';
  return 'rank-miss';
}
function renderWinningHistorySummary(items){
  if(!Array.isArray(items) || !items.length) return '<div class="empty-detail">당첨 이력이 없습니다.</div>';
  const list=items.slice(0,20);
  const counts={'1등':0,'2등':0,'3등':0,'4등':0,'5등':0,'낙첨':0};
  let totalPrize=0;
  list.forEach(r=>{
    const rank=String(r.rank||'낙첨');
    const key=['1등','2등','3등','4등','5등'].find(x=>rank.includes(x)) || '낙첨';
    counts[key]+=1;
    totalPrize += Number(r.prize||0);
  });
  const hit=list.length-counts['낙첨'];
  const rate=list.length ? Math.round((hit/list.length)*100) : 0;
  const best=['1등','2등','3등','4등','5등'].find(k=>counts[k]>0) || '없음';
  return `<div class="win-summary-box">
    <div class="win-summary-top">
      <div><b>${list.length}</b><span>최근 확인</span></div>
      <div><b>${hit}</b><span>적중</span></div>
      <div><b>${rate}%</b><span>적중률</span></div>
      <div><b>${esc(best)}</b><span>최고기록</span></div>
      <div><b>${formatMoney(totalPrize)}</b><span>최근 당첨금</span></div>
    </div>
    <div class="win-rank-strip">
      ${['1등','2등','3등','4등','5등','낙첨'].map(k=>`<span class="${rankClass(k)}"><em>${k}</em><b>${counts[k]}</b></span>`).join('')}
    </div>
    <div class="win-card-list">${list.map(renderWinningHistoryCard).join('')}</div>
  </div>`;
}
function renderWinningHistoryCard(r){
  const rank=esc(r.rank || '낙첨');
  const numbersRaw = r.numbers || r.combo || r.recommend_numbers || '';
  const numbers = Array.isArray(numbersRaw) ? numbersRaw.join(', ') : String(numbersRaw||'');
  const matched = (r.matched_count ?? r.match_count ?? r.matches ?? '-');
  const bonusRaw = (r.bonus_match ?? r.bonus ?? false);
  const bonus = bonusRaw===true || bonusRaw==='true' || bonusRaw==='O' || bonusRaw===1 ? 'O' : '-';
  const prize = Number(r.prize||0);
  return `<div class="win-history-card ${rankClass(r.rank)}">
    <div class="win-card-head"><b>${esc(r.round_no || '-')}회</b><span>${rank}</span></div>
    <div class="win-card-nums">${numbers ? esc(numbers) : '<span class="hint">추천번호 없음</span>'}</div>
    <div class="win-card-meta"><small>일치 ${esc(matched)}개 · 보너스 ${esc(bonus)}</small><strong>${prize.toLocaleString()}원</strong></div>
  </div>`;
}

function applyAdminVisibility(isSuper){
  // PHASE28: 일반 관리자는 시스템/관리자 관리 메뉴를 숨기고, 내 계정만 허용
  ['adminSecurityBox','adminBackupBox','adminStatsBox','adminLogsBox','adminAddBox','adminAiEngineBox'].forEach(id=>{
    const el=$(id);
    if(el) el.style.display = isSuper ? '' : 'none';
  });
  document.querySelectorAll('.nav[data-tab="admin"]').forEach(btn=>{ btn.style.display = isSuper ? '' : 'none'; });
}


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
  await saveCurrentRecommendation();
  try{ return await api('/api/sms_log',{method:'POST',body}); }
  catch(e){ return await api('/api/sms',{method:'POST',body}); }
}

function captureCurrentMemberResult(memberId){
  const snapshot={
    memberId:String(memberId),
    combos:normalizeCombos(currentCombos),
    details:Array.isArray(currentDetails) ? JSON.parse(JSON.stringify(currentDetails)) : [],
    sms:String(($('smsPreview')?.value || currentSms || '')).trim(),
    analysis:String(currentAnalysis||''),
    recommendationAnalysis:String(currentRecommendationAnalysis||''),
    round:currentRound,
    recId:null
  };
  memberQuickResults.set(String(memberId), snapshot);
  return snapshot;
}

function restoreMemberResult(memberId){
  const snapshot=memberQuickResults.get(String(memberId));
  if(!snapshot || !normalizeCombos(snapshot.combos).length) return null;
  currentCombos=normalizeCombos(snapshot.combos);
  currentDetails=Array.isArray(snapshot.details) ? JSON.parse(JSON.stringify(snapshot.details)) : [];
  currentSms=String(snapshot.sms||'');
  currentAnalysis=String(snapshot.analysis||'');
  currentRecommendationAnalysis=String(snapshot.recommendationAnalysis||'');
  currentRound=snapshot.round||'';
  currentRecId=snapshot.recId||null;
  renderCombos(currentCombos,currentDetails);
  renderAnalysis(currentAnalysis);
  renderRecommendationAnalysis(currentRecommendationAnalysis);
  refreshSmsPreview();
  saveWorkspaceState();
  return snapshot;
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
    const snapshot=captureCurrentMemberResult(id);
    let copied=false;
    try{ await copyTextToClipboard(snapshot.sms); copied=true; }
    catch(copyError){ console.warn('문자 복사 권한이 차단되었습니다.', copyError); }
    toast(`${m.name} ${expected}조합 새 번호 생성 완료${copied?' · 문자 복사 완료':' · 복사는 브라우저에서 차단됨'}`);
    if(btn) btn.textContent=copied?'복사완료':'생성완료';
    setTimeout(()=>{ if(btn){ btn.textContent=oldText || `${getMemberPreferredCount(m)}조합`; btn.disabled=false; } }, 1200);
  }catch(e){
    console.error(e);
    if(btn){ btn.textContent=oldText || `${getMemberPreferredCount(m)}조합`; btn.disabled=false; }
    alert('자동 생성 실패: '+(e.message||e));
  }
});

window.generateMemberCopyAndSave = safe(async function(id, btn){
  const m=membersCache.find(x=>String(x.id)===String(id));
  if(!m){ alert('회원을 찾을 수 없습니다.'); return; }
  const oldText = btn?.textContent;
  try{
    const snapshot=memberQuickResults.get(String(id));
    if(!snapshot || !normalizeCombos(snapshot.combos).length){
      alert(`먼저 ${getMemberPreferredCount(m)}조합 버튼을 눌러 추천번호를 생성하세요.`);
      return;
    }
    if(btn){ btn.disabled=true; btn.textContent='저장중'; }
    window.selectMember(id);
    const restored=restoreMemberResult(id);
    if(!restored) throw new Error('저장할 추천번호를 찾지 못했습니다. 다시 조합 버튼을 눌러주세요.');
    const expected=getMemberPreferredCount(m);
    if(normalizeCombos(currentCombos).length!==expected) throw new Error(`현재 생성 결과가 ${expected}조합이 아닙니다. 다시 조합 버튼을 눌러주세요.`);

    // 번호를 새로 생성하지 않고, 직전에 만든 동일 번호를 먼저 저장합니다.
    await saveCurrentSmsLog();
    const savedRecId=currentRecId;
    const savedSnapshot={...restored, recId:savedRecId};
    memberQuickResults.set(String(id), savedSnapshot);

    let copied=false;
    try{ await copyTextToClipboard(($('smsPreview')?.value || currentSms || '').trim()); copied=true; }
    catch(copyError){ console.warn('저장은 완료됐지만 문자 복사가 차단되었습니다.', copyError); }

    await Promise.all([loadDashboard(), loadMembers()]);
    if($('genMember')) $('genMember').value=String(id);
    restoreMemberResult(id);
    toast(`${m.name} ${expected}조합 동일 번호 저장 완료${copied?' · 문자 복사 완료':' · 복사는 브라우저에서 차단됨'}`);
    if(btn) btn.textContent='저장완료';
    setTimeout(()=>{ if(btn){ btn.textContent=oldText || '복사저장'; btn.disabled=false; } }, 1200);
  }catch(e){
    console.error(e);
    if(btn){ btn.textContent=oldText || '복사저장'; btn.disabled=false; }
    alert('복사저장 실패: '+(e.message||e));
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
window.deleteMember=safe(async function(id){ if(!confirm('삭제할까요?')) return; await api('/api/members/'+id,{method:'DELETE'}); await loadMembers(); await loadDashboard(); });
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
  const next=await setNextDrawRound();
  try{ await loadStats(0); }catch(e){ console.warn('최신 통계 갱신 실패', e); }
  const defaultRound = Number(next?.next_round || next?.latest_round || 0) || undefined;
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
    currentRecommendationAnalysis=buildRecommendationAnalysis(currentCombos,currentDetails);
    currentSms=normalizeText(d.sms||'') || buildTemplateMessage(getSelectedMember(), currentRound, currentCombos, currentAnalysis);
    setText('roundLabel', currentRound ? `${currentRound}회차 추천번호 · 심층분석 완료` : '생성 완료');
    renderCombos(currentCombos,currentDetails);
    renderAnalysis(currentAnalysis);
    renderRecommendationAnalysis(currentRecommendationAnalysis);
    renderEngine(d.engine,currentDetails);
    refreshSmsPreview();
    await loadStats(0);
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
function renderDrawSearchResult(d){
  const box=$('drawSearchResult'); if(!box) return;
  if(!d){ box.innerHTML='조회 결과가 없습니다.'; return; }
  const nums=(d.numbers||[]).map(n=>`<span class="ball ${ballClass(n)}">${n}</span>`).join('');
  if(d.ok){
    box.innerHTML=`<div class="draw-search-result"><b>${d.round_no}회</b> <small>${d.draw_date||''}</small><div class="nums-line">${nums}<span class="bonus-ball">보너스 ${d.bonus||''}</span></div><p>${esc(d.message||'조회 완료')}</p></div>`;
  }else{
    box.innerHTML=`<div class="draw-search-result warn"><b>${d.round_no||'-'}회</b> <small>${d.draw_date||''}</small><p>${esc(d.message||'조회 실패')}</p></div>`;
  }
}
async function searchDrawByRound(){
  const r=Number($('drawSearchRound')?.value||0);
  if(!r){ alert('조회할 회차를 입력하세요.'); return; }
  setBusy('searchDraw', true, '조회 중...');
  try{
    const d=await api('/api/draws/search?round_no='+encodeURIComponent(r));
    lastSearchedDraw=d && d.ok ? d : null;
    renderDrawSearchResult(d);
    if(d && d.ok){ await Promise.allSettled([loadDraws(), loadStats(0), loadDashboard()]); }
  }catch(e){
    lastSearchedDraw=null;
    renderDrawSearchResult({ok:false, round_no:r, message:e?.message || '회차 조회에 실패했습니다.'});
  }finally{ setBusy('searchDraw', false); }
}
function applySearchedDrawToCheck(){
  if(!lastSearchedDraw || !lastSearchedDraw.numbers?.length){ alert('먼저 회차 조회를 완료하세요.'); return; }
  if($('checkRound')) $('checkRound').value=lastSearchedDraw.round_no;
  if($('winningNums')) $('winningNums').value=(lastSearchedDraw.numbers||[]).join(' ');
  if($('bonusNum')) $('bonusNum').value=lastSearchedDraw.bonus||'';
  setText('autoRoundInfo', `${lastSearchedDraw.round_no}회 당첨번호를 당첨확인 입력칸에 적용했습니다.`);
  toast('조회한 당첨번호를 적용했습니다.');
}

async function checkWinning(){
  // PHASE20: 회차/당첨번호 확인을 백엔드 자동화에 맡깁니다.
  // 번호가 비어 있으면 해당 회차 공식 번호를 자동 조회하고, 아직 공개 전이면 안내 메시지를 받습니다.
  if(!$('checkRound')?.value) await setNextDrawRound();
  const body={round_no:Number($('checkRound')?.value||0), winning:$('winningNums')?.value||'', bonus:Number($('bonusNum')?.value||0)};
  if(!body.round_no){ alert('회차를 자동으로 불러오지 못했습니다.'); return; }
  setBusy('checkWinning',true,'자동 확인 중...');
  try{
    const d=await api('/api/check_winning',{method:'POST',body});
    if(d.wins?.length){ if($('winningNums')) $('winningNums').value=d.wins.join(' '); if($('bonusNum')) $('bonusNum').value=d.bonus||''; }
    renderWinningResult(d);
    toast('당첨번호 자동확인이 완료되었습니다.');
    await Promise.all([loadStats(0),loadDraws(),loadDashboard(),setNextDrawRound()]);
  }catch(e){
    const msg = e?.message || '당첨번호 자동확인에 실패했습니다.';
    alert(msg + '\n\n공식 조회가 막힌 경우에는 당첨번호 6개와 보너스 번호를 직접 입력한 뒤 다시 누르면 저장/확인이 가능합니다.');
  }
  finally{ setBusy('checkWinning',false); }
}
async function saveDraw(){ await checkWinning(); }


function renderMyAccount(){
  if(!currentAdmin) return;
  setValue('myUsername', currentAdmin.username || '');
  setValue('myName', currentAdmin.name || '관리자');
  setValue('myPhone', currentAdmin.phone || '');
  setValue('myMemo', currentAdmin.memo || '');
  const roleText = currentAdmin.is_super_admin ? '최고관리자' : '일반관리자';
  setText('myLoginInfo', `${roleText} · 마지막 로그인 ${currentAdmin.last_login_at || '기록 없음'} · 최근 활동 ${currentAdmin.last_seen_at || '-'} · 자동 로그아웃까지 ${Math.ceil((currentAdmin.expires_in_seconds||0)/60)}분`);
}
async function loadMyAccount(){
  currentAdmin = await api('/api/me');
  setText('who', currentAdmin.name || currentAdmin.username || '관리자');
  startSessionWatcher(currentAdmin);
  applyAdminVisibility(!!currentAdmin?.is_super_admin);
  renderMyAccount();
}
async function saveMyProfile(){
  const body={name:$('myName')?.value||'관리자', phone:$('myPhone')?.value||'', memo:$('myMemo')?.value||''};
  await api('/api/me',{method:'PUT',body});
  toast('내 계정 정보를 저장했습니다.');
  await loadMyAccount();
}
async function saveMyPassword(){
  const current_password=$('myCurrentPw')?.value||'';
  const new_password=$('myNewPw')?.value||'';
  const confirm=$('myNewPw2')?.value||'';
  if(!current_password) return alert('현재 비밀번호를 입력하세요.');
  if(new_password.length<4) return alert('새 비밀번호는 4자리 이상입니다.');
  if(new_password!==confirm) return alert('새 비밀번호 확인이 맞지 않습니다.');
  await api('/api/me',{method:'PUT',body:{current_password,new_password}});
  ['myCurrentPw','myNewPw','myNewPw2'].forEach(id=>setValue(id,''));
  toast('비밀번호를 변경했습니다.');
}
async function saveSmsSettings(){
  toast('문자 발송 설정은 관리자 페이지에서 제거되었습니다.');
}
async function saveSessionTimeout(){
  const v=String(Math.max(10, Math.min(1440, Number($('sessionTimeout')?.value||600))));
  await api('/api/settings',{method:'POST',body:{key:'session_timeout_minutes',value:v}});
  toast('자동 로그아웃 시간을 저장했습니다.');
}
async function createBackup(){
  const d=await api('/api/backups/create',{method:'POST',body:{}});
  toast('백업 생성 완료: '+(d.filename||''));
  await loadAdmin();
}

window.validateBackup=async function(filename){
  const d=await api('/api/backups/validate/'+encodeURIComponent(filename));
  const counts=d.table_counts||{};
  alert('백업 검증 완료\n파일: '+filename+'\n생성: '+(d.created_at||'')+'\n테이블: '+Object.entries(counts).map(([k,v])=>k+': '+v).join(', '));
};
window.restoreBackup=async function(filename){
  if(!confirm('정말 이 백업으로 복원할까요? 현재 DB 내용이 백업 기준으로 교체됩니다.')) return;
  const d=await api('/api/backups/restore/'+encodeURIComponent(filename),{method:'POST',body:{}});
  toast('복원 완료: '+filename);
  await loadAdmin();
};
window.cleanupBackups=async function(){
  const keep=prompt('최근 몇 개 백업을 남길까요?', '20');
  if(!keep) return;
  const d=await api('/api/backups/cleanup?keep='+encodeURIComponent(keep),{method:'POST',body:{}});
  toast('백업 정리 완료: '+(d.removed||[]).length+'개 삭제');
  await loadAdmin();
};
window.cleanupSessions=async function(){
  await api('/api/sessions/cleanup',{method:'POST',body:{}});
  toast('만료 세션을 정리했습니다.');
  await loadAdmin();
};

async function addAdmin(){
  if(!currentAdmin?.is_super_admin){ alert('최고 관리자만 관리자 계정을 생성할 수 있습니다.'); return; }
  const body={username:$('newAdmin')?.value||'', name:$('newAdminName')?.value||'관리자', password:$('newAdminPw')?.value||'', role:$('newAdminRole')?.value||'전체권한', memo:$('newAdminMemo')?.value||''};
  if(!body.username || body.password.length<4){ alert('관리자 아이디와 4자리 이상 비밀번호를 입력하세요.'); return; }
  await api('/api/admins',{method:'POST',body});
  ['newAdmin','newAdminName','newAdminPw','newAdminMemo'].forEach(x=>setValue(x,''));
  setValue('newAdminRole','일반관리자');
  toast('관리자를 생성했습니다.'); closeAdminCreateModal(); await loadAdmin();
}
window.addAdmin=safe(addAdmin);
window.deleteAdmin=safe(async function(id, username){
  if(!confirm(`관리자 ${username || id} 계정을 완전히 삭제할까요?\n삭제하면 해당 관리자는 로그인할 수 없습니다.`)) return;
  await api('/api/admins/'+id,{method:'DELETE'});
  toast('관리자를 삭제했습니다.');
  await loadAdmin();
});
window.activateAdmin=safe(async function(id){
  await api('/api/admins/'+id+'/activate',{method:'POST',body:{}});
  toast('관리자를 활성화했습니다.');
  await loadAdmin();
});
window.toggleAdmin=safe(async function(id, active){
  if(active===0 && !confirm('이 관리자를 비활성화할까요?')) return;
  await api('/api/admins/'+id,{method:'PUT',body:{is_active:active}});
  toast(active ? '관리자를 활성화했습니다.' : '관리자를 비활성화했습니다.');
  await loadAdmin();
});
window.changeMyPassword=safe(async function(id){
  if(!currentAdmin || Number(id)!==Number(currentAdmin.id)) return alert('본인 비밀번호만 변경할 수 있습니다.');
  const password=prompt('새 비밀번호를 입력하세요 (4자리 이상)', '');
  if(password===null) return;
  if(password.length<4) return alert('비밀번호는 4자리 이상입니다.');
  await api('/api/admins/'+id,{method:'PUT',body:{password}});
  toast('비밀번호를 변경했습니다.');
});
function openAdminEditModal(admin){
  return new Promise(resolve=>{
    const old=$('adminEditModal'); if(old) old.remove();
    const wrap=document.createElement('div');
    wrap.id='adminEditModal';
    wrap.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';
    wrap.innerHTML=`<div style="width:min(520px,96vw);background:#080808;border:1px solid rgba(212,175,55,.45);border-radius:18px;padding:24px;box-shadow:0 20px 80px rgba(0,0,0,.75);color:#f7e7b0;">
      <h3 style="margin:0 0 16px;color:#f5c542;">관리자 수정</h3>
      <p style="margin:0 0 16px;color:#bdb095;font-size:14px;">최고 관리자는 관리자명, 권한명, 메모, 비밀번호를 수정할 수 있습니다. 비밀번호를 비우면 기존 비밀번호가 유지됩니다.</p>
      <label style="display:block;margin:10px 0 6px;font-weight:700;">아이디</label>
      <input id="editUsername" value="${esc(admin.username||'')}" disabled style="width:100%;box-sizing:border-box;padding:13px;border-radius:12px;border:1px solid rgba(212,175,55,.35);background:#111;color:#aaa;">
      <label style="display:block;margin:10px 0 6px;font-weight:700;">관리자명</label>
      <input id="editName" value="${esc(admin.name||'관리자')}" style="width:100%;box-sizing:border-box;padding:13px;border-radius:12px;border:1px solid rgba(212,175,55,.5);background:#050505;color:white;">
      <label style="display:block;margin:10px 0 6px;font-weight:700;">관리자 권한</label>
      <select id="editRole" style="width:100%;box-sizing:border-box;padding:13px;border-radius:12px;border:1px solid rgba(212,175,55,.5);background:#050505;color:white;"><option value="일반관리자">일반관리자</option><option value="대표관리자">대표관리자</option></select>
      <label style="display:block;margin:10px 0 6px;font-weight:700;">새 비밀번호</label>
      <input id="editPassword" type="password" placeholder="변경하려면 4자리 이상 입력" autocomplete="new-password" style="width:100%;box-sizing:border-box;padding:13px;border-radius:12px;border:1px solid rgba(212,175,55,.5);background:#050505;color:white;">
      <label style="display:block;margin:10px 0 6px;font-weight:700;">메모</label>
      <input id="editMemo" value="${esc(admin.memo||'')}" style="width:100%;box-sizing:border-box;padding:13px;border-radius:12px;border:1px solid rgba(212,175,55,.5);background:#050505;color:white;">
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
        <button id="cancelAdminEdit" type="button">취소</button>
        <button id="saveAdminEdit" type="button" class="primary">수정 저장</button>
      </div>
    </div>`;
    document.body.appendChild(wrap);
    setValue('editRole', (String(admin.role||'').includes('대표') || String(admin.role||'').toLowerCase().includes('super') || String(admin.role||'').toLowerCase().includes('owner')) ? '대표관리자' : '일반관리자');
    const close=(value)=>{ wrap.remove(); resolve(value); };
    $('cancelAdminEdit').onclick=()=>close(null);
    wrap.addEventListener('click', e=>{ if(e.target===wrap) close(null); });
    $('saveAdminEdit').onclick=()=>{
      const password=$('editPassword').value.trim();
      if(password && password.length<4){ alert('비밀번호는 4자리 이상입니다.'); return; }
      const body={
        name:$('editName').value.trim() || '관리자',
        role:$('editRole').value.trim() || '전체권한',
        memo:$('editMemo').value.trim()
      };
      if(password) body.password=password;
      close(body);
    };
    setTimeout(()=>$('editName')?.focus(),50);
  });
}
window.editAdmin=safe(async function(id){
  const admins=await api('/api/admins');
  const a=admins.find(x=>Number(x.id)===Number(id));
  if(!a) return alert('관리자를 찾을 수 없습니다.');
  const self = currentAdmin && Number(id)===Number(currentAdmin.id);
  if(!currentAdmin?.is_super_admin){
    if(self) return changeMyPassword(id);
    return alert('일반 관리자는 다른 관리자를 수정할 수 없습니다.');
  }
  const body=await openAdminEditModal(a);
  if(!body) return;
  await api('/api/admins/'+id,{method:'PUT',body});
  toast('관리자 정보를 수정했습니다.');
  await loadAdmin();
});

function bind(){
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
  $('copyNums')?.addEventListener('click',()=>{navigator.clipboard?.writeText(currentCombos.map((a,i)=>`${i+1}. ${a.join(', ')}`).join('\n')); toast('번호를 복사했습니다.');});
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
  if(!window.__bbSmsExportDelegatedClickBound){
    window.__bbSmsExportDelegatedClickBound=true;
    document.addEventListener('click', function(e){
      const btn=e.target && e.target.closest ? e.target.closest('button') : null;
      if(!btn) return;
      const id=btn.id || '';
      if(id==='exportSmsCsvAll'){ e.preventDefault(); downloadSmsCsv('all'); return; }
      if(id==='exportSmsCsvSelected'){ e.preventDefault(); downloadSmsCsv('selected'); return; }
      if(id==='copySmsBulk'){ e.preventDefault(); copyBulkSmsText(); return; }
      if(id==='applyBulkTemplate'){ e.preventDefault(); applyBulkTemplateToPreview(); return; }
    });
  }
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

  // RC5.4 FIX: 관리자 모달 버튼은 onclick/직접 바인딩에 의존하지 않고
  // 버블 단계 이벤트 위임으로 처리한다. pointerdown preventDefault는 제거했다.
  if(!window.__bbAdminDelegatedClickBound){
    window.__bbAdminDelegatedClickBound=true;
    document.addEventListener('click', function(e){
      const btn=e.target && e.target.closest ? e.target.closest('button') : null;
      if(!btn) return;
      const id=btn.id || '';
      if(id==='openAdminModal'){
        e.preventDefault(); openAdminCreateModal(); return;
      }
      if(id==='closeAdminModal' || id==='cancelAdminModal'){
        e.preventDefault(); closeAdminCreateModal(); return;
      }
      if(id==='addAdmin'){
        e.preventDefault(); window.addAdmin ? window.addAdmin() : safe(addAdmin)(); return;
      }
      if(btn.classList && btn.classList.contains('admin-tab-btn')){
        e.preventDefault(); switchAdminPanel(btn.dataset.adminPanel || 'admins'); return;
      }
    });
    document.addEventListener('click', function(e){
      const modal=$('adminCreateModal');
      if(modal && modal.style.display!=='none' && e.target===modal) closeAdminCreateModal();
    });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeAdminCreateModal(); });
  }
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
