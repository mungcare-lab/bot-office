/* AI OFFICE 서비스 워커 — 앱 껍데기만 캐시하고, 화면/데이터는 항상 네트워크를 우선한다.
 * scope: /bot-office/  ·  등록: src/main.tsx (navigator.serviceWorker.register('/bot-office/sw.js', { scope:'/bot-office/' }))
 *
 * 규칙
 *  - 화면 이동(navigate): 네트워크 우선 → 실패 시 캐시된 index.html
 *  - 같은 출처 정적 자산: 캐시 우선 + 뒤에서 갱신(stale-while-revalidate)
 *  - Supabase·폰트 등 다른 출처: 절대 가로채지 않는다.
 *  - 새 버전: CACHE 이름을 올리고 activate 에서 이전 캐시를 지운다(구버전 화면 고착 방지).
 *
 * 푸시(개발 지시서 #18500)
 *  - push: 제목·본문·아이콘·tag·data.url 로 알림을 띄운다(같은 tag 는 하나로 합쳐진다).
 *  - notificationclick: 이미 열린 앱 창이 있으면 포커스하며 해당 화면(?openBlogPost=…)으로 이동,
 *    없으면 새 창으로 그 주소를 연다.
 *  - pushsubscriptionchange: 브라우저가 구독을 갱신하면 새 구독으로 다시 등록한다.
 */
const VERSION = 'aioffice-v39-2026-11-27';
const SCOPE = '/bot-office/';
const SHELL = [`${SCOPE}`, `${SCOPE}index.html`, `${SCOPE}manifest.webmanifest`, `${SCOPE}icons/icon-192.png`];
/** 공개 값(VAPID). 개인키는 서버 시크릿에만 있다. */
const VAPID_PUBLIC_KEY =
  'BNdiPUa_NyeL5H9dzRpT5pOoe1FyOni8rn7CPLGTjbp9UaO86BQhtWtmnBrzSYOtOrHPLJoRQ4N5K5xol3ItM1k';

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

/* ---------------------------------------------------------------- 푸시 알림 */

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    try {
      data = { title: 'AI OFFICE', body: event.data ? event.data.text() : '' };
    } catch {
      data = {};
    }
  }
  const title = data.title || 'AI OFFICE';
  const options = {
    body: data.body || '',
    icon: `${SCOPE}icons/icon-192.png`,
    badge: `${SCOPE}icons/icon-192.png`,
    tag: data.tag || 'aioffice',
    renotify: true,
    data: { url: data.url || SCOPE, event: data.event || '' },
    requireInteraction: Boolean(data.requireInteraction),
    vibrate: [80, 40, 80],
    lang: 'ko-KR',
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // 서버는 '/?openBlogPost=…' 처럼 앱 안 경로만 보낸다. 그대로 new URL('/?…', scope) 하면
  // 사이트 루트(https://<user>.github.io/)로 가 버리므로, 반드시 앱 경로(/bot-office/)를 붙인다.
  const raw = (event.notification.data && event.notification.data.url) || '/';
  const normalized = raw.startsWith('/') ? SCOPE + raw.slice(1) : raw;
  let target;
  try {
    target = new URL(normalized, self.registration.scope).href;
  } catch {
    target = self.registration.scope;
  }
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const mine = windows.find((client) => client.url.startsWith(self.registration.scope));
      if (mine) {
        try {
          await mine.focus();
        } catch {
          /* 포커스 실패해도 이동은 시도한다 */
        }
        try {
          await mine.navigate(target);
        } catch {
          await self.clients.openWindow(target);
        }
        return;
      }
      await self.clients.openWindow(target);
    })(),
  );
});

self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    (async () => {
      try {
        const applicationServerKey = Uint8Array.from(
          atob(VAPID_PUBLIC_KEY.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(VAPID_PUBLIC_KEY.length / 4) * 4, '=')),
          (c) => c.charCodeAt(0),
        );
        const sub = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
        const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of windows) {
          client.postMessage({ type: 'aioffice:push-resubscribed', subscription: sub.toJSON() });
        }
      } catch {
        /* 다음 앱 실행 때 다시 시도된다 */
      }
    })(),
  );
});
