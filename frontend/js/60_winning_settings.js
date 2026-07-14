/* BBLOTTO V3 frontend split: js/60_winning_settings.js | original lines 2131-2350 */
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

