import { useState } from 'preact/hooks';

import { api } from './api';
import { parsePrice, retailerFor, STORE_NAMES } from './format';
import { go } from './router';

export function AddWatch() {
  const [url, setUrl] = useState('');
  const [target, setTarget] = useState('');
  const [alertOnDrop, setAlertOnDrop] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const store = retailerFor(url);
  const price = parsePrice(target);

  async function paste() {
    try {
      setUrl((await navigator.clipboard.readText()).trim());
    } catch {
      setError('Paste isn’t allowed here. Long-press the field and choose Paste.');
    }
  }

  async function submit(e: Event) {
    e.preventDefault();
    if (!store) return setError(`Use an https link from ${STORE_NAMES.join(', ')}.`);
    if (price === null) return setError('Enter the price you want, like 199 or 199.99.');
    setBusy(true);
    setError('');
    try {
      await api.addWatch({ url: url.trim(), targetPrice: price, alertOnDrop });
      go('watching');
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <form class="screen add" onSubmit={submit} noValidate>
      <header class="bar">
        <a class="link" href="#/">
          Cancel
        </a>
        <h1>Add watch</h1>
        <span class="spacer" />
      </header>

      <div class="field">
        <label for="url">Product link</label>
        <div class="row">
          <input id="url" type="url" inputMode="url" autoComplete="off" autoCapitalize="off" spellcheck={false} maxLength={1000} placeholder="https://www.target.com/p/…" value={url} onInput={(e) => setUrl(e.currentTarget.value)} />
          <button class="button" type="button" onClick={paste}>
            Paste
          </button>
        </div>
        <div class="muted small">{store ? `Found: ${store}` : `Works with ${STORE_NAMES.join(', ')}.`}</div>
      </div>

      <div class="field">
        <label for="target">Alert me at or below</label>
        <div class="money">
          <span aria-hidden="true">$</span>
          <input id="target" inputMode="decimal" autoComplete="off" maxLength={9} placeholder="199.00" value={target} onInput={(e) => setTarget(e.currentTarget.value)} />
        </div>
      </div>

      <div class="group">
        <div class="setting">
          <span id="drop-label">Also alert on drops of 10% or more</span>
          <button type="button" role="switch" aria-checked={alertOnDrop} aria-labelledby="drop-label" class={alertOnDrop ? 'switch on' : 'switch'} onClick={() => setAlertOnDrop(!alertOnDrop)}>
            <span class="knob" />
          </button>
        </div>
      </div>

      {error && (
        <p class="error" role="alert">
          {error}
        </p>
      )}
      <div class="footer">
        <button class="button primary wide" type="submit" disabled={busy}>
          {busy ? 'Adding…' : 'Start watching'}
        </button>
      </div>
    </form>
  );
}
