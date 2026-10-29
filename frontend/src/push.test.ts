import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';
import { disablePush, enablePush, initPush, keyBytes, pushState, testPush } from './push';

vi.mock('./api', () => ({
  api: {
    pushStatus: vi.fn(async (endpoint: string) => ({ devices: 1, thisDevice: endpoint === 'https://push.test/mine' })),
    pushOn: vi.fn(async () => ({ devices: 1 })),
    pushOff: vi.fn(async () => ({ devices: 0 })),
    pushTest: vi.fn(async () => ({ sent: 1 })),
  },
}));

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)';

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

interface Options {
  standalone?: boolean;
  permission?: string;
  existing?: { endpoint: string; unsubscribe: () => Promise<boolean> } | null;
  push?: boolean;
  userAgent?: string;
  ready?: Promise<unknown>;
  register?: () => Promise<unknown>;
  subscribe?: () => Promise<unknown>;
}

function device(o: Options = {}) {
  const pushManager = {
    getSubscription: async () => o.existing ?? null,
    subscribe: vi.fn(o.subscribe ?? (async () => ({ endpoint: 'https://push.test/new', toJSON: () => ({ endpoint: 'https://push.test/new' }), unsubscribe: vi.fn(async () => true) }))),
  };
  vi.stubGlobal('navigator', {
    standalone: o.standalone ?? true,
    userAgent: o.userAgent ?? IPHONE,
    ...(o.push === false ? {} : { serviceWorker: { ready: o.ready ?? Promise.resolve({ pushManager }), register: o.register ?? vi.fn(async () => ({})) } }),
  });
  vi.stubGlobal('PushManager', o.push === false ? undefined : vi.fn());
  if (o.push === false) vi.stubGlobal('PushManager', undefined);
  vi.stubGlobal('Notification', Object.assign(vi.fn(), { permission: o.permission ?? 'default', requestPermission: vi.fn(async () => o.permission ?? 'granted') }));
  return pushManager;
}

describe('keyBytes', () => {
  it('decodes a URL-safe base64 key, with or without padding', () => {
    expect([...keyBytes('AQID')]).toEqual([1, 2, 3]);
    expect([...keyBytes('-_8')]).toEqual([251, 255]);
  });
});

describe('pushState', () => {
  it('asks only iPhone Safari tabs to install the app first', async () => {
    device({ push: false, standalone: false });
    expect(await pushState()).toBe('needs-install');
    device({ push: false, standalone: false, userAgent: 'Mozilla/5.0 (X11; Linux) Firefox/130' });
    expect(await pushState()).toBe('unsupported'); // the iPhone instructions would be wrong here
    device({ push: false, standalone: true });
    expect(await pushState()).toBe('unsupported');
  });
  it('reports blocked, off and on', async () => {
    device({ permission: 'denied' });
    expect(await pushState()).toBe('blocked');
    device({ existing: null });
    expect(await pushState()).toBe('off');
    device({ existing: { endpoint: 'https://push.test/mine', unsubscribe: async () => true } });
    expect(await pushState()).toBe('on');
    device({ existing: { endpoint: 'https://push.test/other', unsubscribe: async () => true } }); // the server no longer knows it
    expect(await pushState()).toBe('off');
  });
  it('says so when the service worker cannot be registered', async () => {
    device({ register: async () => Promise.reject(new Error('blocked')) });
    await expect(pushState()).rejects.toThrow('could not start');
  });
  it('fails with a clear message when the service worker never starts', async () => {
    vi.useFakeTimers();
    device({ ready: new Promise(() => undefined) });
    const result = pushState();
    const assertion = expect(result).rejects.toThrow('background worker is not running');
    await vi.advanceTimersByTimeAsync(5000);
    await assertion;
  });
});

describe('enablePush', () => {
  it('needs the server key and the user’s permission', async () => {
    device();
    initPush({ apiUrl: '', authUrl: '', clientId: '' });
    await expect(enablePush()).rejects.toThrow('not set up on the server');
    initPush({ apiUrl: '', authUrl: '', clientId: '', vapidPublicKey: 'AQID' });
    device({ permission: 'denied' });
    await expect(enablePush()).rejects.toThrow('were not allowed');
  });
  it('subscribes and tells the server', async () => {
    const pm = device();
    initPush({ apiUrl: '', authUrl: '', clientId: '', vapidPublicKey: 'AQID' });
    await enablePush();
    expect(pm.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(api.pushOn).toHaveBeenCalledOnce();
  });
  it('replaces a subscription made with another key (the server key changed)', async () => {
    const stale = { endpoint: 'https://push.test/old', unsubscribe: vi.fn(async () => true) };
    const created = { endpoint: 'https://push.test/new', toJSON: () => ({}), unsubscribe: vi.fn(async () => true) };
    const subscribe = vi.fn().mockRejectedValueOnce(Object.assign(new Error('different key'), { name: 'InvalidStateError' })).mockResolvedValueOnce(created);
    device({ existing: stale, subscribe });
    initPush({ apiUrl: '', authUrl: '', clientId: '', vapidPublicKey: 'AQID' });
    await enablePush();
    expect(stale.unsubscribe).toHaveBeenCalledOnce();
    expect(subscribe).toHaveBeenCalledTimes(2);
  });
  it('keeps the device’s existing subscription when nothing needs replacing', async () => {
    const same = { endpoint: 'https://push.test/same', toJSON: () => ({}), unsubscribe: vi.fn(async () => true) };
    device({ existing: same, subscribe: async () => same });
    initPush({ apiUrl: '', authUrl: '', clientId: '', vapidPublicKey: 'AQID' });
    await enablePush();
    expect(same.unsubscribe).not.toHaveBeenCalled();
  });
  it('drops a new subscription when the server refuses it, but never the one it already had', async () => {
    const created = { endpoint: 'https://push.test/new', toJSON: () => ({}), unsubscribe: vi.fn(async () => true) };
    device({ subscribe: async () => created });
    initPush({ apiUrl: '', authUrl: '', clientId: '', vapidPublicKey: 'AQID' });
    vi.mocked(api.pushOn).mockRejectedValueOnce(new Error('up to 10 devices'));
    await expect(enablePush()).rejects.toThrow('up to 10 devices');
    expect(created.unsubscribe).toHaveBeenCalledOnce();

    const same = { endpoint: 'https://push.test/same', toJSON: () => ({}), unsubscribe: vi.fn(async () => true) };
    device({ existing: same, subscribe: async () => same });
    vi.mocked(api.pushOn).mockRejectedValueOnce(new Error('offline'));
    await expect(enablePush()).rejects.toThrow('offline');
    expect(same.unsubscribe).not.toHaveBeenCalled();
  });
});

describe('disablePush and testPush', () => {
  it('turns off on the server, then in the browser', async () => {
    const mine = { endpoint: 'https://push.test/mine', unsubscribe: vi.fn(async () => true) };
    device({ existing: mine });
    await disablePush();
    expect(api.pushOff).toHaveBeenCalledWith('https://push.test/mine');
    expect(mine.unsubscribe).toHaveBeenCalledOnce();
  });
  it('reports a test that reached nothing', async () => {
    device({ existing: { endpoint: 'https://push.test/mine', unsubscribe: async () => true } });
    await testPush();
    vi.mocked(api.pushTest).mockResolvedValueOnce({ sent: 0 });
    await expect(testPush()).rejects.toThrow('did not reach');
    device({ existing: null });
    await expect(testPush()).rejects.toThrow('off on this device');
  });
});
