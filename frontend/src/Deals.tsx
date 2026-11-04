import { useEffect, useRef, useState } from 'preact/hooks';

import { api } from './api';
import { CheckerLine } from './CheckerLine';
import { ago, money, safeLink, sourceName } from './format';
import { markSeen, unseenIds } from './seen';
import type { Deal, Source } from './types';

const MAX_DEALS = 100; // what the API returns

function Card({ deal, fresh }: { deal: Deal; fresh: boolean }) {
  const link = safeLink(deal.url); // feed links are untrusted: https only
  const body = (
    <>
      <div class="deal-head">
        <div class="title wrap">
          {fresh && <span class="new">New</span>}
          {deal.title ?? 'Deal'}
        </div>
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
  const [onlyNew, setOnlyNew] = useState(false);
  const [keyword, setKeyword] = useState('all');
  const [maxPrice, setMaxPrice] = useState('');
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const ids = useRef<string[]>([]);

  // Deals are marked seen when the person leaves, so "New" stays visible for the whole visit.
  useEffect(() => {
    const save = () => markSeen(ids.current);
    addEventListener('pagehide', save);
    return () => {
      removeEventListener('pagehide', save);
      save();
    };
  }, []);

  useEffect(() => {
    let live = true;
    api.deals().then(
      (found) => {
        if (!live) return;
        if (ids.current.length === 0) setFresh(unseenIds(found.map((d) => d.id))); // a retry or refresh keeps the first answer
        ids.current = found.map((d) => d.id);
        setDeals(found);
        setError('');
      },
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
  const keywordList = [...new Set((deals ?? []).flatMap((d) => (d.keyword ? [d.keyword] : [])))];
  const limit = maxPrice.trim() === '' ? null : Number(maxPrice);
  const priceLimit = limit !== null && Number.isFinite(limit) && limit >= 0 ? limit : null;
  const shown = (deals ?? []).filter(
    (d) =>
      (source === 'all' || d.source === source) &&
      (keyword === 'all' || d.keyword === keyword) &&
      (!onlyNew || fresh.has(d.id)) &&
      (priceLimit === null || (typeof d.price === 'number' && d.price <= priceLimit)), // a deal with no price can't be under a limit
  );
  const filtered = source !== 'all' || keyword !== 'all' || onlyNew || priceLimit !== null;
  const markAllSeen = () => {
    markSeen(ids.current);
    setFresh(new Set());
    setOnlyNew(false);
  };
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

      {deals && fresh.size > 0 && (
        <div class="chips">
          <button type="button" class={onlyNew ? 'chip on' : 'chip'} aria-pressed={onlyNew} onClick={() => setOnlyNew(!onlyNew)}>
            New ({fresh.size})
          </button>
          <button type="button" class="textbutton" onClick={markAllSeen}>
            Mark all as seen
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

      {deals && deals.length > 0 && (keywordList.length > 1 || deals.some((d) => typeof d.price === 'number')) && (
        <div class="filters">
          {keywordList.length > 1 && (
            <select class="select" aria-label="Keyword" value={keyword} onChange={(e) => setKeyword(e.currentTarget.value)}>
              <option value="all">All keywords</option>
              {keywordList.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          )}
          <input class="select" type="number" inputMode="decimal" min="0" placeholder="Max price" aria-label="Max price" value={maxPrice} onInput={(e) => setMaxPrice(e.currentTarget.value)} />
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
      {deals && deals.length > 0 && shown.length === 0 && (
        <p class="muted center">
          {filtered ? 'No deals match these filters.' : 'Nothing in the latest deals.'}{' '}
          {filtered && (
            <button
              type="button"
              class="textbutton"
              onClick={() => {
                setSource('all');
                setKeyword('all');
                setOnlyNew(false);
                setMaxPrice('');
              }}
            >
              Clear filters
            </button>
          )}
        </p>
      )}
      <ul class="list">
        {shown.map((d) => (
          <Card key={d.id} deal={d} fresh={fresh.has(d.id)} />
        ))}
      </ul>
      {deals && deals.length >= MAX_DEALS && <p class="muted small center">Showing the latest {MAX_DEALS} deals.</p>}
    </main>
  );
}
