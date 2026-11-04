import { render } from 'preact';

import { App } from './App';
import { initApi } from './api';
import { addPasskeyUrl, currentEmail, initAuth, keepFresh, logout } from './auth';
import { loadConfig } from './config';
import { clearBadge } from './badge';
import { initPush } from './push';
import { reloadIfNewer } from './version';
import './styles.css';

async function start(root: HTMLElement) {
  // Never leave the page empty: this shows while settings load and while the sign-in redirect is under way.
  render(
    <main class="screen">
      <p class="muted">Loading…</p>
    </main>,
    root,
  );
  try {
    const config = await loadConfig();
    initApi(config);
    initPush(config);
    if (!(await initAuth(config))) return; // redirected to the sign-in page
    keepFresh();
    clearBadge(); // the person is looking at the app: nothing is unseen
    addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      clearBadge();
      void reloadIfNewer(); // an app left open keeps its old code until it is reloaded
    });
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => undefined); // push is optional: the app works without it
      navigator.serviceWorker.addEventListener('message', (e) => {
        const url = (e.data as { type?: string; url?: unknown } | null)?.url;
        if ((e.data as { type?: string } | null)?.type === 'open' && typeof url === 'string') {
          location.hash = new URL(url, location.origin).hash || '#/';
          void reloadIfNewer(true); // a tapped notification brings an app that may be a deploy behind
        }
      });
    }
    render(<App email={currentEmail()} onSignOut={logout} passkeyUrl={addPasskeyUrl()} />, root);
  } catch (e) {
    render(
      <main class="screen">
        <p class="muted">{(e as Error).message || 'Something went wrong.'}</p>
      </main>,
      root,
    );
  }
}

// Coming back to a page the browser kept in memory (Back from the sign-in page, a restored Home Screen app) would show
// whatever was on screen when it was left, which can be nothing: start over instead.
addEventListener('pageshow', (e) => {
  if (e.persisted) location.reload();
});

const root = document.getElementById('app');
if (root) void start(root);
