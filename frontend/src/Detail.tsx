import { useEffect, useState } from 'preact/hooks';

import { api, ApiError } from './api';
import { NO_CHECKER_NOTE, STORE_PRICES_CHECKED, ago, money, parseName, parsePrice, retailerFor, targetMoney, watchState } from './format';
import { Switch } from './Switch';
import { go } from './router';
import type { Watch, WatchPatch } from './types';

export function Detail({ id }: { id: string }) {
  const [watch, setWatch] = useState<Watch | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState('');
  const [name, setName] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api.watch(id).then(
      (found) => {
        if (!live) return;
        setWatch(found);
        setTarget(String(found.targetPrice));
        setName(found.title);
      },
      (e: Error) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError(e.message);
      },
    );
    return () => {
      live = false;
    };
  }, [id, attempt]);

  async function change(patch: WatchPatch) {
    setBusy(true);
    setError('');
    try {
      const updated = await api.editWatch(id, patch);
      setWatch(updated);
      if (patch.targetPrice !== undefined) setTarget(String(updated.targetPrice)); // other changes keep a half-typed target
      if (patch.title !== undefined) setName(updated.title); // the name field is disabled while saving, so nothing typed is lost
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
      await api.deleteWatch(id);
      go('#/');
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const back = (
    <a class="back" href="#/">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M15 18l-6-6 6-6" />
      </svg>
      Watching
    </a>
  );

  if (missing) {
    return (
      <main class="screen">
        <header class="top">{back}</header>
        <section class="empty">
          <p>This watch no longer exists.</p>
        </section>
      </main>
    );
  }
  if (!watch) {
    return (
      <main class="screen">
        <header class="top">{back}</header>
        {error ? (
          <div class="notice" role="alert">
            <span>{error}</span>
            <button class="button" type="button" onClick={() => { setError(''); setAttempt(attempt + 1); }}>
              Retry
            </button>
          </div>
        ) : (
          <p class="muted">Loading…</p>
        )}
      </main>
    );
  }

  const state = watchState(watch);
  const newTarget = parsePrice(target);
  const targetChanged = newTarget !== null && newTarget !== watch.targetPrice;
  const newName = parseName(name);
  const nameChanged = newName !== null && newName !== watch.title;
  const productLink = retailerFor(watch.url) ? watch.url : null; // only ever link to a store we recognise

  return (
    <main class="screen">
      <header class="top">
        {back}
        {productLink && (
          <a class="link" href={productLink} target="_blank" rel="noopener noreferrer">
            Open at {watch.retailer}
          </a>
        )}
      </header>

      <div>
        <h1 class="small-title">{watch.title}</h1>
        <div class="muted">{watch.lastChecked ? `${watch.retailer} · checked ${ago(watch.lastChecked)}` : watch.retailer}</div>
      </div>

      <div class="hero">
        <div class={watch.lastPrice === undefined ? 'big faint' : 'big'}>{watch.lastPrice === undefined ? '—' : money(watch.lastPrice)}</div>
        <span class={`pill ${state.tone}`}>{state.label}</span>
      </div>
      {state.noChecker && <p class="muted small">{NO_CHECKER_NOTE}</p>}

      {watch.lowestPrice !== undefined && (
        <div class="stats">
          <div class="stat">
            <div class="muted small">Lowest seen</div>
            <div class="amount">{money(watch.lowestPrice)}</div>
          </div>
        </div>
      )}

      <form class="field" onSubmit={(e) => { e.preventDefault(); if (!busy && nameChanged) void change({ title: newName }); }}>
        <label for="name">Name</label>
        <div class="row">
          <input id="name" autoComplete="off" maxLength={240} disabled={busy} value={name} onInput={(e) => setName(e.currentTarget.value)} />
          <button class="button primary" type="submit" aria-label="Save name" disabled={busy || !nameChanged}>
            Save
          </button>
        </div>
        {newName === null && <div class="muted small">Enter a name up to 120 characters.</div>}
      </form>

      <form class="field" onSubmit={(e) => { e.preventDefault(); if (!busy && targetChanged && newTarget !== null) void change({ targetPrice: newTarget }); }}>
        <label for="target">Alert me at or below</label>
        <div class="row">
          <div class="money grow-row">
            <span aria-hidden="true">$</span>
            <input id="target" inputMode="decimal" autoComplete="off" maxLength={9} value={target} onInput={(e) => setTarget(e.currentTarget.value)} />
          </div>
          <button class="button primary" type="submit" aria-label="Save price limit" disabled={busy || !targetChanged}>
            Save
          </button>
        </div>
        <div class="muted small">{newTarget === null ? 'Enter a price like 199 or 199.99.' : `Currently ${targetMoney(watch.targetPrice)}.`}</div>
      </form>

      <div class="group">
        <Switch on={watch.alertOnDrop} label="Also alert on drops of 10% or more" disabled={busy} onChange={(on) => change({ alertOnDrop: on })} />
        {(STORE_PRICES_CHECKED || watch.paused) && <Switch on={!watch.paused} label="Checking this product" disabled={busy} onChange={(on) => change({ paused: !on })} />}
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
          Delete watch
        </button>
      )}
    </main>
  );
}
