import { useEffect, useState } from 'preact/hooks';

import { api } from './api';
import { initials, money, stateOf, summary, targetMoney, visibleWatches, watchState, NO_CHECKER_NOTE, type WatchFilter } from './format';
import { isProduct, type Watch } from './types';

function Card({ watch }: { watch: Watch }) {
  const state = stateOf(watch);
  const product = isProduct(watch);
  const price = product ? watch.lowestPrice : watch.lastPrice; // a product shows the lowest price seen
  const store = product ? (watch.lowestRetailer ?? '') : watch.retailer;
  const target = watch.targetPrice === null ? 'No price set' : `Target ${targetMoney(watch.targetPrice)}`;
  return (
    <li>
      <a class="card" href={`#/watch/${watch.id}`}>
      <div class="badge">{store ? initials(store) : '·'}</div>
      <div class="grow">
        <div class="title">{product ? watch.name : watch.title}</div>
        <span class={`pill ${state.tone}`}>{state.label}</span>
      </div>
      <div class="price">
        <div class={price === undefined ? 'amount faint' : 'amount'}>{price === undefined ? '—' : money(price)}</div>
        <div class="muted small">{target}</div>
      </div>
      </a>
    </li>
  );
}

export function Watching() {
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<WatchFilter>('all');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api.watches().then(
      (found) => live && (setWatches(found), setError('')),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  const shown = visibleWatches(watches ?? [], filter);
  const chips: [WatchFilter, string][] = [
    ['all', `All ${watches?.length ?? 0}`],
    ['target', 'At target'],
    ['attention', 'Needs attention'],
  ];

  return (
    <main class="screen">
      <header class="top">
        <div>
          <h1>Watching</h1>
          <div class="muted">{watches ? summary(watches) : ' '}</div>
        </div>
        <a class="fab" href="#/add" aria-label="Track a product">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </a>
      </header>

      {error && (
        <div class="notice" role="alert">
          <span>{error}</span>
          <button class="button" type="button" onClick={() => setAttempt(attempt + 1)}>
            Retry
          </button>
        </div>
      )}

      {watches && watches.length > 0 && (
        <div class="chips">
          {chips.map(([id, label]) => (
            <button type="button" class={filter === id ? 'chip on' : 'chip'} aria-pressed={filter === id} onClick={() => setFilter(id)}>
              {label}
            </button>
          ))}
        </div>
      )}

      {watches && watches.length === 0 && (
        <section class="empty">
          <p>No products tracked yet.</p>
          <p class="muted">Track a product by name and you'll get a push notification on a new lowest price, or when it reaches your price.</p>
          <a class="button primary" href="#/add">
            Track a product
          </a>
        </section>
      )}
      {watches?.some((w) => !isProduct(w) && watchState(w).noChecker) && <p class="muted small">{NO_CHECKER_NOTE}</p>}
      {watches && watches.length > 0 && shown.length === 0 && <p class="muted center">Nothing matches this filter.</p>}
      <ul class="list">
        {shown.map((w) => (
          <Card key={w.id} watch={w} />
        ))}
      </ul>
    </main>
  );
}
