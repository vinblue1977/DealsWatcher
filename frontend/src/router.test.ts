import { describe, expect, it } from 'vitest';

import { parseRoute } from './router';

describe('parseRoute', () => {
  it('maps hashes to screens and defaults to Watching', () => {
    expect(parseRoute('#/add')).toBe('add');
    expect(parseRoute('#/settings')).toBe('settings');
    expect(parseRoute('')).toBe('watching');
    expect(parseRoute('#/')).toBe('watching');
    expect(parseRoute('#/nope')).toBe('watching');
    expect(parseRoute('#/__proto__')).toBe('watching');
  });
});
