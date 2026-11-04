import { useState } from 'preact/hooks';

import { api } from './api';
import { parsePrice } from './format';
import { go } from './router';
import { Switch } from './Switch';

export function AddProduct() {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [alertOnLow, setAlertOnLow] = useState(true);
  const [alertOnDrop, setAlertOnDrop] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const target = price.trim() === '' ? null : parsePrice(price);

  async function submit(e: Event) {
    e.preventDefault();
    if (name.trim() === '') return setError('Enter the product name.');
    if (price.trim() !== '' && target === null) return setError('Enter a price like 199 or 199.99, or leave it empty.');
    setBusy(true);
    setError('');
    try {
      const made = await api.addProduct({ name: name.trim(), targetPrice: target, alertOnLow, alertOnDrop: alertOnDrop && target !== null });
      go(`#/watch/${made.id}`);
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
        <h1>Track a product</h1>
        <span class="spacer" />
      </header>

      <div class="field">
        <label for="name">Product name</label>
        <input id="name" class="text" autoComplete="off" maxLength={60} placeholder="e.g. Sony WH-1000XM5" value={name} onInput={(e) => setName(e.currentTarget.value)} />
        <div class="muted small">Use the exact name: a deal must contain every word, in this order. Add -words to skip other models, e.g. XM5 -XM4.</div>
      </div>

      <div class="field">
        <label for="price">Price you want (optional)</label>
        <div class="money">
          <span aria-hidden="true">$</span>
          <input id="price" inputMode="decimal" autoComplete="off" maxLength={9} placeholder="none" value={price} onInput={(e) => setPrice(e.currentTarget.value)} />
        </div>
      </div>

      <div class="group">
        <Switch on={alertOnLow} label="Alert me on a new lowest price" onChange={setAlertOnLow} />
        <Switch on={alertOnDrop && target !== null} label="Alert me when it reaches my price" disabled={target === null} onChange={setAlertOnDrop} />
      </div>

      <p class="muted small">
        Prices come from deals Dealnews posts (its Best Buy, Walmart, Target and Costco feeds and the main feeds), not live shelf prices. A store with no deal shows “no deal
        seen”.
      </p>

      {error && (
        <p class="error" role="alert">
          {error}
        </p>
      )}
      <div class="footer">
        <button class="button primary wide" type="submit" disabled={busy}>
          {busy ? 'Starting…' : 'Start tracking'}
        </button>
      </div>
    </form>
  );
}
