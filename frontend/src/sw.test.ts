import { describe, expect, it, vi } from 'vitest';

import worker from '../public/sw.js?raw';

type Handler = (event: Record<string, unknown>) => void;

/** Runs public/sw.js against a fake worker scope and returns its handlers. */
function load(windows: { url: string; visibilityState: string; focus: () => Promise<void>; postMessage: (message: unknown) => void }[] = []) {
  const handlers: Record<string, Handler> = {};
  const shown: { title: string; options: { body: string; data: { url: string } } }[] = [];
  const opened: string[] = [];
  const scope = {
    addEventListener: (type: string, fn: Handler) => (handlers[type] = fn),
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn(), matchAll: async () => windows, openWindow: async (url: string) => void opened.push(url) },
    registration: { showNotification: async (title: string, options: never) => void shown.push({ title, options }) },
    location: { origin: 'https://app.test' },
  };
  new Function('self', worker)(scope); // eslint-disable-line no-new-func
  return { handlers, shown, opened };
}

const push = (payload: unknown) => {
  const waits: Promise<unknown>[] = [];
  return {
    event: { data: { json: () => (payload instanceof Error ? (() => { throw payload; })() : payload) }, waitUntil: (p: Promise<unknown>) => waits.push(p) },
    done: () => Promise.all(waits),
  };
};

describe('service worker', () => {
  it('shows a notification from the pushed data', async () => {
    const { handlers, shown } = load();
    const p = push({ title: 'Price hit your target', body: 'LG C5 is $1,096.99', url: '/#/watch/0123456789ab' });
    handlers['push']?.(p.event);
    await p.done();
    expect(shown[0]).toMatchObject({ title: 'Price hit your target', options: { body: 'LG C5 is $1,096.99', data: { url: '/#/watch/0123456789ab' } } });
  });

  it('survives bad payloads and long text', async () => {
    const { handlers, shown } = load();
    for (const payload of [new Error('not json'), null, 'text', { title: 7, url: 3 }, { title: 'x'.repeat(500) }]) {
      const p = push(payload);
      handlers['push']?.(p.event);
      await p.done();
    }
    expect(shown.map((s) => s.title.length <= 200)).toEqual([true, true, true, true, true]);
    expect(shown[0]?.title).toBe('DealsWatcher');
  });

  it.each(['https://evil.test/', '//evil.test/', `${'java'}script:alert(1)`, '/\\evil.test', 'relative', '/ with space'])('only opens paths inside the app, not %s', async (url) => {
    const { handlers, shown } = load();
    const p = push({ url });
    handlers['push']?.(p.event);
    await p.done();
    expect(shown[0]?.options.data.url).toBe('/');
  });

  it('opens the tapped notification inside the app', async () => {
    const { handlers, opened } = load();
    const waits: Promise<unknown>[] = [];
    handlers['notificationclick']?.({ notification: { close: vi.fn(), data: { url: '/#/deals' } }, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
    expect(opened).toEqual(['/#/deals']);
  });
});


describe('tapping a notification when the app is open', () => {
  const tap = async (handlers: Record<string, Handler>, url: string) => {
    const waits: Promise<unknown>[] = [];
    handlers['notificationclick']?.({ notification: { close: vi.fn(), data: { url } }, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  const win = (over: object = {}) => ({ url: 'https://app.test/', visibilityState: 'hidden', focus: vi.fn(async () => undefined), postMessage: vi.fn(), ...over });

  it('focuses the visible app window and asks it to move to the page, without reloading it', async () => {
    const hidden = win();
    const visible = win({ visibilityState: 'visible' });
    const { handlers, opened } = load([hidden, visible]);
    await tap(handlers, '/#/deals');
    expect(visible.focus).toHaveBeenCalled();
    expect(visible.postMessage).toHaveBeenCalledWith({ type: 'open', url: '/#/deals' });
    expect(hidden.postMessage).not.toHaveBeenCalled();
    expect(opened).toEqual([]);
  });

  it('ignores windows of other sites and opens the app instead', async () => {
    const { handlers, opened } = load([win({ url: 'https://other.test/' })]);
    await tap(handlers, '/#/deals');
    expect(opened).toEqual(['/#/deals']);
  });

  it('opens the app fresh when the window cannot be focused', async () => {
    const { handlers, opened } = load([win({ focus: vi.fn(async () => Promise.reject(new Error('not allowed'))) })]);
    await tap(handlers, '/#/deals');
    expect(opened).toEqual(['/#/deals']);
  });
});
