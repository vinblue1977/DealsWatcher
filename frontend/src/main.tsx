import { render } from 'preact';

import { App } from './App';
import { initApi } from './api';
import { addPasskeyUrl, currentEmail, initAuth, keepFresh, logout } from './auth';
import { loadConfig } from './config';
import './styles.css';

async function start(root: HTMLElement) {
  try {
    const config = await loadConfig();
    initApi(config);
    if (!(await initAuth(config))) return; // redirected to the sign-in page
    keepFresh();
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
