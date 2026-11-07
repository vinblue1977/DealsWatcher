export type Theme = 'dark' | 'light' | 'auto';

const KEY = 'dw.theme';
export const THEMES: { value: Theme; label: string }[] = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
  { value: 'auto', label: 'Auto' },
];
const isTheme = (value: unknown): value is Theme => value === 'dark' || value === 'light' || value === 'auto';

/** The saved choice. Dark is the look the app shipped with, so it stays the default; storage can be blocked. */
export function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return isTheme(value) ? value : 'dark';
  } catch {
    return 'dark';
  }
}

/** Shows the look on the page. Auto leaves the choice to the phone's own light/dark setting. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme === 'auto' ? 'light dark' : theme;
  // The browser bar takes the page background, read from the tokens so colours stay in styles.css.
  const background = getComputedStyle(root).getPropertyValue('--bg').trim();
  if (background) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', background);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', theme === 'auto' ? 'light dark' : theme);
}

/** Remembers the choice and shows it. Storage can be full or blocked: then the choice lasts until the app is closed. */
export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
  applyTheme(theme);
}

/** Auto follows the phone while the app is open: call once at start. */
export function watchTheme(): void {
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (savedTheme() === 'auto') applyTheme('auto');
  });
}
