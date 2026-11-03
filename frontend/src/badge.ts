/** Clears the number on the app icon and the running total the service worker keeps (see public/sw.js). */
export function clearBadge(): void {
  void (navigator as { clearAppBadge?: () => Promise<void> }).clearAppBadge?.().catch(() => undefined);
  if (typeof caches !== 'undefined') void caches.delete('badge').catch(() => undefined);
}
