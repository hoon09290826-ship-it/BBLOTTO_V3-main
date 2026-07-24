/* BBLOTTO RC7: AI LAB orphan recovery + complete button wiring */
(function(){
'use strict';
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let activeJob=null,busy=false,stopRequested=false;
const terminal=new Set(['completed','cancelled','failed','approved','candidates_ranked']);
const statusLabel={ready:'준비',running:'실행 중',paused:'일시정지',baseline_completed:'기준 측정 완료',candidates_ready:'후보 생성 완료',candidates_testing:'후보 비교 중',candidates_ranked:'후보 비교 완료',approved:'승인 완료',completed:'완료',cancelled:'중단',failed:'실패'};
const validId=v=>Number.isInteger(Number(v))&&Number(v)>0;
function normalizeJob(value){
 const source=value&&typeof value==='object'?(value.item||value.job||value.current_job||value.active_job||value):null;
 if(!source||typeof source!=='object')return null;
 const id=Number(source.id??source.job_id??source.jobId);
 if(!validId(id))return null;
 return {...source,id,job_id:id};
}
const isActive=j=>{const n=normalizeJob(j);return !!n&&!terminal.has(String(n.status||''));};
function currentJobId(action){
 const j=normalizeJob(activeJob);
 if(!j){syncButtons();alert(`${action||'작업'}할 유효한 학습 작업이 없습니다. 새로고침 후 다시 시도하세요.`);return null;}
 activeJob=j;return j.id;
}
function fmt(v,n=3){return Number(v||0).toFixed(n);}
function badge(v){if(el('aiLabBadge'))el('aiLabBadge').textContent=v;}
function setDisabled(id,v){const node=el(id);if(node)node.disabled=!!v;}
function syncButtons(){
 const s=String(activeJob?.status||'');
 setDisabled('aiLabCreateJob',busy||isActive(activeJob));
 setDisabled('aiLabRunBaseline',busy||!['ready','running'].includes(s));
 setDisabled('aiLabPauseJob',busy||s!=='running');
 setDisabled('aiLabResumeJob',busy||s!=='paused');
 setDisabled('aiLabCancelJob',busy||!isActive(activeJob));
 setDisabled('aiLabGenerateCandidates',busy||s!=='baseline_completed');
 setDisabled('aiLabCompareCandidates',busy||!['candidates_ready','candidates_testing'].includes(s));
 setDisabled('aiLabRefresh',busy);
}
function setBusy(v){busy=!!v;syncButtons();}
function progress(job){
 activeJob=normalizeJob(job);
 if(!activeJob){badge('대기');el('aiLabProgressText').textContent='실행 중인 연구가 없습니다.';el('aiLabProgressBar').style.width='0%';syncButtons();return;}
 const comparing=String(activeJob.status||'')==='candidates_testing';
 const p=Math.max(0,Math.min(100,Number(comparing?activeJob.candidate_progress_percent:(activeJob.progress_percent||0))));
 el('aiLabProgressBar').style.width=p+'%';
 const range=activeJob.range_type==='all'?'전체':activeJob.range_type==='recent500'?'최근 500회':'최근 300회';
 const err=activeJob.error_message?` · ${activeJob.error_message}`:'';
 const stage=activeJob.compare_stage==='precision'?'2차 상위 3개 정밀검증':'1차 최근 300회 선별';
 el('aiLabProgressText').textContent=comparing
  ? `작업 #${activeJob.id} · ${stage} · Candidate ${activeJob.candidate_completed_runs||0}/${activeJob.candidate_run_count||0}개 완료 · 검증 ${activeJob.candidate_processed_rounds||0}/${activeJob.candidate_total_rounds||0}회${err}`
  : `작업 #${activeJob.id} · ${range} · 고속 정밀 검증 · ${activeJob.processed_rounds||0}/${activeJob.target_rounds||0}회 · ${statusLabel[activeJob.status]||activeJob.status}${err}`;
 badge(statusLabel[activeJob.status]||activeJob.status||'대기');syncButtons();
}
function renderStable(item){if(!item||!Object.keys(item).length){el('aiLabStable').textContent='Stable 엔진 정보를 찾을 수 없습니다. 기존 기본 엔진으로 안전 동작합니다.';return;}const m=item.metrics||{};el('aiLabStable').innerHTML=`<div class="ai-lab-stable-card"><div><small>현재 운영 Stable</small><b>${esc(item.version_name||('#'+(item.version_id||item.id)))}</b><span>${esc(item.profile_name||'기본 프로필')}</span></div><div><small>엔진 코드</small><b>${esc(item.engine_code_version||'-')}</b><span>평균 최고일치 ${fmt(m.avg_best_match||m.score,2)}</span></div><div><small>상태</small><b class="positive">운영 중</b><span>관리자 승인 전 자동 변경 없음</span></div></div>`;}
function renderKpis(o){const c=o.counts||{};el('aiLabKpis').innerHTML=[['엔진 버전',c.versions||0],['가중치 프로필',c.profiles||0],['연구 작업',c.jobs||0],['연구노트',c.notes||0]].map(r=>`<div class="stat"><b>${esc(r[1])}</b><span>${esc(r[0])}</span></div>`).join('');}
function renderRankings(items){el('aiLabRankings').innerHTML=items?.length?'<table><thead><tr><th>순위</th><th>버전</th><th>점수</th><th>개선</th><th>상태</th><th></th></tr></thead><tbody>'+items.map(x=>`<tr><td>${x.rank||'-'}</td><td>${esc(x.version_name||('#'+x.version_id))}</td><td>${fmt(x.score,4)}</td><td>${Number(x.improvement)>0?'+':''}${fmt(x.improvement,4)}</td><td>${Number(x.improvement)>0&&x.rank===1?'승인 가능':'검증 완료'}</td><td>${Number(x.improvement)>0&&x.rank===1?`<button class="primary" data-ai-approve="${x.version_id}">Stable 승인</button>`:''}</td></tr>`).join('')+'</tbody></table>':'비교가 완료되면 Candidate 순위가 표시됩니다.';}
function renderVersions(items,stableId){el('aiLabVersions').innerHTML=items?.length?'<table><thead><tr><th>ID</th><th>버전</th><th>상태</th><th>프로필</th><th></th></tr></thead><tbody>'+items.slice(0,20).map(x=>`<tr><td>${x.id}</td><td>${esc(x.version_name||'-')}</td><td>${esc(x.status||'-')}</td><td>${x.profile_id||'-'}</td><td>${x.status==='retired'&&Number(x.id)!==Number(stableId)?`<button data-ai-rollback="${x.id}">롤백</button>`:''}</td></tr>`).join('')+'</tbody></table>':'버전 이력이 없습니다.';}
function renderActivations(items){el('aiLabActivations').innerHTML=items?.length?'<table><tbody>'+items.slice(0,20).map(x=>`<tr><td>${esc(x.created_at||'-')}</td><td>${x.action==='rollback'?'롤백':'승인'}</td><td>${esc(x.reason||'-')}</td></tr>`).join('')+'</tbody></table>':'승인·롤백 이력이 없습니다.';}
function renderNotes(items){el('aiLabNotes').innerHTML=items?.length?items.slice(0,30).map(x=>`<article><b>${esc(x.title||x.note_type||'연구 기록')}</b><small>${esc(x.created_at||'')}</small><p>${esc(x.body||'')}</p></article>`).join(''):'연구노트가 없습니다.';}
async function safeGet(url,fallback){try{return await api(url);}catch(e){console.error(url,e);return fallback;}}
async function loadAll(){
 setBusy(true);
 try{
  const [o,s,v,a,n,j,bt]=await Promise.all([
   safeGet('/api/ai-lab/overview',{counts:{},stable:{},active_job:null}),safeGet('/api/ai-lab/stable',{item:{}}),safeGet('/api/ai-lab/versions?limit=50',{items:[]}),safeGet('/api/ai-lab/activations?limit=50',{items:[]}),safeGet('/api/ai-lab/notes?limit=50',{items:[]}),safeGet('/api/ai-lab/jobs?limit=20',{items:[]}),safeGet('/api/ai-lab/backtest-link',{linked:false,item:{}})]);
  renderStable(s.item||o.stable);renderKpis(o);
  const link=bt?.item?.run||{};const linkSummary=bt?.item?.summary||{};const progressNode=el('aiLabProgressText');
  if(progressNode&&bt?.linked&&!activeJob){progressNode.textContent=`관리자 백테스트 #${link.id} 연동 · ${link.start_round||'-'}~${link.end_round||'-'}회 · 평균 최고일치 ${fmt(linkSummary.avg_best_match||0,2)} · AI LAB 작업 생성 시 기준정보로 저장됩니다.`;}
  const jobs=(Array.isArray(j.items)?j.items:[]).map(normalizeJob).filter(Boolean);activeJob=jobs.find(isActive)||normalizeJob(o.active_job)||jobs[0]||null;progress(activeJob);
  renderVersions(v.items||[],(s.item||{}).version_id||(o.stable||{}).id);renderActivations(a.items||[]);renderNotes(n.items||[]);
  if(normalizeJob(activeJob)){const r=await safeGet(`/api/ai-lab/jobs/${activeJob.id}/rankings`,{items:[]});renderRankings(r.items||[]);}else renderRankings([]);
  const recovered=[...(o.recovered_job_ids||[]),...(j.recovered_job_ids||[])];if(recovered.length)toast(`중단된 실행 작업 #${[...new Set(recovered)].join(', #')}을 자동 복구했습니다.`);
 }finally{setBusy(false);}
}
async function createJob(){const existing=normalizeJob(activeJob);if(isActive(existing))return alert(`완료되지 않은 작업 #${existing.id}을 먼저 완료하거나 중단하세요.`);const d=await api('/api/ai-lab/jobs',{method:'POST',body:{range_type:el('aiLabRange').value,candidate_limit:Number(el('aiLabCandidateLimit').value||6),random_seed:Date.now()%2147483647}});const created=normalizeJob(d);if(!created)throw new Error('서버가 유효한 작업 번호를 반환하지 않았습니다.');progress(created);toast('AI LAB 연구 작업을 생성했습니다.');}
async function runBaseline(){const jobId=currentJobId('기준 성능 측정');if(!jobId)return;stopRequested=false;setBusy(true);try{while(normalizeJob(activeJob)&&['ready','running'].includes(activeJob.status)&&!stopRequested){const d=await api(`/api/ai-lab/jobs/${jobId}/step?step_size=25`,{method:'POST'});progress(normalizeJob(d)||activeJob);if(d.busy){await sleep(350);continue;}if(d.done||d.paused)break;await sleep(10);}await loadAll();}finally{setBusy(false);}}
async function pauseJob(){if(normalizeJob(activeJob)?.status!=='running')return alert('실행 중인 작업만 일시정지할 수 있습니다.');const jobId=currentJobId('일시정지');if(!jobId)return;stopRequested=true;const d=await api(`/api/ai-lab/jobs/${jobId}/pause`,{method:'POST'});progress(normalizeJob(d));toast('일시정지했습니다.');}
async function resumeJob(){if(normalizeJob(activeJob)?.status!=='paused')return alert('일시정지된 작업이 없습니다.');const jobId=currentJobId('이어 실행');if(!jobId)return;const d=await api(`/api/ai-lab/jobs/${jobId}/resume`,{method:'POST'});progress(normalizeJob(d));await runBaseline();}
async function cancelJob(){const job=normalizeJob(activeJob);if(!isActive(job))return alert('중단할 진행 작업이 없습니다.');const jobId=currentJobId('중단');if(!jobId)return;if(!confirm(`작업 #${jobId}을 중단할까요? 운영 Stable 엔진은 변경되지 않습니다.`))return;stopRequested=true;const d=await api(`/api/ai-lab/jobs/${jobId}/cancel`,{method:'POST'});progress(normalizeJob(d));toast('작업을 중단했습니다.');await loadAll();}
async function generateCandidates(){if(normalizeJob(activeJob)?.status!=='baseline_completed')return alert('기준 성능 측정을 먼저 완료하세요.');const jobId=currentJobId('후보 생성');if(!jobId)return;const d=await api(`/api/ai-lab/jobs/${jobId}/generate-candidates`,{method:'POST'});toast(`Candidate ${d.created_count||d.count||0}개를 생성했습니다.`);await loadAll();}
async function compareCandidates(){if(!['candidates_ready','candidates_testing'].includes(normalizeJob(activeJob)?.status))return alert('후보 생성을 먼저 완료하세요.');const jobId=currentJobId('후보 비교');if(!jobId)return;setBusy(true);try{let done=false;while(!done){const d=await api(`/api/ai-lab/jobs/${jobId}/compare-step?step_size=25`,{method:'POST'});const job=normalizeJob(d.job)||activeJob;progress(job);if(d.busy){await sleep(350);continue;}done=!!d.done;await sleep(10);}await loadAll();}finally{setBusy(false);}}
async function approve(versionId){const jobId=currentJobId('Stable 승인');if(!jobId)return;const reason=prompt('Stable 승인 사유를 입력하세요.','백테스트 1위 후보 관리자 승인');if(reason===null)return;await api('/api/ai-lab/approve',{method:'POST',body:{job_id:jobId,version_id:Number(versionId),reason}});toast('새 Stable 엔진을 승인했습니다.');await loadAll();}
async function rollback(versionId){const reason=prompt('롤백 사유를 입력하세요.','이전 Stable 복원');if(reason===null)return;await api('/api/ai-lab/rollback',{method:'POST',body:{target_version_id:Number(versionId),reason}});toast('Stable 엔진을 롤백했습니다.');await loadAll();}
function bind(){
 [['aiLabCreateJob',createJob],['aiLabRunBaseline',runBaseline],['aiLabPauseJob',pauseJob],['aiLabResumeJob',resumeJob],['aiLabCancelJob',cancelJob],['aiLabGenerateCandidates',generateCandidates],['aiLabCompareCandidates',compareCandidates],['aiLabRefresh',loadAll]].forEach(([id,fn])=>el(id)?.addEventListener('click',()=>fn().catch(e=>alert(e.message||e))));
 document.addEventListener('click',e=>{const a=e.target.closest?.('[data-ai-approve]');if(a)approve(a.dataset.aiApprove).catch(err=>alert(err.message||err));const r=e.target.closest?.('[data-ai-rollback]');if(r)rollback(r.dataset.aiRollback).catch(err=>alert(err.message||err));});
 document.querySelector('[data-admin-panel="adminAiLabPanel"]')?.addEventListener('click',()=>loadAll().catch(e=>{el('aiLabProgressText').textContent=e.message||e;}));
 syncButtons();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
window.loadAiLabDashboard=loadAll;
})();
