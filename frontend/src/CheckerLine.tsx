import { useEffect, useState } from 'preact/hooks';

import { api } from './api';
import { checkerLine } from './format';
import type { CheckerStatus } from './types';

const REFRESH_MS = 5 * 60000; // the checker runs every 30 minutes
const TICK_MS = 60000; // the "x min ago" text and the stale warning are worked out again every minute

/** "Checked 12 min ago": proof the deal checker is alive. Shows nothing while loading or if the status can't be read.
 * With a `label` it is a Settings row instead, drawn only once there is something to show. */
export function CheckerLine({ label }: { label?: string }) {
  const [status, setStatus] = useState<CheckerStatus | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let live = true;
    const load = () =>
      api.checker().then(
        (s) => live && setStatus(s),
        () => undefined, // a nicety: the screen works without it (an old line then ages and turns stale by itself)
      );
    void load();
    const onVisible = () => document.visibilityState === 'visible' && (setNow(Date.now()), void load());
    document.addEventListener('visibilitychange', onVisible);
    const refresh = setInterval(() => void load(), REFRESH_MS);
    const tick = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => {
      live = false;
      document.removeEventListener('visibilitychange', onVisible);
      clearInterval(refresh);
      clearInterval(tick);
    };
  }, []);
  if (!status) return null;
  const { text, stale } = checkerLine(status, now);
  const tone = stale ? 'warn-text' : 'muted';
  return label ? (
    <div class="setting">
      <span>{label}</span>
      <span class={`${tone} small right`}>{text}</span>
    </div>
  ) : (
    <div class={`${tone} small`}>{text}</div>
  );
}
