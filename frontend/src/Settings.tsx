import { Notifications } from './Notifications';
import { QuietHours } from './QuietHours';

export function Settings({ email, onSignOut, passkeyUrl }: { email: string; onSignOut: () => void; passkeyUrl: string }) {
  return (
    <main class="screen">
      <header class="top">
        <h1>Settings</h1>
      </header>
      <Notifications />
      <QuietHours />
      <section class="group">
        <div class="setting">
          <span>Signed in</span>
          <span class="muted">{email || 'your account'}</span>
        </div>
        <a class="setting" href={passkeyUrl}>
          <span>Add a passkey</span>
          <span class="muted" aria-hidden="true">
            ›
          </span>
        </a>
      </section>
      <button class="button wide" type="button" onClick={onSignOut}>
        Sign out
      </button>
    </main>
  );
}
