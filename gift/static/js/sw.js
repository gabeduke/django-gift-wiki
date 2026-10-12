/* Wikileet service worker.
 *
 * Served from /sw.js by gift.views.service_worker, which prepends
 * SW_VERSION, OFFLINE_URL and PRECACHE_URLS so this file can stay static.
 *
 * What it does, deliberately little:
 *   - Pages always come from the network. Wishlists show what other people
 *     have bought, so a stale cached page could spoil or double-buy a gift.
 *     When the network is gone, navigations fall back to a friendly offline
 *     page instead of the browser's dinosaur.
 *   - Our own static files are served from cache. Versioned URLs (?v=<hash>)
 *     never change content, so they're cache-first; anything else is shown
 *     from cache and refreshed in the background.
 *   - Everything else (JSON endpoints, POSTs, auth, other origins) is left
 *     alone entirely.
 */
/* global SW_VERSION, OFFLINE_URL, PRECACHE_URLS */
'use strict';

var CACHE = 'wikileet-' + SW_VERSION;

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE)
      .then(function (cache) { return cache.addAll([OFFLINE_URL].concat(PRECACHE_URLS)); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.filter(function (key) {
          return key.indexOf('wikileet-') === 0 && key !== CACHE;
        }).map(function (key) { return caches.delete(key); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

function isStatic(url) {
  return url.origin === self.location.origin && url.pathname.indexOf('/static/') === 0;
}

function fromCacheFirst(request) {
  return caches.open(CACHE).then(function (cache) {
    return cache.match(request).then(function (hit) {
      return hit || fetch(request).then(function (response) {
        if (response.ok) { cache.put(request, response.clone()); }
        return response;
      });
    });
  });
}

function staleWhileRevalidate(request) {
  return caches.open(CACHE).then(function (cache) {
    return cache.match(request).then(function (hit) {
      var refresh = fetch(request).then(function (response) {
        if (response.ok) { cache.put(request, response.clone()); }
        return response;
      });
      if (hit) {
        refresh.catch(function () {});  // offline: the cached copy already answered
        return hit;
      }
      return refresh;
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  var url = new URL(request.url);
  if (isStatic(url)) {
    event.respondWith(
      url.searchParams.has('v') ? fromCacheFirst(request) : staleWhileRevalidate(request)
    );
  }
});
