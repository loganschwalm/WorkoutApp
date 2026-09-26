// Caches the app's own files so the pages survive a reload with no connection.
//
// This only covers the shell: HTML, CSS, JS and icons. Workout data is not cached
// here, because offline.js already keeps it on the device and syncs it back. The
// two must not both own that job, so every /api/ request is left alone.
//
// Every request goes to the network first, so a deploy reaches the next load without
// bumping anything (unless that load's network is too slow; see NETWORK_WAIT). Bump VERSION only to drop old caches, e.g. when PRECACHE changes.
const VERSION = 'v6';
const CACHE = `workout-tracker-${VERSION}`;

// Files that are the same for everyone, so they are safe to fetch at install time.
// The signed-in pages are deliberately absent: fetching index.html while signed out
// answers 303 to the login page, and caching that would lock the user out of their
// own app. They are cached once a real load succeeds instead.
const PRECACHE = [
  '/styles.css',
  '/pwa.js',
  '/theme.js',
  '/common.js',
  '/settings.js',
  '/offline.js',
  '/program-definitions.js',
  '/program.js',
  '/script.js',
  '/history.js',
  '/progress.js',
  '/login.js',
  '/login.html',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
];

// Pages worth having offline, warmed after activation while the session cookie is live.
const PAGES = ['/index.html', '/history.html', '/progress.html'];

// One cache entry per page, so /index.html?start=12 does not pile up copies of the shell,
// and / shares the entry of /index.html, which is the page it serves.
const pageKey = (url) => url.origin + (url.pathname === '/' ? '/index.html' : url.pathname);

// A 303 to the login page reaches a navigation as an opaque redirect, which the browser
// has to follow itself and which must never be stored.
const storable = (response) =>
  response && response.ok && !response.redirected && response.type !== 'opaqueredirect';

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(PRECACHE);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name)));
    await self.clients.claim();
    await warmPages();
  })());
});

// Signed in, these succeed and the app works offline from the first visit. Signed out,
// each one redirects and is skipped, and the next real load caches them instead.
async function warmPages() {
  const cache = await caches.open(CACHE);
  await Promise.all(PAGES.map(async (path) => {
    try {
      const response = await fetch(path, { credentials: 'same-origin' });
      if (storable(response)) await cache.put(pageKey(new URL(path, self.location.origin)), response);
    } catch (error) {
      // Offline at activation time; the page gets cached on its next successful load.
    }
  }));
}

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return; // offline.js owns the data layer

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(event, request, pageKey(url), true));
    return;
  }
  event.respondWith(networkFirst(event, request, request, false));
});

// How long the network gets before a cached copy is used instead. A connection that stalls
// rather than fails (a basement gym) would otherwise hold the page until the browser gives up,
// which can take minutes.
const NETWORK_WAIT = 3000;

// Pages and assets alike go to the network first, and the cache is only there for when
// the network is gone or too slow to wait for. Serving assets from the cache first would
// pair freshly deployed HTML with the previous deploy's JavaScript for one load. The server
// answers an unchanged file with a 304, so asking every time costs little on a home network.
async function networkFirst(event, request, key, isPage) {
  const cache = await caches.open(CACHE);
  const network = fetch(request).then((response) => {
    if (storable(response)) event.waitUntil(cache.put(key, response.clone()));
    return response;
  });
  // Keeps the worker alive until the network answers, so an answer that arrives after the
  // cached copy was used still refreshes the cache for next time.
  event.waitUntil(network.catch(() => {}));
  // Only this request's own copy: when it has none, waiting on the network beats the shell.
  const cachedAfterWait = new Promise((resolve) => setTimeout(resolve, NETWORK_WAIT))
    .then(() => cache.match(key))
    .then((cached) => cached || network);
  try {
    return await Promise.race([network, cachedAfterWait]);
  } catch (error) {
    const cached = await cache.match(key);
    if (cached) return cached;
    if (isPage) {
      const shell = await cache.match(pageKey(new URL('/index.html', self.location.origin)));
      if (shell) return shell;
    }
    throw error;
  }
}
