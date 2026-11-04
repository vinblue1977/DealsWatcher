const KEY = 'dw.hiddenDeals';
const KEEP = 300; // a little more than the 100 deals the API returns

/** Deal ids the person hid on this device, newest first. Bad or blocked storage reads as nothing hidden. */
export function loadHidden(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string').slice(0, KEEP) : [];
  } catch {
    return [];
  }
}

/** Saves the list (bounded). Storage can be full or blocked: then deals just come back next visit. */
export function saveHidden(ids: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(ids.slice(0, KEEP)));
  } catch {
    /* ignore */
  }
}

export const hide = (ids: string[], id: string): string[] => [id, ...ids.filter((x) => x !== id)];
export const unhide = (ids: string[], id: string): string[] => ids.filter((x) => x !== id);
