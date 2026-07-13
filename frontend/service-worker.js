const CACHE_NAME = 'bblotto-stable6-runtime-safety';
self.addEventListener('install', event => { self.skipWaiting(); });
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  // HTML/JS/CSS는 항상 서버 최신본을 사용합니다.
  const url = new URL(event.request.url);
  if (event.request.method === 'GET' && (url.pathname === '/dashboard' || url.pathname === '/' || /\.(js|css)$/.test(url.pathname))) {
    event.respondWith(fetch(event.request, {cache:'no-store'}));
  }
});
