import { describe, expect, it, vi } from 'vitest';

import { Nav } from './Nav';
import { Settings } from './Settings';

describe('Settings', () => {
  it('links to passkey registration and shows the signed-in email', () => {
    const tree = JSON.stringify(Settings({ email: 'tester', onSignOut: vi.fn(), passkeyUrl: 'https://auth.test/passkeys/add' }));
    expect(tree).toContain('"href":"https://auth.test/passkeys/add"');
    expect(tree).toContain('Add a passkey');
    expect(tree).toContain('tester');
  });
});

describe('Nav', () => {
  it('marks the current tab', () => {
    const tree = JSON.stringify(Nav({ active: 'settings' }));
    expect(tree.match(/"aria-current":"page"/g)).toHaveLength(1);
    expect(tree).toContain('Watching');
    expect(tree).toContain('Settings');
  });
});
