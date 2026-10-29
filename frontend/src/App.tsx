export function App({
  email,
  onSignOut,
  passkeyUrl,
}: {
  email: string;
  onSignOut: () => void;
  passkeyUrl: string;
}) {
  return (
    <main>
      <h1>Watching</h1>
      <section class="empty">
        <p>Nothing watched yet.</p>
        <p class="muted">Add a product link and you'll get a push notification when its price drops.</p>
      </section>
      <section class="account">
        <p class="muted">Signed in{email ? ` as ${email}` : ''}.</p>
        <a class="button" href={passkeyUrl}>
          Add passkey
        </a>
        <button class="button" type="button" onClick={onSignOut}>
          Sign out
        </button>
      </section>
    </main>
  );
}
