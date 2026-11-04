import { beforeEach, describe, expect, it, vi } from 'vitest';

import { hide, loadHidden, saveHidden, unhide } from './hidden';

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

describe('hidden deals', () => {
  it('starts empty and round-trips', () => {
    expect(loadHidden()).toEqual([]);
    saveHidden(['a', 'b']);
    expect(loadHidden()).toEqual(['a', 'b']);
  });

  it('hides newest first without duplicates, and unhides', () => {
    expect(hide(['a', 'b'], 'c')).toEqual(['c', 'a', 'b']);
    expect(hide(['a', 'b'], 'b')).toEqual(['b', 'a']);
    expect(unhide(['a', 'b'], 'a')).toEqual(['b']);
  });

  it('keeps the list bounded and survives bad stored data', () => {
    saveHidden(Array.from({ length: 400 }, (_, i) => `d${i}`));
    expect(loadHidden()).toHaveLength(300);
    localStorage.setItem('dw.hiddenDeals', '{oops');
    expect(loadHidden()).toEqual([]);
    localStorage.setItem('dw.hiddenDeals', JSON.stringify(['a', 7, null]));
    expect(loadHidden()).toEqual(['a']);
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
    expect(() => saveHidden(['a'])).not.toThrow();
    expect(loadHidden()).toEqual([]);
  });
});
