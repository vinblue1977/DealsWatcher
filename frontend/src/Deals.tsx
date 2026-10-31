import { useEffect, useState } from 'preact/hooks';

import { api } from './api';
import { CheckerLine } from './CheckerLine';
import { ago, money, safeLink, sourceName } from './format';
import type { Deal, Source } from './types';

const MAX_DEALS = 100; // what the API returns

function Card({ deal }: { deal: Deal }) {
  const link = safeLink(deal.url); // feed links are untrusted: https only
  const body = (
    <>
      <div class="deal-head">
        <div class="title wrap">{deal.title ?? 'Deal'}</div>
        {typeof deal.price === 'number' && <div class="deal-price">{money(deal.price)}</div>}
      </div>
      <div class="deal-meta muted small">
        {deal.keyword && <span class="tag">{deal.keyword}</span>}
        <span>{[deal.retailer, sourceName(deal.source), deal.publishedAt ? ago(deal.publishedAt) : ''].filter(Boolean).join(' · ')}</span>
      </div>
    </>
  );
  return (
    <li>
      {link ? (
        <a class="card block" href={link} target="_blank" rel="noopener noreferrer">
          {body}
        </a>
      ) : (
        <div class="card block">{body}</div>
      )}
    </li>
  );
}

export function Deals() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [keywords, setKeywords] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [source, setSource] = useState<Source | 'all'>('all');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api.deals().then(
      (found) => live && (setDeals(found), setError('')),
      (e: Error) => live && setError(e.message),
    );
    // The keyword count is a nicety: if it fails the deals still show.
    api.rules().then(
      (rules) => live && setKeywords(rules.filter((r) => r.enabled).length),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  const sources = [...new Set((deals ?? []).flatMap((d) => (d.source ? [d.source] : [])))]; // only feeds that have deals
  const shown = (deals ?? []).filter((d) => source === 'all' || d.source === source);
  return (
    <main class="screen">
      <header>
        <h1>Deals</h1>
        <div class="muted">{keywords === null ? ' ' : `Matches for your ${keywords} active ${keywords === 1 ? 'keyword' : 'keywords'}`}</div>
        <CheckerLine />
      </header>

      {error && (
        <div class="notice" role="alert">
          <span>{error}</span>
          <button class="button" type="button" onClick={() => setAttempt(attempt + 1)}>
            Retry
          </button>
        </div>
      )}

      {deals && sources.length > 1 && (
        <div class="chips">
          {(['all', ...sources] as const).map((id) => (
            <button key={id} type="button" class={source === id ? 'chip on' : 'chip'} aria-pressed={source === id} onClick={() => setSource(id)}>
              {id === 'all' ? 'All' : sourceName(id)}
            </button>
          ))}
        </div>
      )}

      {deals && deals.length === 0 && (
        <section class="empty">
          <p>No deals yet.</p>
          <p class="muted">Deals that match your keywords show up here.</p>
          <a class="button" href="#/keywords">
            Edit keywords
          </a>
        </section>
      )}
      {deals && deals.length > 0 && shown.length === 0 && <p class="muted center">Nothing from this feed in the latest deals.</p>}
      <ul class="list">
        {shown.map((d) => (
          <Card key={d.id} deal={d} />
        ))}
      </ul>
      {deals && deals.length >= MAX_DEALS && <p class="muted small center">Showing the latest {MAX_DEALS} deals.</p>}
    </main>
  );
}
