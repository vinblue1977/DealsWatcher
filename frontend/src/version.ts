const BUNDLE = /<script[^>]*\ssrc="(\/assets\/index-[^"]+\.js)"/;
const CHECK_EVERY_MS = 60_000;

/** The app bundle named in a page's HTML (its file name changes with every build), or null when there is none. */
export function bundleIn(html: string): string | null {
  return BUNDLE.exec(html)?.[1] ?? null;
}

/** True when the page at `/` now points at a different bundle than the one running: a newer build was deployed. */
export function isStale(running: string | null, html: string): boolean {
  const latest = bundleIn(html);
  return running !== null && latest !== null && latest !== running;
}

let lastCheck = 0;

/** Reloads the app when a newer build is out. An app left open keeps running the old code (nothing reloads it), so this is
 * run when a notification opens it and when it comes back to the front. Never while a field is being typed in, at most once
 * a minute (unless `force`, for a tapped notification), and any failure (offline, say) just keeps the current version. */
export async function reloadIfNewer(force = false, now = Date.now()): Promise<void> {
  if (!force && now - lastCheck < CHECK_EVERY_MS) return;
  lastCheck = now;
  const running = bundleIn(document.documentElement.outerHTML);
  if (running === null) return; // a dev server or test page: nothing to compare
  try {
    const page = await fetch('/', { cache: 'no-store' });
    if (!page.ok || !isStale(running, await page.text())) return;
    const typing = document.activeElement instanceof HTMLInputElement || document.activeElement instanceof HTMLTextAreaElement;
    if (!typing) location.reload();
  } catch {
    // offline or blocked: keep what is running
  }
}
