export function App({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  return (
    <main>
      <h1>Watching</h1>
      <p class="muted">Signed in{email ? ` as ${email}` : ''}. Screens follow docs/design.</p>
      <button class="button" type="button" onClick={onSignOut}>
        Sign out
      </button>
    </main>
  );
}
