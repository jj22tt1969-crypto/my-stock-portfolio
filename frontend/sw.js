// QUANT AI PORTFOLIO Service Worker (PWA Realtime Network-First Version)
const CACHE_NAME = 'quant-ai-pwa-v1.0.8_pwa_final';

// 1. 설치 시 즉시 스킵 (skipWaiting)
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

// 3. fetch 요청 시 API 요청(/api/)은 항상 네트워크 최신 응답(Network-First/Bypass), 정적 자원도 최신 우선
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // API 요청(주가, 수급, 환율, AI 분석, Forward Test 등)은 절대 캐시에서 읽지 않고 네트워크 직송
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(fetch(event.request));
        return;
    }

    // 일반 정적 자원은 네트워크 응답 우선, 오프라인일 때만 캐시 사용
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});
