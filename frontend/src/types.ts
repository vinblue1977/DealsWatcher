// Shapes returned by the API (backend/api/*.py).
export type Source = 'dealnews' | 'reddit' | 'slickdeals';

export interface Watch {
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

export interface WatchInput {
  url: string;
  targetPrice: number;
  title?: string;
  alertOnDrop?: boolean;
}

export type WatchPatch = Partial<Pick<Watch, 'targetPrice' | 'alertOnDrop' | 'paused' | 'title'>>;

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
