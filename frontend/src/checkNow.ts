import { api } from './api';

export const POLL_MS = 4000; // the checker takes 10-40 seconds
export const MAX_WAIT_MS = 90000; // its own time limit; after that the deals are reloaded anyway

const wait = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));

/** Asks the backend to read the feeds now, then waits until the "last checked" time moves (or MAX_WAIT_MS passes).
 * Never rejects: if a check can't be started (too soon after the last one, offline) it returns at once and the caller just reloads. */
export async function checkNow(alive: () => boolean = () => true, sleep: (ms: number) => Promise<void> = wait): Promise<void> {
  const before = await api.checkNow().catch(() => null);
  if (!before?.started) return;
  for (let waited = 0; waited < MAX_WAIT_MS && alive(); waited += POLL_MS) {
    await sleep(POLL_MS);
    const now = await api.checker().catch(() => null);
    if (now && now.checkedAt !== before.checkedAt) return;
  }
}
