import { beforeEach, describe, expect, it, vi } from 'vitest';

import { loadConfig } from './config';

const CONFIG = { apiUrl: 'https://api.test', authUrl: 'https://auth.test', clientId: 'cid', region: 'us-east-2', vapidPublicKey: 'k' };

function memoryStorage(): Storage {
  const data: Record<string, string> = {};
  return {
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
  } as unknown as Storage;
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage());
});

describe('loadConfig', () => {
  it('reads /config.json without the cache and keeps a copy for offline starts', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(CONFIG)));
    vi.stubGlobal('fetch', fetchMock);
    await expect(loadConfig()).resolves.toEqual(CONFIG);
    expect(fetchMock).toHaveBeenCalledWith('/config.json', { cache: 'no-store' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(loadConfig()).resolves.toEqual(CONFIG);
  });

  it('fails when offline on the very first visit', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(loadConfig()).rejects.toThrow('offline');
  });

  it('reports missing settings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })));
    await expect(loadConfig()).rejects.toThrow('App settings are missing');
  });

  it('reports missing settings when the site answers with its HTML page', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<!doctype html><title>app</title>')));
    await expect(loadConfig()).rejects.toThrow('App settings are missing');
  });

  it('reports missing settings when the file holds JSON null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('null')));
    await expect(loadConfig()).rejects.toThrow('App settings are missing');
  });

  it('reports missing settings when a required one is empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...CONFIG, clientId: '' }))));
    await expect(loadConfig()).rejects.toThrow('App settings are missing');
  });

  it('works with blocked storage', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(CONFIG))));
    await expect(loadConfig()).resolves.toEqual(CONFIG);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(loadConfig()).rejects.toThrow('offline');
  });
});
