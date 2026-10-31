import type { CheckerStatus, Rule, Source, Watch } from './types';

export type Tone = 'good' | 'warn' | 'muted';

// The stores the API accepts (mirrors RETAILERS in backend/api/watches.py; the server is the authority).
const RETAILERS: Record<string, string> = {
  'bestbuy.com': 'Best Buy',
  'target.com': 'Target',
  'walmart.com': 'Walmart',
  'costco.com': 'Costco',
  'tennis-warehouse.com': 'Tennis Warehouse',
};

export const STORE_NAMES = Object.values(RETAILERS);

/** Whether anything reads store prices. Not yet (see ROADMAP "Store price checking"): watches are only saved, so the app says
 * so instead of promising a first check. Flip this to true in the PR that ships the first store checker. */
export const STORE_PRICES_CHECKED = false;

export const NO_CHECKER_EMPTY = "Store prices aren't read yet, so a watch only keeps your list and target for now. For deal alerts today, use Keywords.";

export const NO_CHECKER_NOTE = "Store prices aren't read yet. Your watch is saved with its target, and alerts start once a store checker is added. For deal alerts today, use Keywords.";

/** A plain https link (no embedded credentials) as a URL, else null. */
export function httpsUrl(link: string): URL | null {
  try {
    const url = new URL(link.trim());
    return url.protocol === 'https:' && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

/** The store a product link belongs to, or null when it isn't a link we can watch. */
export function retailerFor(link: string): string | null {
  const url = httpsUrl(link);
  if (!url) return null;
  const host = url.hostname.toLowerCase();
  const match = Object.entries(RETAILERS).find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  return match ? match[1] : null;
}

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export function money(amount: number): string {
  return dollars.format(amount);
}

/** A target without cents when it is a whole number ("$199"), as the mockups show it. */
export function targetMoney(amount: number): string {
  return Number.isInteger(amount) ? dollars.format(amount).replace(/\.00$/, '') : dollars.format(amount);
}

/** A dollar amount typed by the user ("199", "$1,099.50") as a number, or null if it isn't a positive amount under $100,000.
 * Commas count only as thousands separators, so "1,99" is refused instead of read as 199. */
export function parsePrice(text: string): number | null {
  const typed = text.trim().replace(/^\$\s*/, '');
  if (!/^(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$/.test(typed)) return null;
  const amount = Number(typed.replace(/,/g, ''));
  return amount > 0 && amount < 100000 ? amount : null;
}

/** A keyword's highest price as typed: a number, null for "any price" (empty), or undefined if it is not a valid amount. */
export function parseMaxPrice(text: string): number | null | undefined {
  return text.trim() === '' ? null : (parsePrice(text) ?? undefined);
}

/** A watch name typed by the user, trimmed; null if empty or over 120 characters (counted like the API does, by code points). */
export function parseName(text: string): string | null {
  const name = text.trim();
  return name.length > 0 && [...name].length <= 120 ? name : null;
}

/** "Best Buy" becomes "BB", "Target" becomes "T". */
export function initials(store: string): string {
  const words = store.split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.map((w) => w.charAt(0)).join('') : (words[0] ?? '?').charAt(0);
  return letters.toUpperCase().slice(0, 2);
}

export function ago(iso: string, now = Date.now()): string {
  if (Number.isNaN(Date.parse(iso))) return 'a while ago';
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export interface WatchState {
  label: string;
  tone: Tone;
  /** At or under the target price. */
  atTarget: boolean;
  /** The checker couldn't read this product's price. */
  blocked: boolean;
  /** Nothing reads this product's price at all (there is no store checker yet): the app says so. */
  noChecker: boolean;
}

export function watchState(w: Watch, storePricesChecked = STORE_PRICES_CHECKED): WatchState {
  const base = { atTarget: false, blocked: false, noChecker: false };
  if (w.paused) return { ...base, label: 'Paused', tone: 'muted' };
  if (w.status === 'blocked') return { ...base, label: "Can't read price", tone: 'warn', blocked: true };
  if (w.lastPrice === undefined) {
    return { ...base, label: storePricesChecked ? 'Waiting for first check' : 'Prices not read yet', tone: 'muted', noChecker: !storePricesChecked };
  }
  if (w.lastPrice <= w.targetPrice) return { ...base, label: 'At target', tone: 'good', atTarget: true };
  return { ...base, label: `${targetMoney(Math.round((w.lastPrice - w.targetPrice) * 100) / 100)} above target`, tone: 'muted' };
}

/** Subtitle under "Watching": the count and when the newest check happened. */
export function summary(watches: Watch[], now = Date.now()): string {
  const count = `${watches.length} ${watches.length === 1 ? 'item' : 'items'}`;
  const times = watches.flatMap((w) => (w.lastChecked && !Number.isNaN(Date.parse(w.lastChecked)) ? [w.lastChecked] : []));
  const checked = times.sort((a, b) => Date.parse(a) - Date.parse(b)).at(-1);
  return checked ? `${count} · checked ${ago(checked, now)}` : count;
}

const SOURCE_NAMES: Record<Source, string> = { dealnews: 'Dealnews', reddit: 'Reddit', slickdeals: 'Slickdeals' };
// The feeds the checker reads (Slickdeals and Reddit disallow automated access); stored rules may still list others.
export const ACTIVE_SOURCES: Source[] = ['dealnews'];

export const sourceName = (source: Source | undefined): string => (source ? (SOURCE_NAMES[source] ?? source) : '');

/** A link from an outside feed, only if it is a plain https link; anything else (javascript:, data:, http:) is dropped. */
export function safeLink(link: string | undefined): string | null {
  return link ? (httpsUrl(link)?.href ?? null) : null;
}

/** "Under $1,200 · Dealnews" (or "Any price · Dealnews"), with "Paused" at the end when it is off. Only feeds that are read are named. */
export function ruleLine(rule: Rule): string {
  const price = rule.maxPrice === null ? 'Any price' : `Under ${targetMoney(rule.maxPrice)}`;
  const feeds = rule.sources.filter((s) => ACTIVE_SOURCES.includes(s)).map(sourceName).join(', ') || 'No active feed';
  return [price, feeds, ...(rule.enabled ? [] : ['Paused'])].join(' · ');
}

export type WatchFilter = 'all' | 'target' | 'attention';

export function visibleWatches(watches: Watch[], filter: WatchFilter): Watch[] {
  return watches.filter((w) => {
    const state = watchState(w);
    return filter === 'all' || (filter === 'target' ? state.atTarget : state.blocked);
  });
}

/** An hour of the day (0-23) as the mockups show it: "10 PM", "12 AM". */
export function hourLabel(hour: number): string {
  return `${hour % 12 || 12} ${hour < 12 ? 'AM' : 'PM'}`;
}

const STALE_MINUTES = 90; // three missed runs of the checker's 30-minute schedule (infra/feeds.py: change both together)

/** The "last checked" line: when the feeds were last read, how many answered, and whether it has gone quiet for too long. */
export function checkerLine(status: CheckerStatus, now = Date.now()): { text: string; stale: boolean } {
  const iso = status.checkedAt;
  const at = iso ? Date.parse(iso) : NaN;
  if (!iso || Number.isNaN(at)) return { text: 'Not checked yet', stale: false };
  const stale = now - at > STALE_MINUTES * 60000;
  const read = status.feedsRead ?? 0;
  const total = read + (status.feedsFailed ?? 0) + (status.feedsSkipped ?? 0);
  const feeds = total > read ? ` · ${read} of ${total} feeds` : '';
  return { text: stale ? `Last checked ${ago(iso, now)}, new deals may be delayed` : `Checked ${ago(iso, now)}${feeds}`, stale };
}
