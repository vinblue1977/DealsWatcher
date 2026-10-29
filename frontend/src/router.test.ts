import { describe, expect, it } from 'vitest';

import { parseRoute } from './router';

describe('parseRoute', () => {
  it('maps hashes to screens and defaults to Watching', () => {
    expect(parseRoute('#/add')).toEqual({ route: 'add', id: '' });
    expect(parseRoute('#/settings')).toEqual({ route: 'settings', id: '' });
    expect(parseRoute('#/deals')).toEqual({ route: 'deals', id: '' });
    expect(parseRoute('#/keywords')).toEqual({ route: 'keywords', id: '' });
    expect(parseRoute('')).toEqual({ route: 'watching', id: '' });
    expect(parseRoute('#/')).toEqual({ route: 'watching', id: '' });
    expect(parseRoute('#/nope')).toEqual({ route: 'watching', id: '' });
    expect(parseRoute('#/__proto__')).toEqual({ route: 'watching', id: '' });
  });
  it('reads a watch id only when it has the shape the API issues', () => {
    expect(parseRoute('#/watch/0123456789ab')).toEqual({ route: 'watch', id: '0123456789ab' });
    for (const bad of ['#/watch/', '#/watch/XYZ', '#/watch/0123456789abc', '#/watch/0123456789ab/x', '#/watch/../x']) {
      expect(parseRoute(bad).route).toBe('watching');
    }
  });
});
