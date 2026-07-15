/* BBLOTTO RC6-B: full-history backtest report UI */
(function(){
'use strict';
let activeRun=null, stepBusy=false, resultPage=1;
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=(a,b)=>b?((Number(a||0)*100/Number(b)).toFixed(1)+'%'):'0.0%';
const rankLabel=r=>r||'낙첨';
function setBadge(text){if(el('backtestBadge'))el('backtestBadge').textContent=text;}
function setProgress(run){
  activeRun=run||activeRun;if(!activeRun)return;
  const total=Math.max(1,Number(activeRun.total_rounds||0)), done=Number(activeRun.processed_rounds||0), p=Math.min(100,done*100/total);
  if(el('backtestProgressBar'))el('backtestProgressBar').style.width=p.toFixed(2)+'%';
  if(el('backtestProgressText')){const validationStart=Number(activeRun.start_round||0),dataStart=validationStart>1?validationStart-1:validationStart;el('backtestProgressText').textContent=`전체 데이터 ${dataStart||'-'}~${activeRun.end_round||'-'}회 · 백테스트 검증 ${activeRun.start_round||'-'}~${activeRun.end_round||'-'}회 · ${done}/${total}회 처리 · 성공 ${activeRun.success_rounds||0} · 실패 ${activeRun.failed_rounds||0} · 상태 ${activeRun.status||'-'}`;}
  setBadge(activeRun.status==='completed'?'완료':activeRun.status==='running'?'실행 중':activeRun.status==='cancelled'?'중단':'대기');
}
async function loadRuns(){
  const d=await api('/api/backtest/runs?limit=1');
  activeRun=(d.items||[])[0]||null;
  if(!activeRun){setBadge('대기');return false;}
  setProgress(activeRun);await loadReport(activeRun.id);return true;
}
async function startRun(){
  if(stepBusy)return;
  const d=await api('/api/backtest/runs',{method:'POST',body:{combo_count:Number(el('backtestComboCount')?.value||10),mode:el('backtestMode')?.value||'balanced',min_history:1}});
  activeRun=d.run;resultPage=1;setProgress(activeRun);toast('전체 회차 백테스트를 시작했습니다.');await continueRun();
}
async function continueRun(){
  if(stepBusy)return;if(!activeRun){const ok=await loadRuns();if(!ok)return alert('먼저 새 분석을 시작해주세요.');}
  if(activeRun.status==='completed')return toast('이미 완료된 분석입니다.');
  stepBusy=true;toggleButtons(true);
  try{
    while(activeRun && !['completed','cancelled','failed'].includes(activeRun.status)){
      const d=await api(`/api/backtest/runs/${activeRun.id}/step?step_size=5`,{method:'POST'});
      activeRun=d.run;setProgress(activeRun);
      if(d.done)break;
      await new Promise(r=>setTimeout(r,80));
    }
    await loadReport(activeRun.id);toast(activeRun.status==='completed'?'전체 회차 분석이 완료됐습니다.':'백테스트 실행이 멈췄습니다.');
  }catch(e){alert(e.message||e);await refreshRun();}
  finally{stepBusy=false;toggleButtons(false);}
}
function toggleButtons(busy){['backtestStart','backtestContinue','backtestCancel'].forEach(id=>{if(el(id))el(id).disabled=busy;});}
async function cancelRun(){if(!activeRun)return;if(!confirm('현재 백테스트를 중단할까요? 저장된 결과는 유지됩니다.'))return;const d=await api(`/api/backtest/runs/${activeRun.id}/cancel`,{method:'POST'});activeRun=d.run;setProgress(activeRun);}
async function refreshRun(){if(!activeRun)return loadRuns();const d=await api(`/api/backtest/runs/${activeRun.id}`);activeRun=d.run;setProgress(activeRun);await loadReport(activeRun.id);}
function renderKpis(s){
  const rows=[['검증 회차',s.evaluated_rounds||0],['평균 최고 일치',Number(s.avg_best_match||0).toFixed(2)],['추천 풀 포함',Number(s.avg_pool_match||0).toFixed(2)+'/6'],['3개 이상',s.rounds_with_3plus||0],['4개 이상',s.rounds_with_4plus||0],['5개 이상',s.rounds_with_5plus||0]];
  el('backtestKpis').innerHTML=rows.map(x=>`<div class="stat"><b>${esc(x[1])}</b><span>${esc(x[0])}</span></div>`).join('');
}
function renderWindows(w){
  const labels={all:'전체','50':'최근 50회','100':'최근 100회','300':'최근 300회'};
  el('backtestWindows').innerHTML='<table><thead><tr><th>범위</th><th>회차</th><th>평균 최고일치</th><th>풀 포함</th><th>3+</th><th>4+</th><th>5+</th></tr></thead><tbody>'+Object.entries(w||{}).map(([k,v])=>`<tr><td>${labels[k]||k}</td><td>${v.evaluated_rounds||0}</td><td>${Number(v.avg_best_match||0).toFixed(2)}</td><td>${Number(v.avg_pool_match||0).toFixed(2)}</td><td>${v.rounds_with_3plus||0}</td><td>${v.rounds_with_4plus||0}</td><td>${v.rounds_with_5plus||0}</td></tr>`).join('')+'</tbody></table>';
}
function renderStrategies(s){
  const rows=Object.entries(s||{}).sort((a,b)=>Number(b[1].avg_match||0)-Number(a[1].avg_match||0));
  el('backtestStrategies').innerHTML=rows.length?'<table><thead><tr><th>전략</th><th>조합</th><th>평균 일치</th><th>3+</th><th>4+</th></tr></thead><tbody>'+rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v.combos||0}</td><td>${Number(v.avg_match||0).toFixed(3)}</td><td>${v.three_plus||0}</td><td>${v.four_plus||0}</td></tr>`).join('')+'</tbody></table>':'전략별 결과가 없습니다.';
}
function renderTrend(rows){
  if(!rows?.length){el('backtestTrend').textContent='성과 추이가 없습니다.';return;}
  const max=Math.max(1,...rows.map(x=>Number(x.avg_pool_match||0)));
  el('backtestTrend').innerHTML=rows.map(x=>{const h=Math.max(3,Math.round(Number(x.avg_pool_match||0)/max*125));return `<div class="backtest-trend-item" title="${esc(x.label)} · 평균 풀 포함 ${Number(x.avg_pool_match||0).toFixed(2)}"><div class="backtest-trend-bar"><i style="height:${h}px"></i></div><b>${Number(x.avg_pool_match||0).toFixed(2)}</b><small>${esc(x.label)}</small></div>`;}).join('');
}
async function loadResults(runId,page=1){
  resultPage=Math.max(1,page);const d=await api(`/api/backtest/runs/${runId}/results?page=${resultPage}&page_size=20`);
  const rows=d.items||[];
  el('backtestResults').innerHTML=rows.length?'<table><thead><tr><th>회차</th><th>당첨번호</th><th>최고일치</th><th>최고등수</th><th>풀 포함</th><th>생성시간</th></tr></thead><tbody>'+rows.map(x=>`<tr><td>${x.target_round}</td><td>${(x.winning_numbers||[]).join(' · ')}</td><td>${x.best_match||0}개</td><td>${esc(rankLabel(x.best_rank))}</td><td>${x.pool_match_count||0}/6</td><td>${Number(x.generation_ms||0).toFixed(0)}ms</td></tr>`).join('')+'</tbody></table>':'상세 결과가 없습니다.';
  const pages=Math.max(1,Math.ceil(Number(d.total||0)/20));el('backtestPager').innerHTML=`<button ${resultPage<=1?'disabled':''} data-bt-page="${resultPage-1}">이전</button><span>${resultPage} / ${pages}</span><button ${resultPage>=pages?'disabled':''} data-bt-page="${resultPage+1}">다음</button>`;
}
async function loadReport(runId){
  const d=await api(`/api/backtest/runs/${runId}/summary`);activeRun=d.run;setProgress(activeRun);renderKpis(d.summary||{});renderWindows(d.by_window||{});renderStrategies(d.by_strategy||{});renderTrend(d.trend_blocks||[]);await loadResults(runId,resultPage);
}
function bind(){
  el('backtestStart')?.addEventListener('click',()=>startRun().catch(e=>alert(e.message||e)));
  el('backtestContinue')?.addEventListener('click',()=>continueRun().catch(e=>alert(e.message||e)));
  el('backtestRefresh')?.addEventListener('click',()=>refreshRun().catch(e=>alert(e.message||e)));
  el('backtestCancel')?.addEventListener('click',()=>cancelRun().catch(e=>alert(e.message||e)));
  document.addEventListener('click',e=>{const b=e.target.closest?.('[data-bt-page]');if(b&&!b.disabled&&activeRun)loadResults(activeRun.id,Number(b.dataset.btPage||1)).catch(err=>alert(err.message||err));});
  document.querySelector('[data-admin-panel="adminBacktestPanel"]')?.addEventListener('click',()=>loadRuns().catch(e=>{console.error(e);el('backtestProgressText').textContent=e.message||e;}));
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
window.loadBacktestReport=loadRuns;
})();
