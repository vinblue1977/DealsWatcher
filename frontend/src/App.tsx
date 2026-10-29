import { AddWatch } from './AddWatch';
import { Detail } from './Detail';
import { Nav } from './Nav';
import { Settings } from './Settings';
import { Watching } from './Watching';
import { useRoute } from './router';

export function App({ email, onSignOut, passkeyUrl }: { email: string; onSignOut: () => void; passkeyUrl: string }) {
  const { route, id } = useRoute();
  if (route === 'add') return <AddWatch />;
  return (
    <>
      {route === 'settings' ? <Settings email={email} onSignOut={onSignOut} passkeyUrl={passkeyUrl} /> : route === 'watch' ? <Detail key={id} id={id} /> : <Watching />}
      <Nav active={route === 'watch' ? 'watching' : route} />
    </>
  );
}
