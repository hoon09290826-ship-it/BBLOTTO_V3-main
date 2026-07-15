/* BBLOTTO V3 frontend split: js/20_stats_winning_views.js | original lines 861-1167 */
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
  const full=d.full_history||{};
  const fullOld=full.oldest_round||((d.round_range||[])[0])||0;
  const fullLatest=full.latest_round||d.latest_round||0;
  const fullCount=full.count||d.actual_count||0;
  const fullMissing=Number(full.missing_count ?? d.missing_rounds_count ?? 0);
  const invalidCount=Number(full.invalid_count ?? d.invalid_rows_count ?? 0);
  const complete=Boolean(full.is_complete ?? d.is_full_history);
  statsRecentDrawsCache=(d.recent_draws||[]);
  const freq=d.freq || d.freq100 || {};
  const maxFreq=Math.max(1, ...Object.values(freq).map(Number));
  const bars=Object.entries(freq).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,15).map(([n,c])=>`<div class="stats-bar"><b>${n}</b><div><i style="width:${Math.round(Number(c)/maxFreq*100)}%"></i></div><span>${c}회</span></div>`).join('');
  box.innerHTML=`<div class="stats-dashboard">
    <div class="stats-kpi">
      <div class="stat-card"><b>${d.count}</b><span>${d.range_label||'선택 범위'} 분석 회차</span></div>
      <div class="stat-card"><b>${d.sum_avg}</b><span>평균 합계</span></div>
      <div class="stat-card"><b>${d.odd}:${d.even}</b><span>홀짝 누적</span></div>
      <div class="stat-card"><b>${(d.sections||[]).join(' / ')}</b><span>구간 1~15 / 16~30 / 31~45</span></div>
    </div>
    <div class="detail-section full-history-status"><h4>통계 범위 및 전체 데이터 상태</h4><div class="history-range"><b>${d.analysis_confirm||'분석 상태 확인 중'}</b><span>${d.range_label||''}</span></div><div class="hint">전체 DB ${fullOld||'-'}회차~${fullLatest||'-'}회차 · 유효 ${fullCount.toLocaleString()}개 · 누락 ${fullMissing}개 · 비정상 ${invalidCount}개 · 전체이력 ${complete?'완료':'확인 필요'}</div></div>
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
  const box=$('statsBox');
  if(box) box.innerHTML='<div class="hint">통계를 계산하고 있습니다...</div>';
  const d=await api('/api/stats?limit='+encodeURIComponent(limit));
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


