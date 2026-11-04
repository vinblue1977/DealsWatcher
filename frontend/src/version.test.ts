import { describe, expect, it } from 'vitest';

import { bundleIn, isStale } from './version';

const page = (file: string) =>
  `<head><script type="module" crossorigin src="/assets/${file}"></script><link rel="stylesheet" href="/assets/index-x.css"></head>`;

describe('bundleIn', () => {
  it('finds the app bundle and nothing else', () => {
    expect(bundleIn(page('index-_bneTHsf.js'))).toBe('/assets/index-_bneTHsf.js');
    expect(bundleIn('<script src="https://evil.test/assets/index-a.js"></script>')).toBeNull();
    expect(bundleIn('<p>no script</p>')).toBeNull();
  });
});

describe('isStale', () => {
  it('is true only when a different bundle is now served', () => {
    const running = '/assets/index-old.js';
    expect(isStale(running, page('index-new.js'))).toBe(true);
    expect(isStale(running, page('index-old.js'))).toBe(false);
    expect(isStale(running, '<html>error page</html>')).toBe(false); // an unreadable answer never reloads
    expect(isStale(null, page('index-new.js'))).toBe(false);
  });
});
