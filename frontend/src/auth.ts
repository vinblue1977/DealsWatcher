// Cognito managed login with authorization code + PKCE, and a session that stays signed in.
//
// Tokens live in localStorage. The app client's refresh token lasts a year, so the access token (1 hour) is renewed
// quietly: on demand, shortly before it expires (keepFresh), when the app comes back to the foreground, and after a 401.
// Only a *rejected* refresh token (HTTP 4xx) sends the person back to sign in; a network blip keeps the session.
// Tradeoff: localStorage is readable by any script on this origin; the strict CSP (no inline or third-party scripts) and the
// lint rules against HTML sinks are what protect it. iOS clears website data after 7 days of non-use in Safari tabs but not
// for Home Screen apps, which is how the app is meant to be used.
import type { Config } from './config';

const STORE = 'dw.tokens';
const PKCE = 'dw.pkce.';
const PKCE_TTL = 10 * 60 * 1000;
const RETRY = 'dw.retry';
const RETRY_WINDOW = 2 * 60 * 1000;
const EXPIRY_MARGIN = 60_000; // refresh when less than a minute is left
const REFRESH_AHEAD = 5 * 60_000; // keepFresh renews this long before expiry

interface Tokens {
  access_token: string;
  id_token?: string;
  refresh_token?: string;
  expires_at: number;
}

type TokenResponse = { access_token: string; id_token?: string; refresh_token?: string; expires_in?: number };

let refreshing: Promise<TokenResponse> | undefined; // single-flight refresh
let cfg: Config | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;

export const b64url = (bytes: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const randomString = (len = 32) => b64url(crypto.getRandomValues(new Uint8Array(len)));
const redirectUri = () => `${location.origin}/`;

function authUrl(path: string, params: Record<string, string>): string {
  if (!cfg) return '#';
  const url = new URL(`${cfg.authUrl}${path}`);
  url.search = new URLSearchParams({ client_id: cfg.clientId, ...params }).toString();
  return url.toString();
}

function local<T>(fn: (ls: Storage) => T): T | null {
  try {
    return fn(localStorage);
  } catch {
    return null;
  }
}

function readPkce(ls: Storage, key: string): { verifier: string; at: number } | null {
  try {
    return JSON.parse(ls.getItem(key) ?? 'null');
  } catch {
    return null;
  }
}

function putPkce(state: string, verifier: string): void {
  local((ls) => {
    for (const key of Object.keys(ls)) {
      if (key.startsWith(PKCE) && !((readPkce(ls, key)?.at ?? 0) > Date.now() - PKCE_TTL)) ls.removeItem(key);
    }
    ls.setItem(PKCE + state, JSON.stringify({ verifier, at: Date.now() }));
  });
}

function takePkce(state: string): string | null {
  return local((ls) => {
    const record = readPkce(ls, PKCE + state);
    ls.removeItem(PKCE + state);
    return record && record.at > Date.now() - PKCE_TTL ? record.verifier : null;
  });
}

function load(): Tokens | null {
  return local((ls) => JSON.parse(ls.getItem(STORE) ?? 'null'));
}

function save(t: TokenResponse): void {
  const prev = load();
  const tokens: Tokens = {
    access_token: t.access_token,
    id_token: t.id_token ?? prev?.id_token,
    refresh_token: t.refresh_token ?? prev?.refresh_token, // a refresh response doesn't repeat the refresh token
    expires_at: Date.now() + (t.expires_in ?? 3600) * 1000,
  };
  local((ls) => ls.setItem(STORE, JSON.stringify(tokens))); // blocked storage: the session just won't persist
}

async function tokenRequest(params: Record<string, string>): Promise<TokenResponse> {
  if (!cfg) throw new Error('Not configured');
  const res = await fetch(`${cfg.authUrl}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: cfg.clientId, ...params }),
  });
  if (!res.ok) throw Object.assign(new Error(`Sign-in failed (${res.status}). Please try again.`), { status: res.status });
  return res.json();
}

let redirecting: Promise<void> | null = null;

/** Starts the sign-in redirect. Parallel callers (several API calls failing at once) share one redirect and one PKCE entry. */
export function login(): Promise<void> {
  redirecting ??= startLogin().finally(() => {
    redirecting = null;
  });
  return redirecting;
}

async function startLogin(): Promise<void> {
  const verifier = randomString(48);
  const state = randomString(16);
  const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
  putPkce(state, verifier);
  location.assign(
    authUrl('/oauth2/authorize', {
      response_type: 'code',
      redirect_uri: redirectUri(),
      scope: 'openid email',
      code_challenge_method: 'S256',
      code_challenge: challenge,
      state,
    }),
  );
}

export const addPasskeyUrl = () => authUrl('/passkeys/add', { redirect_uri: redirectUri() });

export function logout(): void {
  clearTimeout(timer);
  local((ls) => ls.removeItem(STORE));
  location.assign(authUrl('/logout', { logout_uri: redirectUri() }));
}

/** True when signed in; otherwise starts the redirect to the sign-in page. */
export async function initAuth(config: Config): Promise<boolean> {
  cfg = config;
  const params = new URLSearchParams(location.search);
  if (params.has('code')) {
    history.replaceState(null, '', `${location.pathname}${location.hash || '#/'}`);
    try {
      const state = params.get('state');
      const verifier = state ? takePkce(state) : null;
      if (!verifier && load()) return true; // an old callback URL while signed in
      if (!verifier) throw new Error('Sign-in could not be verified. Please try again.');
      save(
        await tokenRequest({
          grant_type: 'authorization_code',
          code: params.get('code') ?? '',
          redirect_uri: redirectUri(),
          code_verifier: verifier,
        }),
      );
      local((ls) => ls.removeItem(RETRY));
      return true;
    } catch (e) {
      // Retry once (Cognito's session usually makes it instant); a second failure within 2 minutes shows the error.
      const retried = Number(local((ls) => ls.getItem(RETRY))) > Date.now() - RETRY_WINDOW;
      if (!retried && local((ls) => (ls.setItem(RETRY, String(Date.now())), true))) {
        await login();
        return false;
      }
      local((ls) => ls.removeItem(RETRY));
      throw e;
    }
  }
  if (params.has('error')) {
    history.replaceState(null, '', location.pathname);
    if (load()) return true; // e.g. a cancelled passkey registration
    throw new Error(params.get('error_description') || 'Sign-in was cancelled.');
  }
  if (load()) return true;
  await login();
  return false;
}

/** A valid access token, renewed with the refresh token when it is (nearly) expired or `forceRefresh` is set. */
export async function getAccessToken(forceRefresh = false): Promise<string | null> {
  const tokens = load();
  if (!tokens) {
    await login();
    return null;
  }
  if (forceRefresh || Date.now() > tokens.expires_at - EXPIRY_MARGIN) {
    const refreshToken = tokens.refresh_token;
    if (!refreshToken) {
      await login();
      return null;
    }
    try {
      refreshing ??= tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken }).finally(() => (refreshing = undefined));
      save(await refreshing);
    } catch (e) {
      // Only a rejected refresh token ends the session; a network blip or server error keeps it.
      const status = (e as { status?: number }).status ?? 0;
      if (status < 400 || status >= 500) throw e;
      local((ls) => ls.removeItem(STORE));
      await login();
      return null;
    }
  }
  return load()?.access_token ?? null;
}

/** Renews the access token before it expires and whenever the app returns to the foreground. */
export function keepFresh(): void {
  const arm = () => {
    clearTimeout(timer);
    const tokens = load();
    if (!tokens?.refresh_token) return;
    const wait = Math.max(tokens.expires_at - REFRESH_AHEAD - Date.now(), 30_000);
    timer = setTimeout(() => {
      getAccessToken(true)
        .catch(() => undefined) // offline: the next visit or timer tries again
        .finally(arm);
    }, wait);
  };
  arm();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void getAccessToken().catch(() => undefined).finally(arm);
  });
}

export function currentEmail(): string {
  const idToken = load()?.id_token;
  if (!idToken) return '';
  try {
    return JSON.parse(atob((idToken.split('.')[1] ?? '').replace(/-/g, '+').replace(/_/g, '/'))).email ?? '';
  } catch {
    return '';
  }
}
