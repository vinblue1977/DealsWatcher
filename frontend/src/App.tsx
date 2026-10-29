import { AddWatch } from './AddWatch';
import { Deals } from './Deals';
import { Detail } from './Detail';
import { Keywords } from './Keywords';
import { Nav } from './Nav';
import { Settings } from './Settings';
import { Watching } from './Watching';
import { useRoute, type Route } from './router';

function screen(route: Route, id: string, account: { email: string; onSignOut: () => void; passkeyUrl: string }) {
  switch (route) {
    case 'settings':
      return <Settings {...account} />;
    case 'watch':
      return <Detail key={id} id={id} />;
    case 'deals':
      return <Deals />;
    case 'keywords':
      return <Keywords />;
    default:
      return <Watching />;
  }
}

export function App({ email, onSignOut, passkeyUrl }: { email: string; onSignOut: () => void; passkeyUrl: string }) {
  const { route, id } = useRoute();
  if (route === 'add') return <AddWatch />;
  return (
    <>
      {screen(route, id, { email, onSignOut, passkeyUrl })}
      <Nav active={route === 'watch' ? 'watching' : route} />
    </>
  );
}
