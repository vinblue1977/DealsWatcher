import type { Watch } from './types';

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

/** The store a product link belongs to, or null when it isn't a link we can watch. */
export function retailerFor(link: string): string | null {
  let url: URL;
  try {
    url = new URL(link.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' || url.username || url.password) return null;
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

/** A dollar amount typed by the user ("199", "$1,099.50") as a number, or null if it isn't a positive amount under $100,000. */
export function parsePrice(text: string): number | null {
  const cleaned = text.replace(/[$,\s]/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const amount = Number(cleaned);
  return amount > 0 && amount < 100000 ? amount : null;
}

/** "Best Buy" becomes "BB", "Target" becomes "T". */
export function initials(store: string): string {
  const words = store.split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.map((w) => w.charAt(0)).join('') : (words[0] ?? '?').charAt(0);
  return letters.toUpperCase().slice(0, 2);
}

export function ago(iso: string, now = Date.now()): string {
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
}

export function watchState(w: Watch): WatchState {
  if (w.paused) return { label: 'Paused', tone: 'muted', atTarget: false, blocked: false };
  if (w.status === 'blocked') return { label: "Can't read price", tone: 'warn', atTarget: false, blocked: true };
  if (w.lastPrice === undefined) return { label: 'Waiting for first check', tone: 'muted', atTarget: false, blocked: false };
  if (w.lastPrice <= w.targetPrice) return { label: 'At target', tone: 'good', atTarget: true, blocked: false };
  return { label: `${targetMoney(w.lastPrice - w.targetPrice)} above target`, tone: 'muted', atTarget: false, blocked: false };
}

/** Subtitle under "Watching": the count and when the newest check happened. */
export function summary(watches: Watch[], now = Date.now()): string {
  const count = `${watches.length} ${watches.length === 1 ? 'item' : 'items'}`;
  const checked = watches.flatMap((w) => (w.lastChecked ? [w.lastChecked] : [])).sort().at(-1);
  return checked ? `${count} · checked ${ago(checked, now)}` : count;
}
