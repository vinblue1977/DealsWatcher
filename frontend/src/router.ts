import { useEffect, useState } from 'preact/hooks';

export type Route = 'watching' | 'add' | 'settings';

const ROUTES: Record<string, Route> = { '#/add': 'add', '#/settings': 'settings' };

/** The screen for a URL hash; anything unknown is the Watching list. */
export const parseRoute = (hash: string): Route => ROUTES[hash] ?? 'watching';

export const go = (route: Route): void => {
  location.hash = route === 'watching' ? '#/' : `#/${route}`;
};

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(location.hash));
    addEventListener('hashchange', onChange);
    return () => removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
