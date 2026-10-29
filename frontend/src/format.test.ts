import { describe, expect, it } from 'vitest';

import { ago, initials, money, parsePrice, retailerFor, summary, targetMoney, watchState } from './format';
import type { Watch } from './types';

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
    'https://user:pw@www.target.com/',
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
  it.each(['', '0', '-5', '1e3', '12.345', '100000', 'abc', '1.'])('rejects %j', (text) => {
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
  });
});

describe('watchState', () => {
  it('covers each situation', () => {
    expect(watchState(watch({ paused: true }))).toMatchObject({ label: 'Paused', tone: 'muted' });
    expect(watchState(watch({ status: 'blocked' }))).toMatchObject({ blocked: true, tone: 'warn' });
    expect(watchState(watch({ status: 'pending' }))).toMatchObject({ label: 'Waiting for first check' });
    expect(watchState(watch({ lastPrice: 199 }))).toMatchObject({ label: 'At target', atTarget: true, tone: 'good' });
    expect(watchState(watch({ lastPrice: 229 }))).toMatchObject({ label: '$30 above target', atTarget: false });
  });
});

describe('summary', () => {
  const now = Date.parse('2026-10-28T12:00:00Z');
  it('counts items and shows the newest check', () => {
    expect(summary([], now)).toBe('0 items');
    expect(summary([watch()], now)).toBe('1 item');
    const two = [watch({ lastChecked: '2026-10-28T11:00:00Z' }), watch({ lastChecked: '2026-10-28T11:54:00Z' })];
    expect(summary(two, now)).toBe('2 items · checked 6 min ago');
  });
});
