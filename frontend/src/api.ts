import { getAccessToken } from './auth';
import type { Config } from './config';
import type { Deal, QuietHours, Rule, RuleInput, RulePatch, Settings, Watch, WatchInput, WatchPatch } from './types';

let base = '';

export function initApi(config: Config): void {
  base = config.apiUrl;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new Error('Signing in…');
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  if (res.status === 401 && retry) {
    await getAccessToken(true); // the token was rejected: renew it once and try again
    return call(path, init, false);
  }
  if (!res.ok) {
    const detail = await res.json().then((b: { error?: string }) => b.error, () => undefined);
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  return res.json();
}

const send = (method: string, body?: unknown): RequestInit => ({ method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const api = {
  watches: () => call<{ watches: Watch[] }>('/me/watches').then((r) => r.watches),
  watch: (id: string) => call<Watch>(`/me/watches/${id}`),
  addWatch: (w: WatchInput) => call<Watch>('/me/watches', send('POST', w)),
  editWatch: (id: string, patch: WatchPatch) => call<Watch>(`/me/watches/${id}`, send('PUT', patch)),
  deleteWatch: (id: string) => call<{ deleted: string }>(`/me/watches/${id}`, send('DELETE')),
  rules: () => call<{ rules: Rule[] }>('/me/rules').then((r) => r.rules),
  addRule: (r: RuleInput) => call<Rule>('/me/rules', send('POST', r)),
  editRule: (id: string, patch: RulePatch) => call<Rule>(`/me/rules/${id}`, send('PUT', patch)),
  deleteRule: (id: string) => call<{ deleted: string }>(`/me/rules/${id}`, send('DELETE')),
  deals: () => call<{ deals: Deal[] }>('/me/deals').then((r) => r.deals),
  settings: () => call<Settings>('/me/settings'),
  // The zone goes along every time, so travelling moves the quiet hours with the phone.
  saveQuietHours: (quietHours: QuietHours | null, timeZone: string) => call<Settings>('/me/settings', send('PUT', { quietHours, timeZone })),
  // The endpoint is a secret (it lets anyone push to the device): bodies only, never URLs, so it stays out of logs.
  pushStatus: (endpoint: string) => call<{ devices: number; thisDevice: boolean }>('/me/push/status', send('POST', { endpoint })),
  pushOn: (subscription: PushSubscriptionJSON, timeZone: string) =>
    call<{ devices: number }>('/me/push', send('PUT', { ...subscription, timeZone })),
  pushOff: (endpoint: string) => call<{ devices: number }>('/me/push', send('DELETE', { endpoint })),
  pushTest: (endpoint: string) => call<{ sent: number }>('/me/push/test', send('POST', { endpoint })),
};
