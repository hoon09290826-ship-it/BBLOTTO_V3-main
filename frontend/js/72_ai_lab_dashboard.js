/* BBLOTTO RC6-D1 Stage 6: AI LAB administrator dashboard */
(function(){
'use strict';
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let activeJob=null,busy=false;
const terminalStatuses=new Set(['completed','cancelled','failed','approved']);
const unfinishedStatuses=new Set(['ready','running','paused','baseline_completed','candidates_generated','candidates_ranked']);
const statusLabel={ready:'준비',running:'실행 중',paused:'일시정지',baseline_completed:'기준 측정 완료',candidates_generated:'후보 생성 완료',candidates_ranked:'후보 비교 완료',approved:'승인 완료',completed:'완료',cancelled:'중단',failed:'실패'};
function badge(text){if(el('aiLabBadge'))el('aiLabBadge').textContent=text;}
function fmt(v,n=3){return Number(v||0).toFixed(n);}
function setBusy(v){busy=!!v;['aiLabCreateJob','aiLabRunBaseline','aiLabPauseJob','aiLabResumeJob','aiLabCancelJob','aiLabGenerateCandidates','aiLabCompareCandidates','aiLabRefresh'].forEach(id=>{if(el(id))el(id).disabled=busy;});updateControls();}
function updateControls(){
 const status=activeJob?.status||'';
 const unfinished=!!activeJob&&unfinishedStatuses.has(status);
 const pause=el('aiLabPauseJob'),resume=el('aiLabResumeJob'),cancel=el('aiLabCancelJob');
 if(pause)pause.hidden=!unfinished||!['ready','running'].includes(status);
 if(resume)resume.hidden=status!=='paused';
 if(cancel)cancel.hidden=!unfinished;
 if(el('aiLabCreateJob'))el('aiLabCreateJob').disabled=busy||unfinished;
 if(el('aiLabRunBaseline'))el('aiLabRunBaseline').disabled=busy||!activeJob||status==='paused'||terminalStatuses.has(status)||['baseline_completed','candidates_generated','candidates_ranked'].includes(status);
 if(el('aiLabGenerateCandidates'))el('aiLabGenerateCandidates').disabled=busy||!activeJob||!['baseline_completed','candidates_generated'].includes(status);
 if(el('aiLabCompareCandidates'))el('aiLabCompareCandidates').disabled=busy||!activeJob||!['candidates_generated','candidates_ranked'].includes(status);
}
function progress(job){activeJob=job||activeJob;if(!activeJob){badge('대기');el('aiLabProgressText').textContent='실행 중인 연구가 없습니다.';el('aiLabProgressBar').style.width='0%';updateControls();return;}
 const p=Math.max(0,Math.min(100,Number(activeJob.progress_percent||0)));el('aiLabProgressBar').style.width=p+'%';
 el('aiLabProgressText').textContent=`작업 #${activeJob.id} · ${activeJob.range_type||'-'} · ${activeJob.processed_rounds||0}/${activeJob.target_rounds||0}회 · ${statusLabel[activeJob.status]||activeJob.status}`;badge(statusLabel[activeJob.status]||activeJob.status||'대기');updateControls();}
function renderStable(item){if(!item||!Object.keys(item).length){el('aiLabStable').textContent='Stable 엔진 정보를 찾을 수 없습니다. 기존 기본 엔진으로 안전 동작합니다.';return;}
 const m=item.metrics||{};el('aiLabStable').innerHTML=`<div class="ai-lab-stable-card"><div><small>현재 운영 Stable</small><b>${esc(item.version_name||('#'+(item.version_id||item.id)))}</b><span>${esc(item.profile_name||'기본 프로필')}</span></div><div><small>엔진 코드</small><b>${esc(item.engine_code_version||'-')}</b><span>평균 최고일치 ${fmt(m.avg_best_match||m.score,2)}</span></div><div><small>상태</small><b class="positive">운영 중</b><span>자동 변경 금지</span></div></div>`;}
function renderKpis(o){const c=o.counts||{};const rows=[['엔진 버전',c.versions||0],['가중치 프로필',c.profiles||0],['연구 작업',c.jobs||0],['연구노트',c.notes||0]];el('aiLabKpis').innerHTML=rows.map(r=>`<div class="stat"><b>${esc(r[1])}</b><span>${esc(r[0])}</span></div>`).join('');}
function renderRankings(items){if(!items?.length){el('aiLabRankings').textContent='비교가 완료되면 Candidate 순위가 표시됩니다.';return;}
 el('aiLabRankings').innerHTML='<table><thead><tr><th>순위</th><th>버전</th><th>점수</th><th>개선</th><th>상태</th><th></th></tr></thead><tbody>'+items.map(x=>`<tr><td>${x.rank||'-'}</td><td>${esc(x.version_name||('#'+x.version_id))}</td><td>${fmt(x.score,4)}</td><td class="${Number(x.improvement)>0?'positive':'negative'}">${Number(x.improvement)>0?'+':''}${fmt(x.improvement,4)}</td><td>${Number(x.improvement)>0&&x.rank===1?'승인 가능':'검증 완료'}</td><td>${Number(x.improvement)>0&&x.rank===1?`<button class="primary" data-ai-approve="${x.version_id}">Stable 승인</button>`:''}</td></tr>`).join('')+'</tbody></table>';}
function renderVersions(items,stableId){if(!items?.length){el('aiLabVersions').textContent='버전 이력이 없습니다.';return;}
 el('aiLabVersions').innerHTML='<table><thead><tr><th>ID</th><th>버전</th><th>상태</th><th>프로필</th><th></th></tr></thead><tbody>'+items.slice(0,20).map(x=>`<tr><td>${x.id}</td><td>${esc(x.version_name||'-')}</td><td>${esc(x.status||'-')}</td><td>${x.profile_id||'-'}</td><td>${x.status==='retired'&&Number(x.id)!==Number(stableId)?`<button data-ai-rollback="${x.id}">롤백</button>`:''}</td></tr>`).join('')+'</tbody></table>';}
function renderActivations(items){el('aiLabActivations').innerHTML=items?.length?'<table><thead><tr><th>일시</th><th>작업</th><th>변경</th><th>사유</th></tr></thead><tbody>'+items.slice(0,20).map(x=>`<tr><td>${esc(x.created_at||'-')}</td><td>${x.action==='rollback'?'롤백':'승인'}</td><td>${esc(x.from_version_name||('#'+x.from_version_id))} → ${esc(x.to_version_name||('#'+x.to_version_id))}</td><td>${esc(x.reason||'-')}</td></tr>`).join('')+'</tbody></table>':'승인·롤백 이력이 없습니다.';}
function renderNotes(items){el('aiLabNotes').innerHTML=items?.length?items.slice(0,30).map(x=>`<article><b>${esc(x.title||x.note_type||'연구 기록')}</b><small>${esc(x.created_at||'')}</small><p>${esc(x.body||'')}</p></article>`).join(''):'연구노트가 없습니다.';}
async function loadAll(){setBusy(true);try{
 const [o,s,v,a,n,j]=await Promise.all([api('/api/ai-lab/overview'),api('/api/ai-lab/stable'),api('/api/ai-lab/versions?limit=50'),api('/api/ai-lab/activations?limit=50'),api('/api/ai-lab/notes?limit=50'),api('/api/ai-lab/jobs?limit=1')]);
 renderStable(s.item||o.stable);renderKpis(o);const jobs=j.items||[];activeJob=o.active_job||jobs.find(x=>unfinishedStatuses.has(x.status))||jobs[0]||null;progress(activeJob);renderVersions(v.items||[],(s.item||{}).version_id||(o.stable||{}).id);renderActivations(a.items||[]);renderNotes(n.items||[]);
 if(activeJob){try{const r=await api(`/api/ai-lab/jobs/${activeJob.id}/rankings`);renderRankings(r.items||[]);}catch(e){renderRankings([]);}}
 else renderRankings([]);
 }finally{setBusy(false);}}
async function createJob(){if(busy)return;if(activeJob&&unfinishedStatuses.has(activeJob.status))return alert(`완료되지 않은 학습 작업 #${activeJob.id}이 있습니다. 계속 진행하거나 작업 중단 후 새 연구를 시작하세요.`);const body={range_type:el('aiLabRange').value,candidate_limit:Number(el('aiLabCandidateLimit').value||6),random_seed:Date.now()%2147483647};const d=await api('/api/ai-lab/jobs',{method:'POST',body});activeJob=d.item;progress(activeJob);toast('AI LAB 연구 작업을 생성했습니다.');await loadAll();}
async function runBaseline(){if(!activeJob)return alert('먼저 새 연구를 시작하세요.');setBusy(true);try{while(activeJob&&!['baseline_completed','completed','failed','cancelled'].includes(activeJob.status)){const d=await api(`/api/ai-lab/jobs/${activeJob.id}/step?step_size=5`,{method:'POST'});activeJob=d.job||activeJob;progress(activeJob);if(d.done)break;await new Promise(r=>setTimeout(r,100));}toast('Stable 기준 성능 측정을 마쳤습니다.');await loadAll();}finally{setBusy(false);}}

async function pauseJob(){if(!activeJob||!['ready','running'].includes(activeJob.status))return;const d=await api(`/api/ai-lab/jobs/${activeJob.id}/pause`,{method:'POST'});activeJob=d.item||activeJob;progress(activeJob);toast(`작업 #${activeJob.id}을 일시정지했습니다.`);await loadAll();}
async function resumeJob(){if(!activeJob||activeJob.status!=='paused')return;const d=await api(`/api/ai-lab/jobs/${activeJob.id}/resume`,{method:'POST'});activeJob=d.item||activeJob;progress(activeJob);toast(`작업 #${activeJob.id}을 재개했습니다.`);await loadAll();}
async function cancelJob(){if(!activeJob||!unfinishedStatuses.has(activeJob.status))return;if(!confirm(`미완료 작업 #${activeJob.id}을 중단할까요?\n\n중단된 작업은 다시 실행할 수 없으며, 이후 새 연구를 시작할 수 있습니다. 운영 Stable 엔진은 변경되지 않습니다.`))return;setBusy(true);try{const d=await api(`/api/ai-lab/jobs/${activeJob.id}/cancel`,{method:'POST'});activeJob=d.item||activeJob;progress(activeJob);toast(`작업 #${activeJob.id}을 중단했습니다. 새 연구를 시작할 수 있습니다.`);await loadAll();}finally{setBusy(false);}}
async function generateCandidates(){if(!activeJob)return alert('먼저 연구 작업을 선택하세요.');if(!confirm('Stable 기준 가중치에서 Candidate 프로필을 생성할까요? 운영 엔진은 변경되지 않습니다.'))return;const d=await api(`/api/ai-lab/jobs/${activeJob.id}/generate-candidates`,{method:'POST'});toast(`Candidate ${d.created_count||d.count||0}개를 생성했습니다.`);await loadAll();}
async function compareCandidates(){if(!activeJob)return alert('먼저 연구 작업을 선택하세요.');setBusy(true);try{let done=false;while(!done){const d=await api(`/api/ai-lab/jobs/${activeJob.id}/compare-step?step_size=5`,{method:'POST'});activeJob=d.job||activeJob;progress(activeJob);done=!!d.done;await new Promise(r=>setTimeout(r,100));}toast('Candidate 비교와 순위 계산을 완료했습니다.');await loadAll();}finally{setBusy(false);}}
async function approve(versionId){if(!activeJob)return;const reason=prompt('Stable 승인 사유를 입력하세요.','백테스트 1위 후보 관리자 승인');if(reason===null)return;if(!confirm(`Candidate #${versionId}를 운영 Stable로 승인할까요? 기존 Stable은 롤백 가능 상태로 보존됩니다.`))return;await api('/api/ai-lab/approve',{method:'POST',body:{job_id:Number(activeJob.id),version_id:Number(versionId),reason}});toast('새 Stable 엔진을 승인했습니다.');await loadAll();}
async function rollback(versionId){const reason=prompt('롤백 사유를 입력하세요.','이전 Stable 복원');if(reason===null)return;if(!confirm(`엔진 버전 #${versionId}로 롤백할까요?`))return;await api('/api/ai-lab/rollback',{method:'POST',body:{target_version_id:Number(versionId),reason}});toast('Stable 엔진을 롤백했습니다.');await loadAll();}
function bind(){el('aiLabCreateJob')?.addEventListener('click',()=>createJob().catch(e=>alert(e.message||e)));el('aiLabRunBaseline')?.addEventListener('click',()=>runBaseline().catch(e=>alert(e.message||e)));el('aiLabPauseJob')?.addEventListener('click',()=>pauseJob().catch(e=>alert(e.message||e)));el('aiLabResumeJob')?.addEventListener('click',()=>resumeJob().catch(e=>alert(e.message||e)));el('aiLabCancelJob')?.addEventListener('click',()=>cancelJob().catch(e=>alert(e.message||e)));el('aiLabGenerateCandidates')?.addEventListener('click',()=>generateCandidates().catch(e=>alert(e.message||e)));el('aiLabCompareCandidates')?.addEventListener('click',()=>compareCandidates().catch(e=>alert(e.message||e)));el('aiLabRefresh')?.addEventListener('click',()=>loadAll().catch(e=>alert(e.message||e)));
 document.addEventListener('click',e=>{const a=e.target.closest?.('[data-ai-approve]');if(a)approve(a.dataset.aiApprove).catch(err=>alert(err.message||err));const r=e.target.closest?.('[data-ai-rollback]');if(r)rollback(r.dataset.aiRollback).catch(err=>alert(err.message||err));});
 document.querySelector('[data-admin-panel="adminAiLabPanel"]')?.addEventListener('click',()=>loadAll().catch(e=>{console.error(e);el('aiLabProgressText').textContent=e.message||e;}));}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
window.loadAiLabDashboard=loadAll;
})();
