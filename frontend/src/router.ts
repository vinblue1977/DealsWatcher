import { useEffect, useState } from 'preact/hooks';

export type Route = 'watching' | 'add' | 'settings' | 'watch' | 'deals' | 'keywords';
export interface Location {
  route: Route;
  /** The watch id on the 'watch' screen. */
  id: string;
}

const SCREENS: Record<string, Route> = { '#/add': 'add', '#/settings': 'settings', '#/deals': 'deals', '#/keywords': 'keywords' };
const WATCH = /^#\/watch\/([0-9a-f]{12})$/;

/** The screen for a URL hash; anything unknown is the Watching list. */
export function parseRoute(hash: string): Location {
  const watch = WATCH.exec(hash);
  if (watch?.[1]) return { route: 'watch', id: watch[1] };
  return { route: SCREENS[hash] ?? 'watching', id: '' };
}

export const go = (hash: string): void => {
  location.hash = hash;
};

export function useRoute(): Location {
  const [where, setWhere] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const onChange = () => setWhere(parseRoute(location.hash));
    addEventListener('hashchange', onChange);
    return () => removeEventListener('hashchange', onChange);
  }, []);
  return where;
}
