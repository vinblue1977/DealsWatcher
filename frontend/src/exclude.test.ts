import { describe, expect, it } from 'vitest';

import { candidateWords, withExclusion } from './exclude';

describe('candidateWords', () => {
  it('lists title words not in the keyword, once each, in order', () => {
    expect(candidateWords('Samsung 55" OLED TV with Wall Mount for $499', 'TV')).toEqual(['samsung', 'oled', 'wall', 'mount']);
    expect(candidateWords('Mount mount MOUNT kit', 'tv')).toEqual(['mount', 'kit']);
  });
  it('skips filler, short words, numbers and words starting with a digit', () => {
    expect(candidateWords('The 4K TV is on sale for 50 off', 'tv')).toEqual([]);
  });
  it('treats apostrophes and hyphens as word breaks', () => {
    expect(candidateWords("Men's T-Shirt", 'shirt')).toEqual(['men']);
  });
  it('leaves out plurals of the keyword, which the matcher treats as the same word', () => {
    expect(candidateWords('Sony Headphones and Box', 'headphone')).toEqual(['sony', 'box']);
    expect(candidateWords('Wired Headphone Sale', 'headphones')).toEqual(['wired']);
  });
  it('gives at most 8', () => {
    expect(candidateWords('aaa bbb ccc ddd eee fff ggg hhh iii jjj', 'x')).toHaveLength(8);
  });
});

describe('withExclusion', () => {
  it('adds -word', () => expect(withExclusion(' TV ', 'mount')).toBe('TV -mount'));
  it('refuses a keyword over 60 characters', () => expect(withExclusion('x'.repeat(58), 'ab')).toBeNull());
});
