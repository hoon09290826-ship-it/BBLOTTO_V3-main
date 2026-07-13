(function(){
  'use strict';
  function ready(){
    document.querySelectorAll('button').forEach(function(b){if(!b.hasAttribute('type')) b.type='button';});
    var modal=document.getElementById('adminCreateModal');
    if(modal && !modal.classList.contains('is-open')){
      modal.style.display='none'; modal.setAttribute('aria-hidden','true');
    }
    document.documentElement.dataset.bblottoUi='stable5';
  }
  window.addEventListener('error',function(e){console.error('[STABLE-5 UI]',e.error||e.message);});
  window.addEventListener('unhandledrejection',function(e){console.error('[STABLE-5 PROMISE]',e.reason);});
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',ready,{once:true}); else ready();
  // 앱 이벤트를 가로채지 않는다. 모든 클릭은 app.js의 단일 bind()가 담당한다.
  window.BBLOTTO_STABLE_UI='STABLE-5.0';
})();
