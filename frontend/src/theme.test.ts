import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { applyTheme, savedTheme, setTheme } from './theme';

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

function fakeDocument() {
  const meta: Record<string, string> = { 'meta[name="theme-color"]': '', 'meta[name="color-scheme"]': '' };
  return {
    meta,
    documentElement: { dataset: {} as Record<string, string>, style: { colorScheme: '' } },
    querySelector: (selector: string) => ({ setAttribute: (_: string, v: string) => (meta[selector] = v) }),
  };
}

describe('theme', () => {
  let phoneLight = false;
  let doc: ReturnType<typeof fakeDocument>;
  beforeEach(() => {
    phoneLight = false;
    doc = fakeDocument();
    vi.stubGlobal('document', doc);
    // styles.css decides: here the phone prefers dark unless the test says otherwise
    vi.stubGlobal('getComputedStyle', () => ({
      getPropertyValue: () => {
        const { theme } = doc.documentElement.dataset;
        return theme === 'light' || (theme === 'auto' && phoneLight) ? 'white' : 'black';
      },
    }));
    vi.stubGlobal('localStorage', memoryStorage());
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => undefined }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('defaults to dark and ignores junk', () => {
    expect(savedTheme()).toBe('dark');
    localStorage.setItem('dw.theme', 'purple');
    expect(savedTheme()).toBe('dark');
  });

  it('remembers a choice and shows it', () => {
    setTheme('light');
    expect(savedTheme()).toBe('light');
    expect(doc.documentElement.dataset.theme).toBe('light');
    expect(doc.documentElement.style.colorScheme).toBe('light');
    expect(doc.meta['meta[name="theme-color"]']).toBe('white');
  });

  it('auto follows the phone', () => {
    phoneLight = true;
    applyTheme('auto');
    expect(doc.documentElement.dataset.theme).toBe('auto');
    expect(doc.documentElement.style.colorScheme).toBe('light dark');
    expect(doc.meta['meta[name="theme-color"]']).toBe('white');
  });

  it('still shows the choice when storage is blocked', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    });
    expect(savedTheme()).toBe('dark');
    setTheme('light');
    expect(doc.documentElement.dataset.theme).toBe('light');
  });
});
