import { AddWatch } from './AddWatch';
import { Nav } from './Nav';
import { Settings } from './Settings';
import { Watching } from './Watching';
import { useRoute } from './router';

export function App({ email, onSignOut, passkeyUrl }: { email: string; onSignOut: () => void; passkeyUrl: string }) {
  const route = useRoute();
  if (route === 'add') return <AddWatch />;
  return (
    <>
      {route === 'settings' ? <Settings email={email} onSignOut={onSignOut} passkeyUrl={passkeyUrl} /> : <Watching />}
      <Nav active={route} />
    </>
  );
}
