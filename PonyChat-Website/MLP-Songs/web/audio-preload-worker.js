/* Retire the old audio cache for browsers that previously installed it. */
"use strict";

self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil((async () => {
  await self.clients.claim();
  await caches.delete("music-audio-preload-v1").catch(() => {});
  await self.registration.unregister();
})()));
