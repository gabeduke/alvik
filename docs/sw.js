/* Alvik Remote service worker.
 *
 * BUILD is stamped with the commit SHA by .github/workflows/pages.yml, so every deploy changes
 * this file's bytes and installed copies pick up the new version (see the update code in index.html).
 *
 *  - The app shell is precached so the remote opens with no wifi (Web Bluetooth doesn't need it).
 *  - Same-origin requests go to the network first, revalidating past GitHub Pages' max-age=600,
 *    and fall back to the cache when offline. Fresh responses refresh the cache.
 *  - A new version installs in the background and takes over at once.
 */
const BUILD = "__BUILD__";
const CACHE = "alvik-" + BUILD;
const SHELL = ["./", "manifest.webmanifest", "favicon.svg", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "no-cache" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("alvik-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function networkFirst(req) {
  return fetch(req, { cache: "no-cache" })
    .then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    })
    .catch(() =>
      caches.match(req, { ignoreSearch: true })
        .then((hit) => hit || (req.mode === "navigate" ? caches.match("./") : Response.error()))
    );
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(networkFirst(req));
});
