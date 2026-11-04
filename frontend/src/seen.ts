const KEY = 'dw.seenDeals';
const KEEP = 300; // a little more than the 100 deals the API returns

function read(): string[] | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : null;
  } catch {
    return null;
  }
}

/** Ids of deals the person has not seen on an earlier visit. The first visit ever marks nothing, or everything would be "new". */
export function unseenIds(ids: string[]): Set<string> {
  const seen = read();
  return new Set(seen === null ? [] : ids.filter((id) => !seen.includes(id)));
}

/** Remembers these deals as seen (newest first, bounded). Storage can be full or blocked: then deals just stay "new". */
export function markSeen(ids: string[]): void {
  try {
    const rest = (read() ?? []).filter((id) => !ids.includes(id));
    localStorage.setItem(KEY, JSON.stringify([...ids, ...rest].slice(0, KEEP)));
  } catch {
    /* ignore */
  }
}
