// Service worker. In slice 1 it only makes the app installable; slice 2 adds the `push` and
// `notificationclick` handlers. Network only: offline mode is out of scope.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
