import type { ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';

import { api } from './api';
import { ago, byStore, money, parsePrice, productState, safeLink, targetMoney } from './format';
import { go } from './router';
import { Switch } from './Switch';
import type { Product, ProductPatch } from './types';

/** A tracked product: the lowest price seen, the lowest at each store, and every recorded price (from deals the feeds listed). */
export function ProductDetail({ product, back, onChange }: { product: Product; back: ComponentChildren; onChange: (p: Product) => void }) {
  const [price, setPrice] = useState(product.targetPrice === null ? '' : String(product.targetPrice));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState(false);

  const sightings = product.sightings ?? [];
  const state = productState(product);
  const typed = price.trim() === '' ? null : parsePrice(price);
  const valid = price.trim() === '' || typed !== null;
  const changed = valid && typed !== product.targetPrice;

  async function change(patch: ProductPatch) {
    setBusy(true);
    setError('');
    try {
      const updated = await api.editProduct(product.id, patch);
      onChange({ ...updated, sightings: product.sightings }); // the answer to a change has no sightings: keep the ones shown
      if (patch.targetPrice !== undefined) setPrice(updated.targetPrice === null ? '' : String(updated.targetPrice));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError('');
    try {
      await api.deleteWatch(product.id);
      go('#/');
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <main class="screen">
      <header class="top">{back}</header>

      <div>
        <h1 class="small-title">{product.title}</h1>
        <div class="muted small">Prices come from deals the feeds list, not live store prices.</div>
      </div>

      <div class="hero">
        <div class={product.lowestPrice === undefined ? 'big faint' : 'big best'}>{product.lowestPrice === undefined ? '—' : money(product.lowestPrice)}</div>
        <div>
          <span class={`pill ${state.tone}`}>{state.label}</span>
          {product.lowestPrice !== undefined && (
            <span class="muted small">
              {' '}
              {[product.lowestRetailer, product.lowestAt ? ago(product.lowestAt) : ''].filter(Boolean).join(' · ')}
            </span>
          )}
        </div>
      </div>

      <div class="stats two">
        {product.targetPrice !== null && (
          <div class="stat">
            <div class="muted small">Your price</div>
            <div class="amount">{targetMoney(product.targetPrice)}</div>
          </div>
        )}
        <div class="stat">
          <div class="muted small">Seen (90 days)</div>
          <div class="amount">{sightings.length === 1 ? '1 deal' : `${sightings.length} deals`}</div>
        </div>
      </div>

      <div class="sec">By store · lowest seen</div>
      <div class="card col">
        {byStore(sightings).map((row, i) => (
          <div class="store" key={row.store}>
            <span class="n">{row.store}</span>
            {row.price === null ? <span class="muted">no deal seen</span> : <span class={i === 0 ? 'amount best' : 'amount'}>{money(row.price)}</span>}
          </div>
        ))}
      </div>

      {sightings.length > 0 && (
        <>
          <div class="sec">Sightings</div>
          <div class="card col">
            {sightings.map((s) => {
              const link = safeLink(s.url);
              const row = (
                <>
                  <span>
                    {[s.retailer, ago(s.publishedAt)].filter(Boolean).join(' · ')}
                    {s.newLow && <span class="low">New low</span>}
                  </span>
                  <span class="amount">{money(s.price)}</span>
                </>
              );
              return link ? (
                <a class="hist" key={s.id} href={link} target="_blank" rel="noopener noreferrer">
                  {row}
                </a>
              ) : (
                <div class="hist" key={s.id}>
                  {row}
                </div>
              );
            })}
          </div>
          <p class="muted small center">Tap a sighting to open the deal.</p>
        </>
      )}

      <form
        class="field"
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy && changed) void change({ targetPrice: typed });
        }}
      >
        <label for="price">Price you want (optional)</label>
        <div class="row">
          <div class="money grow-row">
            <span aria-hidden="true">$</span>
            <input id="price" inputMode="decimal" autoComplete="off" maxLength={9} placeholder="none" value={price} onInput={(e) => setPrice(e.currentTarget.value)} />
          </div>
          <button class="button primary" type="submit" aria-label="Save price" disabled={busy || !changed}>
            Save
          </button>
        </div>
        <div class="muted small">{valid ? 'Leave it empty to just track the lowest price.' : 'Enter a price like 199 or 199.99.'}</div>
      </form>

      <div class="group">
        <Switch on={product.alertOnLow} label="Alert me on a new lowest price" disabled={busy} onChange={(on) => change({ alertOnLow: on })} />
        <Switch
          on={product.alertOnDrop && product.targetPrice !== null}
          label="Alert me when it reaches my price"
          disabled={busy || product.targetPrice === null}
          onChange={(on) => change({ alertOnDrop: on })}
        />
        <Switch on={!product.paused} label="Tracking this product" disabled={busy} onChange={(on) => change({ paused: !on })} />
      </div>

      {error && (
        <p class="error" role="alert">
          {error}
        </p>
      )}

      {confirming ? (
        <div class="row">
          <button class="button grow-row" type="button" disabled={busy} onClick={() => setConfirming(false)}>
            Keep it
          </button>
          <button class="button danger grow-row" type="button" disabled={busy} onClick={remove}>
            Delete
          </button>
        </div>
      ) : (
        <button class="button danger wide" type="button" onClick={() => setConfirming(true)}>
          Stop tracking
        </button>
      )}
    </main>
  );
}
