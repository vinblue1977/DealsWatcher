import { beforeEach, describe, expect, it, vi } from 'vitest';

import { markSeen, unseenIds } from './seen';

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

describe('seen deals', () => {
  it('marks nothing new on the very first visit', () => {
    expect(unseenIds(['a', 'b']).size).toBe(0);
  });

  it('reports only deals that arrived since the last visit', () => {
    markSeen(['a', 'b']);
    expect([...unseenIds(['c', 'a', 'b'])]).toEqual(['c']);
    markSeen(['c', 'a', 'b']);
    expect(unseenIds(['c', 'a', 'b']).size).toBe(0);
  });

  it('keeps the list bounded and survives bad stored data', () => {
    markSeen(Array.from({ length: 400 }, (_, i) => `d${i}`));
    expect(JSON.parse(localStorage.getItem('dw.seenDeals') ?? '[]')).toHaveLength(300);
    localStorage.setItem('dw.seenDeals', '{oops');
    expect(unseenIds(['x']).size).toBe(0);
  });

  it('does not throw when storage is blocked', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    });
    expect(() => markSeen(['a'])).not.toThrow();
    expect(unseenIds(['a']).size).toBe(0);
  });
});
