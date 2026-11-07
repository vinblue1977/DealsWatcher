import { useState } from 'preact/hooks';

import { savedTheme, setTheme, THEMES, type Theme } from './theme';

/** Dark, Light, or Auto (follows the phone). Kept on this device only. */
export function Appearance() {
  const [theme, setChoice] = useState<Theme>(savedTheme);
  function pick(next: Theme) {
    setChoice(next);
    setTheme(next);
  }
  return (
    <section class="group">
      <div class="setting">
        <span id="appearance-label">Appearance</span>
        <div class="chips" role="group" aria-labelledby="appearance-label">
          {THEMES.map(({ value, label }) => (
            <button key={value} type="button" aria-pressed={theme === value} class={theme === value ? 'chip on' : 'chip'} onClick={() => pick(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
