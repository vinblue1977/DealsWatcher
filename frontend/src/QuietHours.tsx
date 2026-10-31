import { useEffect, useRef, useState } from 'preact/hooks';

import { api } from './api';
import { hourLabel } from './format';
import { SwitchButton } from './Switch';
import type { QuietHours as Window } from './types';

const DEFAULT: Window = { start: 22, end: 7 }; // the mockup's 10 PM – 7 AM
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

/** Quiet hours: alerts that arrive inside the window are held and sent when it ends. The checker reads the window in the device's time zone. */
export function QuietHours() {
  const [quiet, setQuiet] = useState<Window | null | undefined>(undefined); // undefined while loading
  const [zone, setZone] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const latest = useRef(0);

  function load() {
    setError('');
    api.settings().then(
      (s) => {
        setQuiet(s.quietHours);
        setZone(s.timeZone);
      },
      (e: Error) => setError(e.message),
    );
  }
  useEffect(load, []);

  async function save(next: Window | null) {
    const mine = ++latest.current;
    setBusy(true);
    setError('');
    try {
      const s = await api.saveQuietHours(next, Intl.DateTimeFormat().resolvedOptions().timeZone);
      if (mine === latest.current) {
        setQuiet(s.quietHours);
        setZone(s.timeZone);
      }
    } catch (e) {
      if (mine === latest.current) {
        setError((e as Error).message);
        setQuiet((q) => q && { ...q }); // draws the menus again at the saved hours
      }
    } finally {
      if (mine === latest.current) setBusy(false);
    }
  }

  const pick = (field: keyof Window) => (e: Event) => {
    if (!quiet) return;
    const next = { ...quiet, [field]: Number((e.currentTarget as HTMLSelectElement).value) };
    if (next.start === next.end) {
      setError('Pick two different hours.');
      setQuiet({ ...quiet }); // draws the menu again at the saved hour
    } else void save(next);
  };
  return (
    <section class="group">
      <div class="setting">
        <div>
          <div id="quiet-label">Quiet hours</div>
          <div class="muted small">{quiet ? 'Alerts wait until the end' : 'Off: alerts arrive any time'}</div>
        </div>
        <SwitchButton on={!!quiet} labelledBy="quiet-label" disabled={busy || quiet === undefined} onChange={(on) => void save(on ? DEFAULT : null)} />
      </div>
      {quiet && (
        <>
          {(['start', 'end'] as const).map((field) => (
            <label class="setting" key={field}>
              <span>{field === 'start' ? 'From' : 'Until'}</span>
              <select class="select" value={quiet[field]} disabled={busy} onChange={pick(field)}>
                {HOURS.map((h) => (
                  <option value={h} key={h}>
                    {hourLabel(h)}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {zone && <p class="muted small note">{`Uses your device's time zone (${zone}).`}</p>}
        </>
      )}
      {error && (
        <p class="error note" role="alert">
          {error}{' '}
          {quiet === undefined && (
            <button class="link" type="button" onClick={load}>
              Try again
            </button>
          )}
        </p>
      )}
    </section>
  );
}
