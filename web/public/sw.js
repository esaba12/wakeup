// OpenRestore PWA service worker. Caches the built app shell so the UI
// still opens (installed to a home screen, per docs/08-web-ui.md) without
// a network round-trip; it never caches `/api/*` — live device state must
// always come from a fresh WebSocket/REST call, never a stale cache
// pretending to be live (the same rule the "disconnected" banner exists
// to enforce in the UI itself).
//
// Two strategies, deliberately different:
//  - `/assets/*` (Vite's content-hashed JS/CSS — a rebuild changes the
//    filename) is genuinely immutable, so cache-first is correct and never
//    goes stale.
//  - everything else (`/`, the manifest, icons) is network-first with a
//    cache fallback: `index.html` itself is *not* hashed, so cache-first
//    here would mean a device that has ever loaded the app once keeps
//    serving yesterday's `index.html` — which still points at yesterday's
//    hashed JS bundle — forever, even after a rebuild ships a new one.
//    Only an offline device falls back to the cached shell.
const CACHE_NAME = "openrestore-shell-v2";
const SHELL_PATHS = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_PATHS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function cacheFirst(request) {
  return caches.match(request).then((cached) => {
    if (cached) return cached;
    return fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    });
  });
}

function networkFirst(request) {
  return fetch(request)
    .then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    })
    .catch(() => caches.match(request));
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return; // never intercept live device calls
  if (event.request.method !== "GET") return;

  const immutable = url.pathname.startsWith("/assets/");
  event.respondWith(immutable ? cacheFirst(event.request) : networkFirst(event.request));
});
