// Minimal offline service worker: cache the app shell + data, serve cache-first.
const CACHE = "mrf-v10";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./data/programs.json",
  "./data/museums.json",
  "./data/museums.sample.json",
  "./data/memberships.seed.json",
  "./data/zip_centroids.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Data is refreshed monthly: network-first so updates land, cache when offline.
  // zip_centroids.json is static (Census ZCTAs change ~yearly; bump CACHE when rebuilt),
  // so it falls through to cache-first below.
  const path = new URL(e.request.url).pathname;
  if (path.includes("/data/") && !path.endsWith("/zip_centroids.json")) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit ||
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          return res;
        })
        .catch(() => hit)
    )
  );
});
