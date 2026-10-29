import { describe, expect, it, vi } from 'vitest';

import { App } from './App';

describe('App', () => {
  it('links to passkey registration and shows the signed-in email', () => {
    const tree = JSON.stringify(App({ email: 'tester', onSignOut: vi.fn(), passkeyUrl: 'https://auth.test/passkeys/add' }));
    expect(tree).toContain('"href":"https://auth.test/passkeys/add"');
    expect(tree).toContain('Add passkey');
    expect(tree).toContain('tester');
  });

  it('shows the empty state', () => {
    expect(JSON.stringify(App({ email: '', onSignOut: vi.fn(), passkeyUrl: '#' }))).toContain('Nothing watched yet.');
  });
});
