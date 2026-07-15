(function(){
  function pct(v){ return `${Number(v||0).toFixed(1)}%`; }
  function num(v,d=2){ return Number(v||0).toFixed(d); }
  function strategyRows(items){
    if(!Array.isArray(items) || !items.length) return '<p class="hint">평가 가능한 추천 이력이 없습니다.</p>';
    return `<div class="member-analysis-bars">${items.map(item=>{
      const width=Math.max(3, Math.min(100, Number(item.three_plus_rate||0)));
      const adjust=Number(item.adaptive_adjustment||0);
      return `<div class="member-analysis-row"><div><b>${esc(item.strategy)}</b><small>${item.combo_samples}조합 · 평균 ${num(item.avg_match)}개 · 3개 이상 ${pct(item.three_plus_rate)}</small></div><div class="member-analysis-bar"><span style="width:${width}%"></span></div><strong class="${adjust>0?'positive':adjust<0?'negative':''}">${adjust>=0?'+':''}${num(adjust)}점</strong></div>`;
    }).join('')}</div>`;
  }
  function timeline(items){
    if(!Array.isArray(items) || !items.length) return '<p class="hint">회차별 분석 결과가 없습니다.</p>';
    const rows=items.slice(-20);
    const max=Math.max(1,...rows.map(x=>Number(x.pool_match_count||0)));
    return `<div class="member-analysis-timeline">${rows.map(x=>`<div title="${x.round_no}회 · 최고 ${x.best_match}개 · 추천풀 ${x.pool_match_count}개"><span style="height:${Math.max(8, Number(x.pool_match_count||0)/max*100)}%"></span><small>${x.round_no}</small></div>`).join('')}</div>`;
  }
  async function loadMemberAnalysis(memberId){
    const host=document.getElementById('memberAdaptiveAnalysis');
    if(!host) return;
    host.innerHTML='<p class="hint">회원별 추천 이력을 분석하고 있습니다.</p>';
    try{
      const d=await api(`/api/members/${memberId}/recommendation-analysis`);
      const enabled=!!d.enabled;
      host.innerHTML=`
        <div class="member-analysis-head"><div><b>${enabled?'개인화 반영 활성':'개인화 대기'}</b><small>평가 ${d.evaluated_runs||0}회 · ${d.evaluated_combos||0}조합 · 신뢰도 ${pct(Number(d.confidence||0)*100)}</small></div><span class="chip ${enabled?'active':''}">${enabled?`다음 생성에 최대 ${d.safety?.member_history_share||0}% 반영`:`${d.minimum_runs||20}회부터 반영`}</span></div>
        <div class="member-analysis-kpis"><div><b>${num(d.overall?.avg_match)}</b><span>평균 일치</span></div><div><b>${pct(d.overall?.three_plus_rate)}</b><span>3개 이상</span></div><div><b>${pct(d.overall?.four_plus_rate)}</b><span>4개 이상</span></div><div><b>${esc(d.best_strategy||'균형형')}</b><span>상대 우수 스타일</span></div></div>
        <h5>스타일별 실제 결과와 다음 생성 보정</h5>${strategyRows(d.strategies)}
        <h5>최근 회차 추천풀 포함 추이</h5>${timeline(d.timeline)}
        <p class="hint">회원별 결과는 특정 번호 재사용에 쓰지 않고, 전략과 조합 구조에만 제한적으로 반영됩니다. 공통 엔진 비중은 최소 90%로 유지됩니다.</p>`;
    }catch(e){ host.innerHTML=`<p class="hint">회원 분석을 불러오지 못했습니다: ${esc(e.message||e)}</p>`; }
  }
  const original=window.detailMember;
  if(typeof original==='function'){
    window.detailMember=async function(id){
      const result=await original(id);
      const body=document.getElementById('memberDetailPageBody');
      if(body && !document.getElementById('memberAdaptiveAnalysis')){
        const section=document.createElement('div');
        section.className='detail-section member-adaptive-section';
        section.innerHTML='<h4>회원별 추천 이력 분석 · 다음 추천 반영</h4><div id="memberAdaptiveAnalysis"></div>';
        const winning=body.querySelector('.rc43-winning');
        if(winning) body.insertBefore(section, winning); else body.appendChild(section);
      }
      await loadMemberAnalysis(id);
      return result;
    };
  }
})();
