import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAccessToken = vi.fn();
vi.mock('./auth', () => ({ getAccessToken: (force?: boolean) => getAccessToken(force) }));

import { ApiError, api, initApi } from './api';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  getAccessToken.mockReset().mockResolvedValue('tok');
  initApi({ apiUrl: 'https://api.test', authUrl: 'https://auth.test', clientId: 'c' });
});

const lastCall = () => fetchMock.mock.calls.at(-1) as [string, RequestInit & { headers: Record<string, string> }];

describe('api client', () => {
  it('sends the bearer token and unwraps lists', async () => {
    fetchMock.mockResolvedValue(json({ watches: [{ id: 'w1' }] }));
    await expect(api.watches()).resolves.toEqual([{ id: 'w1' }]);
    const [url, init] = lastCall();
    expect(url).toBe('https://api.test/me/watches');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer tok', 'Content-Type': 'application/json' });
  });

  it.each([
    ['addWatch', () => api.addWatch({ url: 'https://www.target.com/x', targetPrice: 5 }), 'POST', '/me/watches', { url: 'https://www.target.com/x', targetPrice: 5 }],
    ['editWatch', () => api.editWatch('w1', { paused: true }), 'PUT', '/me/watches/w1', { paused: true }],
    ['deleteWatch', () => api.deleteWatch('w1'), 'DELETE', '/me/watches/w1', undefined],
    ['addRule', () => api.addRule({ keyword: 'OLED' }), 'POST', '/me/rules', { keyword: 'OLED' }],
    ['editRule', () => api.editRule('r1', { enabled: false }), 'PUT', '/me/rules/r1', { enabled: false }],
    ['deleteRule', () => api.deleteRule('r1'), 'DELETE', '/me/rules/r1', undefined],
    ['pushOff', () => api.pushOff('https://web.push.apple.com/x'), 'DELETE', '/me/push', { endpoint: 'https://web.push.apple.com/x' }],
    ['pushTest', () => api.pushTest('https://web.push.apple.com/x'), 'POST', '/me/push/test', { endpoint: 'https://web.push.apple.com/x' }],
  ])('%s uses the right method, path and body', async (_name, run, method, path, body) => {
    fetchMock.mockResolvedValue(json({}));
    await run();
    const [url, init] = lastCall();
    expect(url).toBe(`https://api.test${path}`);
    expect(init.method).toBe(method);
    expect(init.body === undefined ? undefined : JSON.parse(init.body as string)).toEqual(body);
  });

  it('reads single items, rules, deals and push status', async () => {
    fetchMock.mockImplementation(async () => json({ id: 'w1', rules: [1], deals: [2], devices: 1, thisDevice: true }));
    await expect(api.watch('w1')).resolves.toMatchObject({ id: 'w1' });
    await expect(api.rules()).resolves.toEqual([1]);
    await expect(api.deals()).resolves.toEqual([2]);
    await expect(api.pushStatus('https://x/a b')).resolves.toMatchObject({ thisDevice: true });
    const [url, init] = lastCall();
    expect(url).toBe('https://api.test/me/push/status'); // the endpoint is a secret: in the body, never in the URL
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ endpoint: 'https://x/a b' });
  });

  it('merges the subscription with the time zone when turning notifications on', async () => {
    fetchMock.mockResolvedValue(json({ devices: 1 }));
    await api.pushOn({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } }, 'America/Chicago');
    expect(JSON.parse(lastCall()[1].body as string)).toEqual({
      endpoint: 'https://web.push.apple.com/x',
      keys: { p256dh: 'p', auth: 'a' },
      timeZone: 'America/Chicago',
    });
  });

  it('renews the token once on a 401 and retries', async () => {
    fetchMock.mockResolvedValueOnce(json({ error: 'unauthorized' }, 401)).mockResolvedValueOnce(json({ watches: [] }));
    getAccessToken.mockResolvedValueOnce('stale').mockResolvedValueOnce('renewed').mockResolvedValueOnce('renewed');
    await expect(api.watches()).resolves.toEqual([]);
    expect(getAccessToken.mock.calls.map((c) => c[0])).toEqual([undefined, true, undefined]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(lastCall()[1].headers.Authorization).toBe('Bearer renewed');
  });

  it('gives up after one retry', async () => {
    fetchMock.mockResolvedValue(json({}, 401));
    await expect(api.watches()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces the server message, or a generic one', async () => {
    fetchMock.mockResolvedValueOnce(json({ error: 'up to 100 watches' }, 400));
    await expect(api.addWatch({ url: 'u', targetPrice: 1 })).rejects.toThrow('up to 100 watches');
    fetchMock.mockResolvedValueOnce(new Response('<html>', { status: 502 }));
    const err = await api.watches().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe('Request failed (502)');
  });

  it('does not call the API while redirecting to sign in', async () => {
    getAccessToken.mockResolvedValue(null);
    await expect(api.watches()).rejects.toThrow('Signing in');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
