// QUANT AI PORTFOLIO Service Worker (No-Cache Bypass Version)
const CACHE_NAME = 'quant-ai-pwa-v1.0.5_sugub_btn';

// 1. 설치 시 즉시 스킵
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// 2. 활성화 시 이전 모든 구버전 캐시 전면 강제 삭제 (Purge All Caches)
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    console.log('[ServiceWorker] Force deleting old cache:', cacheName);
                    return caches.delete(cacheName);
                })
            );
        }).then(() => self.clients.claim())
    );
});

// 3. fetch 요청 시 캐시를 전면 무시하고 최신 서버 응답 직송
self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});
