import { describe, expect, it } from 'vitest';

import { ago, initials, money, parseMaxPrice, parseName, parsePrice, retailerFor, ruleLine, safeLink, summary, targetMoney, visibleWatches, watchState } from './format';
import type { Rule, Watch } from './types';

const watch = (over: Partial<Watch> = {}): Watch => ({
  id: 'abc',
  url: 'https://www.target.com/p/x',
  urlHash: 'h',
  retailer: 'Target',
  title: 'Thing',
  targetPrice: 199,
  alertOnDrop: true,
  paused: false,
  status: 'ok',
  createdAt: '2026-10-28T12:00:00Z',
  ...over,
});

describe('retailerFor', () => {
  it('names supported stores, including subdomains', () => {
    expect(retailerFor('https://www.target.com/p/x')).toBe('Target');
    expect(retailerFor(' https://bestbuy.com/site/y ')).toBe('Best Buy');
  });
  it.each([
    'http://www.target.com/p/x',
    `https://user:pw${'@'}www.target.com/`, // credentials in the link
    'https://nottarget.com/',
    'https://target.com.evil.test/',
    'https://www.amazon.com/dp/1',
    'not a url',
    '',
  ])('refuses %s', (link) => {
    expect(retailerFor(link)).toBeNull();
  });
});

describe('prices', () => {
  it('formats money and whole-dollar targets', () => {
    expect(money(1096.99)).toBe('$1,096.99');
    expect(targetMoney(199)).toBe('$199');
    expect(targetMoney(199.5)).toBe('$199.50');
  });
  it.each([
    ['199', 199],
    ['$1,099.50', 1099.5],
    ['0.99', 0.99],
  ])('parses %s', (text, value) => {
    expect(parsePrice(text)).toBe(value);
  });
  it.each(['', '0', '-5', '1e3', '12.345', '100000', 'abc', '1.', '1,99', '1 99', '19,9', '1,0999'])('rejects %j', (text) => {
    expect(parsePrice(text)).toBeNull();
  });
});

describe('initials', () => {
  it('abbreviates store names', () => {
    expect(initials('Best Buy')).toBe('BB');
    expect(initials('Target')).toBe('T');
    expect(initials('')).toBe('?');
  });
});

describe('ago', () => {
  const now = Date.parse('2026-10-28T12:00:00Z');
  it('speaks in minutes, hours and days', () => {
    expect(ago('2026-10-28T12:00:00Z', now)).toBe('just now');
    expect(ago('2026-10-28T11:54:00Z', now)).toBe('6 min ago');
    expect(ago('2026-10-28T09:00:00Z', now)).toBe('3 h ago');
    expect(ago('2026-10-20T12:00:00Z', now)).toBe('8 days ago');
    expect(ago('not a time', now)).toBe('a while ago');
  });
});

describe('watchState', () => {
  it('covers each situation', () => {
    expect(watchState(watch({ paused: true }))).toMatchObject({ label: 'Paused', tone: 'muted' });
    expect(watchState(watch({ status: 'blocked' }))).toMatchObject({ blocked: true, tone: 'warn' });
    expect(watchState(watch({ status: 'pending' }))).toMatchObject({ label: 'Waiting for first check' });
    expect(watchState(watch({ lastPrice: 199 }))).toMatchObject({ label: 'At target', atTarget: true, tone: 'good' });
    expect(watchState(watch({ lastPrice: 229 }))).toMatchObject({ label: '$30 above target', atTarget: false });
    expect(watchState(watch({ lastPrice: 229.99, targetPrice: 199.99 })).label).toBe('$30 above target'); // no float noise
  });
});

describe('summary', () => {
  const now = Date.parse('2026-10-28T12:00:00Z');
  it('counts items and shows the newest check', () => {
    expect(summary([], now)).toBe('0 items');
    expect(summary([watch()], now)).toBe('1 item');
    const two = [watch({ lastChecked: '2026-10-28T11:00:00Z' }), watch({ lastChecked: '2026-10-28T11:54:00Z' })];
    expect(summary(two, now)).toBe('2 items · checked 6 min ago');
    expect(summary([watch({ lastChecked: 'garbage' })], now)).toBe('1 item');
  });
});

describe('deal feed links', () => {
  it('keeps plain https links only', () => {
    // the script link is built in pieces so the linter's no-script-url rule doesn't flag the test data
    expect(safeLink('https://slickdeals.net/f/1')).toBe('https://slickdeals.net/f/1');
    for (const bad of [`${'java'}script:alert(1)`, 'data:text/html,x', 'http://slickdeals.net/', `https://u:p${'@'}slickdeals.net/`, 'not a url', '', undefined]) {
      expect(safeLink(bad)).toBeNull();
    }
  });
});

describe('ruleLine', () => {
  const rule = (over: Partial<Rule> = {}): Rule => ({ id: 'a', keyword: 'OLED', maxPrice: 1200, sources: ['dealnews'], enabled: true, createdAt: '', ...over });
  it('describes price, feed and paused state', () => {
    expect(ruleLine(rule())).toBe('Under $1,200 · Dealnews');
    expect(ruleLine(rule({ maxPrice: null }))).toBe('Any price · Dealnews');
    expect(ruleLine(rule({ enabled: false }))).toBe('Under $1,200 · Dealnews · Paused');
  });
  it('names only the feeds that are read, even if an older rule lists more', () => {
    expect(ruleLine(rule({ sources: ['dealnews', 'reddit', 'slickdeals'] }))).toBe('Under $1,200 · Dealnews');
    expect(ruleLine(rule({ sources: ['reddit'] }))).toBe('Under $1,200 · No active feed');
  });
});

describe('visibleWatches', () => {
  const list = [watch({ id: 'a', lastPrice: 150 }), watch({ id: 'b', lastPrice: 300 }), watch({ id: 'c', status: 'blocked' })];
  it('filters by state', () => {
    expect(visibleWatches(list, 'all')).toHaveLength(3);
    expect(visibleWatches(list, 'target').map((w) => w.id)).toEqual(['a']);
    expect(visibleWatches(list, 'attention').map((w) => w.id)).toEqual(['c']);
  });
});

describe('parseName', () => {
  it('trims the name', () => expect(parseName('  TV in the den  ')).toBe('TV in the den'));
  it.each(['', '   '])('refuses %j', (text) => expect(parseName(text)).toBeNull());
  it('counts characters, not UTF-16 units, against the 120 limit', () => {
    expect(parseName('😀'.repeat(120))).toBe('😀'.repeat(120));
    expect(parseName('a'.repeat(121))).toBeNull();
  });
});

describe('parseMaxPrice', () => {
  it('reads an amount', () => expect(parseMaxPrice('$1,200')).toBe(1200));
  it.each(['', '  '])('treats %j as any price', (text) => expect(parseMaxPrice(text)).toBeNull());
  it.each(['abc', '0', '-5', '1,99'])('refuses %j', (text) => expect(parseMaxPrice(text)).toBeUndefined());
});
