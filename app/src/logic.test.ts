import { describe, expect, it } from 'vitest';
import { browse, EMPTY_BROWSE, mergeMarks, migrateMarks, pick, spinPool, todayIso, type SpinContext } from './logic';
import type { Db, Mark, Special } from './types';
import { DEFAULT_SETTINGS } from './types';

const NOW = new Date('2026-03-01T12:00:00Z').getTime();
const sp = (id: string, extra: Partial<Special> = {}): Special => ({
  id, title: id, performers: [id.split('--')[0]], release_date: '2025-06-01', runtime_min: 60, format: 'hour',
  platforms: [{ platform: 'netflix', kind: 'subscription' }], ...extra,
});
const db: Db = {
  version: 1, generated: 'x', comedians: { a: { name: 'Ann' }, b: { name: 'Bo' }, c: { name: 'Cy' } }, platforms: {}, redirects: {},
  specials: [
    sp('a--one'),
    sp('b--two', { platforms: [{ platform: 'youtube', kind: 'free' }], runtime_min: 30, format: 'half_hour' }),
    sp('c--three', { release_date: '2026-02-15' }),
    sp('a--future', { release_date: '2026-09-01' }),
  ],
};
const mark = (id: string, m: Partial<Mark>): [string, Mark] => [id, { id, status: null, watches: [], updatedAt: 1, ...m }];
const ctx = (over: Partial<SpinContext> = {}): SpinContext => ({
  db, marks: new Map(), follows: new Set(), spins: [], settings: DEFAULT_SETTINGS, now: NOW, ...over,
});

describe('spin pool', () => {
  it('excludes unreleased and applies the default weights', () => {
    const pool = spinPool(ctx({
      marks: new Map([mark('a--one', { status: 'want' })]),
      follows: new Set(['b']),
    }));
    const w = Object.fromEntries(pool.map((p) => [p.special.id, p.weight]));
    expect(w).toEqual({ 'a--one': 3, 'b--two': 2, 'c--three': 1.5 });
  });

  it('honors pool, runtime, availability and skips', () => {
    const marks = new Map([mark('a--one', { status: 'seen', watches: ['2026-02-28'] }), mark('c--three', { status: 'want' })]);
    expect(spinPool(ctx({ marks }), { ...DEFAULT_SETTINGS.spin, pool: 'want' }).map((p) => p.special.id)).toEqual(['c--three']);
    expect(spinPool(ctx({ marks })).map((p) => p.special.id)).toEqual(['b--two', 'c--three']);
    expect(spinPool(ctx(), { ...DEFAULT_SETTINGS.spin, maxRuntime: 45 }).map((p) => p.special.id)).toEqual(['b--two']);
    expect(spinPool(ctx(), { ...DEFAULT_SETTINGS.spin, availability: 'free' }).map((p) => p.special.id)).toEqual(['b--two']);
    const mine = ctx({ settings: { ...DEFAULT_SETTINGS, services: ['netflix'] } });
    expect(spinPool(mine, { ...DEFAULT_SETTINGS.spin, availability: 'mine' }).length).toBe(3); // free counts too
    // Skip comedians watched recently: 'a' was watched yesterday, so a--one is out even in "everything".
    const everything = { ...DEFAULT_SETTINGS.spin, pool: 'everything' as const, skipRecentComedianDays: 7 };
    expect(spinPool(ctx({ marks }), everything).map((p) => p.special.id)).toEqual(['b--two', 'c--three']);
    const skipped = spinPool(ctx({ spins: [{ specialId: 'b--two', at: NOW - 1000, action: 'not_tonight' }] }));
    expect(skipped.find((p) => p.special.id === 'b--two')!.weight).toBe(0.5);
  });

  it('picks by weight and can avoid the last pick', () => {
    const pool = [{ special: db.specials[0], weight: 1, why: [] }, { special: db.specials[1], weight: 3, why: [] }];
    expect(pick(pool, () => 0.2)!.special.id).toBe('a--one');
    expect(pick(pool, () => 0.3)!.special.id).toBe('b--two');
    expect(pick(pool, () => 0, 'a--one')!.special.id).toBe('b--two');
    expect(pick([], () => 0)).toBeNull();
  });
});

describe('redirects', () => {
  it('moves marks to the surviving record and merges them', () => {
    const { keep, removed } = migrateMarks([
      { id: 'old', status: 'want', watches: [], updatedAt: 1, notes: 'from friend' },
      { id: 'new', status: 'seen', watches: ['2026-01-01'], updatedAt: 2, rating: 4 },
      { id: 'other', status: 'want', watches: [], updatedAt: 1 },
    ], { old: 'mid', mid: 'new' });
    expect(removed).toEqual(['old']);
    const n = keep.find((m) => m.id === 'new')!;
    expect(n.status).toBe('seen');
    expect(n.rating).toBe(4);
    expect(n.notes).toBe('from friend');
    expect(keep).toHaveLength(2);
  });

  it('merges watch dates without duplicates', () => {
    const m = mergeMarks({ id: 'x', status: 'seen', watches: ['2026-01-01'], updatedAt: 1 },
      { id: 'x', status: null, watches: ['2026-01-01', '2026-02-01'], updatedAt: 2 });
    expect(m.watches).toEqual(['2026-01-01', '2026-02-01']);
    expect(m.status).toBe('seen');
  });
});

describe('browse', () => {
  it('searches names and titles and filters', () => {
    const today = todayIso(new Date(NOW));
    expect(browse(db, new Map(), { ...EMPTY_BROWSE, q: 'bo' }, today).map((s) => s.id)).toEqual(['b--two']);
    expect(browse(db, new Map(), { ...EMPTY_BROWSE, includeUpcoming: false }, today)).toHaveLength(3);
    expect(browse(db, new Map(), { ...EMPTY_BROWSE, format: 'half_hour' }, today)).toHaveLength(1);
    expect(browse(db, new Map([mark('a--one', { status: 'seen' })]), { ...EMPTY_BROWSE, unseenOnly: true }, today)).toHaveLength(3);
  });
});
