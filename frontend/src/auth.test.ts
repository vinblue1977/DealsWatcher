import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Config } from './config';

const CONFIG: Config = { apiUrl: 'https://api.test', authUrl: 'https://auth.test', clientId: 'cid' };
const NOW = new Date('2026-10-28T12:00:00Z').getTime();

/** localStorage stand-in: data are own enumerable keys (the code iterates them); methods are not. */
function memoryStorage(): Storage {
  const data: Record<string, string> = {};
  const methods = {
    getItem: (k: string) => (k in data ? data[k] : null),
    setItem: (k: string, v: string) => void (data[k] = String(v)),
    removeItem: (k: string) => void Reflect.deleteProperty(data, k),
  };
  for (const [name, fn] of Object.entries(methods)) Object.defineProperty(data, name, { value: fn, enumerable: false });
  return data as unknown as Storage;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const seed = (tokens: object) => localStorage.setItem('dw.tokens', JSON.stringify(tokens));
const stored = () => JSON.parse(localStorage.getItem('dw.tokens') ?? 'null');
const idToken = (claims: object) => `h.${btoa(JSON.stringify(claims)).replace(/\+/g, '-').replace(/\//g, '_')}.s`;

let fetchMock: ReturnType<typeof vi.fn>;
let assign: ReturnType<typeof vi.fn>;
let replaceState: ReturnType<typeof vi.fn>;
let location: { origin: string; search: string; pathname: string; hash: string; assign: typeof assign };
let listeners: Record<string, () => void>;
let doc: { visibilityState: string; addEventListener: (type: string, fn: () => void) => void };

async function freshAuth() {
  vi.resetModules(); // the module keeps its config and in-flight refresh between calls
  return import('./auth');
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  fetchMock = vi.fn();
  assign = vi.fn();
  replaceState = vi.fn();
  listeners = {};
  location = { origin: 'https://app.test', search: '', pathname: '/', hash: '', assign };
  doc = { visibilityState: 'visible', addEventListener: (type, fn) => void (listeners[type] = fn) };
  vi.stubGlobal('localStorage', memoryStorage());
  vi.stubGlobal('location', location);
  vi.stubGlobal('history', { replaceState });
  vi.stubGlobal('document', doc);
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('sign-in redirect (PKCE)', () => {
  it('sends an S256 challenge that matches the stored verifier, with a state', async () => {
    const auth = await freshAuth();
    await auth.initAuth(CONFIG); // no tokens: redirects
    const url = new URL(assign.mock.calls[0]?.[0] as string);
    expect(url.origin + url.pathname).toBe('https://auth.test/oauth2/authorize');
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('client_id')).toBe('cid');
    expect(url.searchParams.get('redirect_uri')).toBe('https://app.test/');
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
    const state = url.searchParams.get('state') ?? '';
    const record = JSON.parse(localStorage.getItem(`dw.pkce.${state}`) ?? 'null');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(record.verifier));
    expect(url.searchParams.get('code_challenge')).toBe(auth.b64url(digest));
  });

  it('exchanges the code with the stored verifier and saves the tokens', async () => {
    const auth = await freshAuth();
    localStorage.setItem('dw.pkce.S1', JSON.stringify({ verifier: 'verifier-1', at: NOW }));
    location.search = '?code=abc&state=S1';
    fetchMock.mockResolvedValue(json({ access_token: 'a1', id_token: 'i1', refresh_token: 'r1', expires_in: 3600 }));
    await expect(auth.initAuth(CONFIG)).resolves.toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://auth.test/oauth2/token');
    const body = new URLSearchParams(init.body as URLSearchParams);
    expect(Object.fromEntries(body)).toMatchObject({
      grant_type: 'authorization_code',
      code: 'abc',
      code_verifier: 'verifier-1',
      redirect_uri: 'https://app.test/',
      client_id: 'cid',
    });
    expect(stored()).toMatchObject({ access_token: 'a1', refresh_token: 'r1', expires_at: NOW + 3_600_000 });
    expect(localStorage.getItem('dw.pkce.S1')).toBeNull(); // single use
    expect(replaceState).toHaveBeenCalled(); // the code leaves the address bar
  });

  it('rejects a callback whose state is unknown or older than 10 minutes, retrying sign-in once', async () => {
    const auth = await freshAuth();
    localStorage.setItem('dw.pkce.OLD', JSON.stringify({ verifier: 'v', at: NOW - 11 * 60_000 }));
    location.search = '?code=abc&state=OLD';
    await expect(auth.initAuth(CONFIG)).resolves.toBe(false); // first failure: back to the sign-in page
    expect(assign).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(auth.initAuth(CONFIG)).rejects.toThrow('could not be verified'); // second failure shows the error
  });

  it('keeps an existing session when an old callback URL is opened', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'a', refresh_token: 'r', expires_at: NOW + 3_600_000 });
    location.search = '?code=abc&state=gone';
    await expect(auth.initAuth(CONFIG)).resolves.toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows a cancelled sign-in, but keeps a signed-in user signed in', async () => {
    const auth = await freshAuth();
    location.search = '?error=access_denied&error_description=Nope';
    await expect(auth.initAuth(CONFIG)).rejects.toThrow('Nope');
    seed({ access_token: 'a', expires_at: NOW + 3_600_000 });
    await expect(auth.initAuth(CONFIG)).resolves.toBe(true);
  });
});

describe('parallel sign-in attempts', () => {
  it('start one redirect and store one PKCE entry', async () => {
    const auth = await freshAuth();
    await Promise.all([auth.login(), auth.login(), auth.login()]);
    expect(assign).toHaveBeenCalledTimes(1);
  });
});

describe('staying signed in (silent refresh)', () => {
  it('returns a fresh token without any request', async () => {
    const auth = await freshAuth();
    await auth.initAuth(CONFIG);
    seed({ access_token: 'fresh', refresh_token: 'r', expires_at: NOW + 3_600_000 });
    await expect(auth.getAccessToken()).resolves.toBe('fresh');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refreshes an expired token, keeping the refresh token and the id token', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', id_token: 'id', refresh_token: 'r1', expires_at: NOW - 1000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'new', expires_in: 3600 })); // Cognito doesn't repeat the refresh token
    await expect(auth.getAccessToken()).resolves.toBe('new');
    const body = Object.fromEntries(new URLSearchParams((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as URLSearchParams));
    expect(body).toMatchObject({ grant_type: 'refresh_token', refresh_token: 'r1', client_id: 'cid' });
    expect(stored()).toMatchObject({ access_token: 'new', refresh_token: 'r1', id_token: 'id', expires_at: NOW + 3_600_000 });
    expect(assign).not.toHaveBeenCalled();
  });

  it('stores the new refresh token when Cognito rotates it', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', id_token: 'id', refresh_token: 'r1', expires_at: NOW - 1000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'new', refresh_token: 'r2', expires_in: 3600 }));
    await expect(auth.getAccessToken()).resolves.toBe('new');
    expect(stored()).toMatchObject({ access_token: 'new', refresh_token: 'r2', id_token: 'id' });
    fetchMock.mockClear();
    seed({ ...stored(), expires_at: NOW - 1 });
    fetchMock.mockResolvedValue(json({ access_token: 'newer', refresh_token: 'r3', expires_in: 3600 }));
    await auth.getAccessToken();
    const body = Object.fromEntries(new URLSearchParams((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as URLSearchParams));
    expect(body.refresh_token).toBe('r2'); // the next renewal uses the rotated token, not the first one
  });

  it('adopts the tokens another tab stored instead of signing out when the sent refresh token was rotated', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r1', expires_at: NOW - 1000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockImplementation(async () => {
      seed({ access_token: 'tab-b', refresh_token: 'r2', expires_at: NOW + 3_600_000 }); // the other tab finished first
      return json({ error: 'invalid_grant' }, 400);
    });
    await expect(auth.getAccessToken()).resolves.toBe('tab-b');
    expect(stored()).toMatchObject({ refresh_token: 'r2' });
    expect(assign).not.toHaveBeenCalled();
  });

  it('keeps the session when the token endpoint throttles (429)', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r', expires_at: NOW - 1 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ error: 'slow_down' }, 429));
    await expect(auth.getAccessToken()).rejects.toMatchObject({ status: 429 });
    expect(stored()).toMatchObject({ refresh_token: 'r' });
    expect(assign).not.toHaveBeenCalled();
  });

  it('refreshes a token that is within a minute of expiring', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r', expires_at: NOW + 30_000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'new' }));
    await expect(auth.getAccessToken()).resolves.toBe('new');
  });

  it('sends one refresh request for concurrent callers', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r', expires_at: NOW - 1 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'new', expires_in: 3600 }));
    const tokens = await Promise.all([auth.getAccessToken(), auth.getAccessToken(), auth.getAccessToken(true)]);
    expect(tokens).toEqual(['new', 'new', 'new']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('forces a refresh after a 401 even though the token looks valid', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r', expires_at: NOW + 3_000_000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'new' }));
    await expect(auth.getAccessToken(true)).resolves.toBe('new');
  });

  it('signs in again only when the refresh token is rejected', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'revoked', expires_at: NOW - 1 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ error: 'invalid_grant' }, 400));
    await expect(auth.getAccessToken()).resolves.toBeNull();
    expect(stored()).toBeNull();
    expect(String(assign.mock.calls[0]?.[0])).toContain('/oauth2/authorize');
  });

  it.each([
    ['a network failure', () => fetchMock.mockRejectedValue(new TypeError('offline'))],
    ['a server error', () => fetchMock.mockResolvedValue(json({}, 503))],
  ])('keeps the session through %s', async (_name, fail) => {
    const auth = await freshAuth();
    seed({ access_token: 'old', refresh_token: 'r', expires_at: NOW - 1 });
    await auth.initAuth(CONFIG);
    fail();
    await expect(auth.getAccessToken()).rejects.toThrow();
    expect(stored()).toMatchObject({ refresh_token: 'r' });
    expect(assign).not.toHaveBeenCalled();
  });

  it('signs in when the token expired and there is no refresh token', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'old', expires_at: NOW - 1 });
    await auth.initAuth(CONFIG);
    await expect(auth.getAccessToken()).resolves.toBeNull();
    expect(assign).toHaveBeenCalledTimes(1);
  });

  it('keepFresh renews the token before it expires and keeps renewing', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'a0', refresh_token: 'r', expires_at: NOW + 3_600_000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockImplementation(async () => json({ access_token: `a${fetchMock.mock.calls.length}`, expires_in: 3600 }));
    auth.keepFresh();
    await vi.advanceTimersByTimeAsync(54 * 60_000);
    expect(fetchMock).not.toHaveBeenCalled(); // not yet: it renews 5 minutes before expiry
    await vi.advanceTimersByTimeAsync(2 * 60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(stored().access_token).toBe('a1');
    await vi.advanceTimersByTimeAsync(56 * 60_000);
    expect(fetchMock).toHaveBeenCalledTimes(2); // re-armed after the first renewal
  });

  it('keepFresh survives a failed renewal and tries again', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'a0', refresh_token: 'r', expires_at: NOW + 400_000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue(json({ access_token: 'a1', expires_in: 3600 }));
    auth.keepFresh();
    await vi.advanceTimersByTimeAsync(100_000);
    expect(fetchMock).toHaveBeenCalledTimes(1); // failed, still signed in
    expect(stored().access_token).toBe('a0');
    await vi.advanceTimersByTimeAsync(30_000); // retries 30 seconds later
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(stored().access_token).toBe('a1');
  });

  it('renews when the app returns to the foreground after a long time away', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'a0', refresh_token: 'r', expires_at: NOW + 3_600_000 });
    await auth.initAuth(CONFIG);
    fetchMock.mockResolvedValue(json({ access_token: 'a1', expires_in: 3600 }));
    auth.keepFresh();
    vi.setSystemTime(NOW + 2 * 3_600_000); // phone slept; timers were frozen
    listeners['visibilitychange']?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(stored().access_token).toBe('a1');
    doc.visibilityState = 'hidden';
    fetchMock.mockClear();
    listeners['visibilitychange']?.();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('session end and identity', () => {
  it('logout forgets the tokens and goes to the sign-out page', async () => {
    const auth = await freshAuth();
    seed({ access_token: 'a', id_token: 'i', refresh_token: 'r', expires_at: NOW + 1 });
    await auth.initAuth(CONFIG);
    auth.logout();
    expect(stored()).toBeNull();
    const url = new URL(assign.mock.calls[0]?.[0] as string);
    expect(url.pathname).toBe('/logout');
    expect(url.searchParams.get('logout_uri')).toBe('https://app.test/');
  });

  it('reads the email from the id token, and tolerates a missing or broken one', async () => {
    const auth = await freshAuth();
    expect(auth.currentEmail()).toBe('');
    seed({ access_token: 'a', id_token: idToken({ email: 'me@example.com' }), expires_at: NOW + 1 });
    expect(auth.currentEmail()).toBe('me@example.com');
    seed({ access_token: 'a', id_token: 'not-a-token', expires_at: NOW + 1 });
    expect(auth.currentEmail()).toBe('');
  });

  it('survives blocked storage: the session simply does not persist', async () => {
    const auth = await freshAuth();
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    });
    await expect(auth.initAuth(CONFIG)).resolves.toBe(false); // can't find tokens: signs in
    expect(assign).toHaveBeenCalled();
    expect(auth.addPasskeyUrl()).toContain('/passkeys/add');
  });
});
