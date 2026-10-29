import { useEffect, useState } from 'preact/hooks';

import { api, ApiError } from './api';
import { parsePrice, ruleLine } from './format';
import { SwitchButton } from './Switch';
import type { Rule } from './types';

export function Keywords() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [word, setWord] = useState('');
  const [max, setMax] = useState('');
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api.rules().then(
      (found) => live && (setRules(found), setLoadError('')),
      (e: Error) => live && setLoadError(e.message),
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  /** Runs one change and shows the API's message if it refuses. A rule that no longer exists is dropped from the list. */
  async function run(change: () => Promise<void>, ruleId?: string): Promise<void> {
    setBusy(true);
    setError('');
    try {
      await change();
    } catch (e) {
      setError((e as Error).message);
      if (ruleId && e instanceof ApiError && e.status === 404) {
        setRules((current) => (current ?? []).filter((r) => r.id !== ruleId));
        setRemoving('');
      }
    } finally {
      setBusy(false);
    }
  }

  const add = (e: Event) => {
    e.preventDefault();
    const keyword = word.trim();
    if (!keyword || rules === null) return;
    if (rules.some((r) => r.keyword.toLowerCase() === keyword.toLowerCase())) return setError('You already have this keyword.');
    const maxPrice = max.trim() ? parsePrice(max) : null;
    if (max.trim() && maxPrice === null) return setError('Enter the highest price like 200 or 199.99, or leave it empty.');
    void run(async () => {
      const created = await api.addRule({ keyword, maxPrice });
      setRules((current) => [created, ...(current ?? [])]);
      setWord('');
      setMax('');
    });
  };

  const toggle = (rule: Rule) =>
    run(async () => {
      const updated = await api.editRule(rule.id, { enabled: !rule.enabled });
      setRules((current) => (current ?? []).map((r) => (r.id === rule.id ? updated : r)));
    }, rule.id);

  const remove = (rule: Rule) =>
    run(async () => {
      await api.deleteRule(rule.id);
      setRules((current) => (current ?? []).filter((r) => r.id !== rule.id));
      setRemoving('');
    }, rule.id);

  const typing = (set: (value: string) => void) => (e: Event) => {
    set((e.currentTarget as HTMLInputElement).value);
    setError('');
  };

  return (
    <main class="screen">
      <header>
        <h1>Keywords</h1>
        <div class="muted">We watch deal feeds and alert you on a match.</div>
      </header>

      <form class="field" onSubmit={add}>
        <label class="sr" for="kw">
          New keyword
        </label>
        <div class="row">
          <input id="kw" class="text grow-row" autoComplete="off" autoCapitalize="off" maxLength={60} placeholder="Add a keyword, e.g. OLED" value={word} onInput={typing(setWord)} />
          <button class="fab square" type="submit" aria-label="Add keyword" disabled={busy || rules === null || !word.trim()}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>
        <label class="sr" for="kwmax">
          Highest price (optional)
        </label>
        <input id="kwmax" class="text" inputMode="decimal" autoComplete="off" maxLength={9} placeholder="Highest price, optional, e.g. 1200" value={max} onInput={typing(setMax)} />
      </form>

      {loadError && (
        <div class="notice" role="alert">
          <span>{loadError}</span>
          <button class="button" type="button" onClick={() => setAttempt(attempt + 1)}>
            Retry
          </button>
        </div>
      )}
      {error && (
        <div class="notice" role="alert">
          <span>{error}</span>
        </div>
      )}

      {rules && rules.length === 0 && <p class="muted center">No keywords yet. Add one above, like “OLED” or “AirPods”.</p>}
      <ul class="list">
        {(rules ?? []).map((rule) => (
          <li class="card" key={rule.id}>
            <div class="grow">
              <div class={rule.enabled ? 'keyword' : 'keyword faint'}>{rule.keyword}</div>
              <div class="muted small">{ruleLine(rule)}</div>
              {removing === rule.id ? (
                <div class="row confirm">
                  <button class="button" type="button" disabled={busy} onClick={() => setRemoving('')}>
                    Keep
                  </button>
                  <button class="button danger" type="button" disabled={busy} onClick={() => remove(rule)}>
                    Remove
                  </button>
                </div>
              ) : (
                <button class="textbutton" type="button" onClick={() => setRemoving(rule.id)} aria-label={`Remove ${rule.keyword}`}>
                  Remove
                </button>
              )}
            </div>
            <SwitchButton on={rule.enabled} label={`${rule.keyword} alerts`} disabled={busy} onChange={() => toggle(rule)} />
          </li>
        ))}
      </ul>
      <p class="muted small">Alerts are sent once per deal.</p>
    </main>
  );
}
