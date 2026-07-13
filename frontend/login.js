const $=id=>document.getElementById(id);
function getToken(){ return localStorage.getItem('bb_v34_token') || ''; }
async function checkExistingLogin(){
  const t=getToken();
  if(!t) return;
  try{
    const r=await fetch('/api/me',{headers:{Authorization:'Bearer '+t}});
    if(r.ok) location.href='/dashboard';
    else localStorage.removeItem('bb_v34_token');
  }catch(e){}
}
async function doLogin(){
  const msg=$('loginMsg');
  if(msg) msg.textContent='로그인 중...';
  try{
    const username=($('loginId')?.value||'').trim();
    const password=$('loginPw')?.value||'';
    if(!username || !password) throw new Error('아이디와 비밀번호를 입력하세요.');
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
    const text=await r.text();
    let d={};
    try{ d=text?JSON.parse(text):{}; }catch(e){ d={raw:text}; }
    if(!r.ok){
      const err=d.error || d.detail || d.raw || '로그인 실패';
      const emsg=(err && typeof err==='object') ? (err.message || JSON.stringify(err)) : String(err);
      throw new Error(emsg);
    }
    localStorage.setItem('bb_v34_token',d.token);
    location.href='/dashboard';
  }catch(e){ if(msg) msg.textContent='로그인 실패: '+(e.message||e); }
}
document.addEventListener('DOMContentLoaded',()=>{
  checkExistingLogin();
  $('loginBtn')?.addEventListener('click',doLogin);
  $('loginPw')?.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
  $('loginId')?.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});
});
