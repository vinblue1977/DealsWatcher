// Shapes returned by the API (backend/api/*.py).
export type Source = 'dealnews' | 'reddit' | 'slickdeals';

/** The older kind: a store link and a price. Nothing reads these prices (see ROADMAP). */
export interface LinkWatch {
  id: string;
  url: string;
  urlHash: string;
  retailer: string;
  title: string;
  targetPrice: number;
  alertOnDrop: boolean;
  paused: boolean;
  status: 'pending' | 'ok' | 'blocked'; // pending until the checker has looked
  createdAt: string;
  lastPrice?: number;
  lowestPrice?: number;
  lastChecked?: string;
}

/** One recorded price: a deal the feeds listed for a tracked product. */
export interface Sighting {
  id: string;
  price: number;
  title?: string;
  url?: string;
  retailer?: string;
  publishedAt: string;
  newLow: boolean; // the lowest price seen up to then
}

/** A tracked product: a name (keyword syntax) and an optional price; the checker records its sightings. */
export interface Product {
  id: string;
  name: string;
  title: string;
  targetPrice: number | null;
  alertOnLow: boolean;
  alertOnDrop: boolean; // alert when a price reaches targetPrice
  paused: boolean;
  status: 'pending' | 'ok' | 'blocked';
  createdAt: string;
  lastPrice?: number;
  lowestPrice?: number;
  lowestRetailer?: string | null;
  lowestUrl?: string;
  lowestAt?: string;
  lastSeenAt?: string;
  sightings?: Sighting[]; // only on the product's own screen
}

export type Watch = LinkWatch | Product;
export const isProduct = (w: Watch): w is Product => 'name' in w;

export interface ProductInput {
  name: string;
  targetPrice?: number | null;
  alertOnLow?: boolean;
  alertOnDrop?: boolean;
}

export type ProductPatch = Partial<Pick<Product, 'targetPrice' | 'alertOnLow' | 'alertOnDrop' | 'paused' | 'title'>>;

export interface WatchInput {
  url: string;
  targetPrice: number;
  title?: string;
  alertOnDrop?: boolean;
}

export type WatchPatch = Partial<Pick<LinkWatch, 'targetPrice' | 'alertOnDrop' | 'paused' | 'title'>>;

export interface Rule {
  id: string;
  keyword: string;
  maxPrice: number | null;
  sources: Source[];
  enabled: boolean;
  createdAt: string;
}

export interface RuleInput {
  keyword: string;
  maxPrice?: number | null;
  sources?: Source[];
  enabled?: boolean;
}

export type RulePatch = Partial<RuleInput>;

export interface Deal {
  id: string; // stable key, newest first
  title?: string;
  url?: string;
  price?: number | null;
  source?: Source;
  keyword?: string;
  retailer?: string;
  publishedAt?: string;
}

export interface QuietHours {
  start: number; // hour of the day, 0-23, in the device's time zone
  end: number;
}

export interface Settings {
  quietHours: QuietHours | null;
  timeZone: string | null; // the zone the checker uses; set when notifications are turned on
}

export interface CheckerStatus {
  checkedAt: string | null; // null until the checker has run
  feedsRead?: number;
  feedsFailed?: number;
  feedsSkipped?: number;
}
