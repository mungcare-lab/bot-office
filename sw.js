/* AI OFFICE 서비스 워커 — 앱 껍데기만 캐시하고, 화면/데이터는 항상 네트워크를 우선한다.
 * scope: /bot-office/  ·  등록: src/main.tsx (navigator.serviceWorker.register('/bot-office/sw.js', { scope:'/bot-office/' }))
 * 규칙
 *  - 화면 이동(navigate): 네트워크 우선 → 실패 시 캐시된 index.html
 *  - 같은 출처 정적 자산: 캐시 우선 + 뒤에서 갱신(stale-while-revalidate)
 *  - Supabase·폰트 등 다른 출처: 절대 가로채지 않는다.
 *  - 새 버전: CACHE 이름을 올리고 activate 에서 이전 캐시를 지운다(구버전 화면 고착 방지).
 */
const VERSION = 'aioffice-v23-2026-11-27';
const SCOPE = '/bot-office/';
const SHELL = [`${SCOPE}`, `${SCOPE}index.html`, `${SCOPE}manifest.webmanifest`, `${SCOPE}icons/icon-192.png`];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      // 한 파일이 404여도 설치는 실패하지 않게 한다(설치 실패 = WebAPK 생성 실패).
      .then((cache) => cache.addAll(SHELL).catch(() => undefined))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // Supabase·외부 폰트 요청은 건드리지 않는다.
  if (!url.pathname.startsWith(SCOPE)) return;

  // 화면 이동은 네트워크 우선(새 배포가 바로 보이도록), 실패 시 캐시.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches
            .open(VERSION)
            .then((cache) => cache.put(`${SCOPE}index.html`, copy))
            .catch(() => undefined);
          return response;
        })
        .catch(() => caches.match(`${SCOPE}index.html`).then((hit) => hit || caches.match(SCOPE)).then((hit) => hit || Response.error())),
    );
    return;
  }

  // 해시가 붙은 정적 자산: 캐시 우선 + 뒤에서 갱신.
  event.respondWith(
    caches.match(request).then((hit) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches
              .open(VERSION)
              .then((cache) => cache.put(request, copy))
              .catch(() => undefined);
          }
          return response;
        })
        .catch(() => hit || Response.error());
      return hit || network;
    }),
  );
});
