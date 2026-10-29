import { render } from 'preact';

import { App } from './App';
import { initApi } from './api';
import { addPasskeyUrl, currentEmail, initAuth, keepFresh, logout } from './auth';
import { loadConfig } from './config';
import { initPush } from './push';
import './styles.css';

async function start(root: HTMLElement) {
  try {
    const config = await loadConfig();
    initApi(config);
    initPush(config);
    if (!(await initAuth(config))) return; // redirected to the sign-in page
    keepFresh();
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => undefined); // push is optional: the app works without it
      navigator.serviceWorker.addEventListener('message', (e) => {
        const url = (e.data as { type?: string; url?: unknown } | null)?.url;
        if ((e.data as { type?: string } | null)?.type === 'open' && typeof url === 'string') location.hash = new URL(url, location.origin).hash || '#/';
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

const root = document.getElementById('app');
if (root) void start(root);
