// Service worker: shows push notifications sent by the server and opens the app when one is tapped.
const MAX_TEXT = 200;

const text = (value, fallback) => (typeof value === 'string' && value.trim() ? value.trim().slice(0, MAX_TEXT) : fallback);

/** Only paths inside this app: anything else (another site, "//host", "javascript:") opens the home screen. */
const inAppPath = (value) => (typeof value === 'string' && /^\/(?!\/)[^\s\\]*$/.test(value) ? value : '/');

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // not JSON: show the default notification
  }
  if (data === null || typeof data !== 'object') data = {};
  event.waitUntil(
    self.registration.showNotification(text(data.title, 'DealsWatcher'), {
      body: text(data.body, ''),
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: inAppPath(data.url) },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = inAppPath(event.notification.data && event.notification.data.url);
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const mine = windows.filter((w) => new URL(w.url).origin === self.location.origin);
      const target = mine.find((w) => w.visibilityState === 'visible') ?? mine[0];
      try {
        if (!target) throw new Error('no open window');
        target.postMessage({ type: 'open', url }); // the app moves itself to the page: no reload, so typed input survives
        await target.focus();
      } catch {
        await self.clients.openWindow(url); // focus or navigate not allowed here: open the app fresh
      }
    })(),
  );
});
