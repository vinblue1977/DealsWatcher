import { useEffect, useRef, useState } from 'preact/hooks';

import { STORE_PRICES_CHECKED } from './format';
import { disablePush, enablePush, pushState, testPush, type PushState } from './push';

const BELL = 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0';

type View = PushState | 'error';

const TEXT: Record<Exclude<View, 'error'>, { title: string; detail: string }> = {
  'needs-install': {
    title: 'Install the app to get alerts',
    detail: 'In Safari tap Share, then Add to Home Screen, and open DealsWatcher from the Home Screen. iPhones only send notifications to the installed app.',
  },
  unsupported: { title: 'Notifications are not available', detail: 'This browser cannot receive push notifications.' },
  blocked: { title: 'Notifications are blocked', detail: 'Turn them on in the iPhone Settings app, under Notifications, then come back.' },
  off: { title: 'Notifications are off', detail: STORE_PRICES_CHECKED ? 'Get a push alert when a price drops or a deal matches.' : 'Get a push alert when a deal matches one of your keywords.' },
  on: { title: 'Notifications are on', detail: 'This device' },
};

export function Notifications() {
  const [state, setState] = useState<View | null>(null);
  const [checkError, setCheckError] = useState(''); // why the status check failed
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState(''); // why the last tap failed
  const latest = useRef(0);

  /** Reads this device's state. Only the newest check may update the card, so a slow older one can't overwrite it. Returns whether it worked. */
  async function refresh(): Promise<boolean> {
    const mine = ++latest.current;
    try {
      const found = await pushState();
      if (mine === latest.current) setState(found);
      return true;
    } catch (e) {
      if (mine === latest.current) {
        setState('error');
        setCheckError((e as Error).message);
      }
      return false;
    }
  }

  useEffect(() => {
    void refresh();
    // Coming back from iOS Settings (or another device changed things): look again.
    const onVisible = () => document.visibilityState === 'visible' && void refresh();
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  async function run(action: () => Promise<void>, done: string) {
    setBusy(true);
    setError('');
    setMessage('');
    let failed = false;
    try {
      await action();
    } catch (e) {
      failed = true;
      setError((e as Error).message);
    } finally {
      const checked = await refresh();
      if (!failed && checked) setMessage(done);
      setBusy(false);
    }
  }

  const text = state === null ? { title: 'Notifications', detail: 'Checking…' } : state === 'error' ? { title: 'Could not check notifications', detail: checkError } : TEXT[state];
  return (
    <section class="group card-body">
      <div class="notify-head">
        <div class={state === 'on' ? 'icon good' : 'icon'}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d={BELL} />
          </svg>
        </div>
        <div class="grow">
          <div class="notify-title">{text.title}</div>
          <div class="muted small">{text.detail}</div>
        </div>
      </div>
      {state === 'error' && (
        <button class="button wide" type="button" onClick={() => void refresh()}>
          Try again
        </button>
      )}
      {state === 'off' && (
        <button class="button primary wide" type="button" disabled={busy} onClick={() => run(enablePush, 'Notifications are on.')}>
          Turn on notifications
        </button>
      )}
      {state === 'on' && (
        <div class="row">
          <button class="button grow-row" type="button" disabled={busy} onClick={() => run(testPush, 'Test sent to this device.')}>
            Send a test
          </button>
          <button class="button danger grow-row" type="button" disabled={busy} onClick={() => run(disablePush, 'Notifications are off.')}>
            Turn off
          </button>
        </div>
      )}
      {message && (
        <p class="muted small" role="status">
          {message}
        </p>
      )}
      {error && (
        <p class="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
