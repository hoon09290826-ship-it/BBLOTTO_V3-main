/* BBLOTTO V3 frontend split: js/00_core.js | original lines 1-615 */
/* BBLOTTO V3 STABLE CORE - single event owner: app.js */
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
    document.documentElement.dataset.bblottoUi='stable-core-1';
  }
  window.addEventListener('error',function(event){
    console.error('[BBLOTTO STABLE CORE]',event.error||event.message);
  });
  window.addEventListener('unhandledrejection',function(event){
    console.error('[BBLOTTO STABLE CORE PROMISE]',event.reason);
  });
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',prepareUi,{once:true});
  else prepareUi();
  window.BBLOTTO_STABLE_CORE='1.0.0';
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
let currentEngine = {};
let currentRound = '';
let nextGenerationRound = 0;
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
let adminCache = [];
let sessionWatchTimer = null;
let sessionWarned = false;
const WORKSPACE_KEY = 'bb_v50_workspace_state';

function saveWorkspaceState(){
  try{
    const state = {
      currentCombos, currentDetails, currentSms, currentAnalysis, currentRecommendationAnalysis, currentEngine, currentRound, currentRecId,
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
    currentEngine = (st.currentEngine && typeof st.currentEngine === 'object') ? st.currentEngine : {};
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
    currentEngine = (d.engine && typeof d.engine === 'object') ? d.engine : (()=>{ try{return JSON.parse(d.engine_json||'{}')}catch(_){return {}} })();
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
  const g = memberGradeLabel(d?.member_grade || d?.grade || currentEngine?.member_grade || '일반');
  return g === '1등' ? '🥇 1등' : (g === '2등' ? '🥈 2등' : '⭐ 일반');
}
function engineLabel(d){
  const g = memberGradeLabel(d?.member_grade || d?.grade || currentEngine?.member_grade || '일반');
  return d?.engine_label || currentEngine?.engine_label || (g === '1등' ? 'AI MASTER' : (g === '2등' ? 'AI PREMIUM' : 'AI BASIC'));
}
function displayScoreOf(d){ const v=d?.display_score ?? d?.score ?? d?.vip_score ?? d?.ai_score ?? 0; const n=Number(v); return Number.isFinite(n)?n:0; }
function starLabel(d){ const s=displayScoreOf(d); return s>=95?'★★★★★':(s>=90?'★★★★☆':(s>=85?'★★★★':(s>=80?'★★★☆':'★★★'))); }
function qualityLabel(d){ return d?.quality_grade || (displayScoreOf(d)>=95?'S+':(displayScoreOf(d)>=90?'S':(displayScoreOf(d)>=85?'A+':(displayScoreOf(d)>=80?'A':'B')))); }
function top3FromDetails(sets, details=[]){ return (sets||[]).map((nums,i)=>({nums, detail:details[i]||{}, idx:i+1})).sort((a,b)=>displayScoreOf(b.detail)-displayScoreOf(a.detail)).slice(0,3); }
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
    if(value.display_score || value.score || value.ai_score || value.avg_score) parts.push(`AI SCORE ${value.display_score || value.score || value.ai_score || value.avg_score}`);
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
  return '안녕하세요 {회원명}님, BBLOTTO입니다.\n\n{회차}회차 추천번호 안내드립니다.\n\n[추천번호]\n{추천번호}\n\n[이번 회차 핵심 분석]\n{분석}\n\n좋은 결과 있으시길 바랍니다.\n\n발송일: {발송일}';
}
function getBestAiScore(){
  const scores = (currentDetails || []).map(d=>displayScoreOf(d)).filter(Boolean);
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
  const panel = $('memberMessagePanel');
  if(panel) panel.classList.add('mobile-open');
  const target = panel || $('smsPreview') || $('comboList');
  if(target) setTimeout(()=>target.scrollIntoView({behavior:'smooth', block:'center'}), 150);
}

function scrollToRecommendationResults(){
  const panel = $('memberMessagePanel');
  if(panel) panel.classList.remove('mobile-open');
  const target = document.querySelector('#generator .result-box') || $('comboList');
  if(target) setTimeout(()=>target.scrollIntoView({behavior:'smooth', block:'start'}), 120);
}


function renderCombos(sets, details=[]){
  const box=$('comboList'); if(!box) return;
  if(!sets || !sets.length){
    box.classList.add('empty');
    box.innerHTML='추천번호를 생성하면 카드형 결과가 표시됩니다.';
    return;
  }
  box.classList.remove('empty');
  const cards = sets.map((arr,i)=>{
    const d = details[i] || {};
    const score = (d.display_score ?? d.score ?? d.vip_score ?? d.ai_score ?? '');
    const sum = d.sum ?? arr.reduce((a,b)=>a+Number(b),0);
    const odd = d.odd ?? arr.filter(n=>Number(n)%2).length;
    const even = d.even ?? (6-odd);
    const zones = d.zones || [arr.filter(n=>n<=15).length, arr.filter(n=>n>=16&&n<=30).length, arr.filter(n=>n>=31).length];
    const tags = d.tags || d.reasons || [];
    const grade = `${gradeLabel(d)} · ${engineLabel(d)} · 품질 ${qualityLabel(d)}`;
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
  box.innerHTML = `<div class="combo-card-grid">${cards}</div>`;
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
  return `안녕하세요 ${name}님, BBLOTTO입니다.\n\n${round || '-'}회차 추천번호 안내드립니다.\n\n[추천번호]\n${numbers}\n\n[이번 회차 핵심 분석]\n${analysisText}\n\n좋은 결과 있으시길 바랍니다.\n\n발송일: ${today}`;
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
  const scores = details.map(d=>displayScoreOf(d)).filter(Boolean);
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
