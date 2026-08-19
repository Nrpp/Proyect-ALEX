// Service worker for the ALEX console PWA. Its only two jobs: turn a Web
// Push message into a real system notification (this is what makes
// notifications reach the phone even when the app isn't open - the "push"
// event fires the moment the OS wakes the worker, independent of any open
// tab), and take you back into the app when you tap one.
"use strict";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = { title: "ALEX", body: "" };
  try {
    if (event.data) payload = event.data.json();
  } catch (e) {
    payload.body = event.data ? event.data.text() : "";
  }

  const priority = payload.priority ?? 1;
  const options = {
    body: payload.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    tag: payload.id || undefined, // same id replaces rather than stacking
    requireInteraction: priority >= 2, // high/critical stay until dismissed
    vibrate: priority >= 2 ? [200, 100, 200] : [120],
    // The banner itself is truncated by the OS - deep-link back with the
    // notification id so the app can show the untruncated body on open.
    data: { url: "./?n=" + encodeURIComponent(payload.id || "") },
  };

  event.waitUntil(self.registration.showNotification(payload.title || "ALEX", options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = new URL(event.notification.data?.url || "./", self.registration.scope).href;

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url === targetUrl && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    }),
  );
});
