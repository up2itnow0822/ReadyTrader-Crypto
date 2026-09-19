/**
 * Self-unregistering stub.
 *
 * The dashboard has no push routes, and approving a trade from a notification without
 * seeing it first would be unsafe -- so this app does not run a service worker. This
 * file exists only to clean up any earlier version of the SW a browser may have
 * installed: on activate, it clears every cache this origin created, unregisters
 * itself, and reloads any open clients so they stop being controlled by it.
 */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
      await self.registration.unregister();

      const clientsList = await self.clients.matchAll({ type: "window" });
      for (const client of clientsList) {
        client.navigate(client.url);
      }
    })()
  );
});
