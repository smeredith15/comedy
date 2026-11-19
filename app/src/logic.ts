/** Pure logic: filters, availability, Spin weights, redirects, backup. No DOM, no IndexedDB. */
import type { Db, Mark, PlatformLink, Settings, Special, SpinEvent, SpinFilters, Weights } from './types';
import { FREE_KINDS } from './types';

export const DAY = 86_400_000;

export function todayIso(now = new Date()): string {
  const d = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return d.toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(iso + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function isReleased(s: Special, today: string): boolean {
  return !!s.release_date && s.release_date <= today;
}

export function isFree(s: Special): boolean {
  return (s.platforms || []).some((p) => FREE_KINDS.has(p.kind || ''));
}

export function onServices(s: Special, services: string[]): boolean {
  if (!services.length) return false;
  return (s.platforms || []).some((p) => services.includes(p.platform) || FREE_KINDS.has(p.kind || ''));
}

export function watchUrl(s: Special, p: PlatformLink, db: Db): string | null {
  if (p.url) return p.url;
  const info = db.platforms[p.platform];
  if (info?.search_url) {
    const name = s.performers.map((x) => db.comedians[x]?.name || x).join(' ');
    return info.search_url.replace('{q}', encodeURIComponent(`${name} ${s.title}`.trim()));
  }
  if (s.ids?.tmdb) return `https://www.themoviedb.org/movie/${s.ids.tmdb}/watch`;
  return null;
}

export function bestWatch(s: Special, db: Db, services: string[]): { label: string; url: string } | null {
  const ps = [...(s.platforms || [])].sort((a, b) => score(b) - score(a));
  for (const p of ps) {
    const url = watchUrl(s, p, db);
    if (url) return { label: db.platforms[p.platform]?.name || p.platform, url };
  }
  return null;
  function score(p: PlatformLink) {
    return (services.includes(p.platform) ? 2 : 0) + (FREE_KINDS.has(p.kind || '') ? 1 : 0) + (p.url ? 0.5 : 0);
  }
}

export function performerNames(s: Special, db: Db): string {
  return s.performers.map((p) => db.comedians[p]?.name || p).join(', ');
}

export function searchText(s: Special, db: Db): string {
  return `${s.title} ${performerNames(s, db)}`.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
}

export interface BrowseFilters {
  q: string;
  platform: string;
  comedian: string;
  year: string;
  format: string;
  maxRuntime: string;
  freeOnly: boolean;
  unseenOnly: boolean;
  includeUpcoming: boolean;
}

export const EMPTY_BROWSE: BrowseFilters = {
  q: '', platform: '', comedian: '', year: '', format: '', maxRuntime: '',
  freeOnly: false, unseenOnly: false, includeUpcoming: true,
};

export function browse(db: Db, marks: Map<string, Mark>, f: BrowseFilters, today: string): Special[] {
  const q = f.q.trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const terms = q.split(/\s+/).filter(Boolean);
  const max = f.maxRuntime ? Number(f.maxRuntime) : null;
  return db.specials.filter((s) => {
    if (!f.includeUpcoming && !isReleased(s, today)) return false;
    if (f.platform && !(s.platforms || []).some((p) => p.platform === f.platform)) return false;
    if (f.comedian && !s.performers.includes(f.comedian)) return false;
    if (f.year && !(s.release_date || '').startsWith(f.year)) return false;
    if (f.format && s.format !== f.format) return false;
    if (max && (!s.runtime_min || s.runtime_min > max)) return false;
    if (f.freeOnly && !isFree(s)) return false;
    if (f.unseenOnly) {
      const m = marks.get(s.id);
      if (m && (m.status === 'seen' || m.status === 'not_interested' || m.watches.length)) return false;
    }
    if (terms.length) {
      const text = searchText(s, db);
      if (!terms.every((t) => text.includes(t))) return false;
    }
    return true;
  });
}

// --- Spin ---------------------------------------------------------------------

export interface SpinContext {
  db: Db;
  marks: Map<string, Mark>;
  follows: Set<string>;
  spins: SpinEvent[];
  settings: Settings;
  now: number;
}

export interface Weighted {
  special: Special;
  weight: number;
  why: string[];
}

export function seenRecently(ctx: SpinContext, days: number): Set<string> {
  const cutoff = todayIso(new Date(ctx.now - days * DAY));
  const out = new Set<string>();
  const byId = new Map(ctx.db.specials.map((s) => [s.id, s]));
  for (const m of ctx.marks.values()) {
    if (m.watches.some((w) => w >= cutoff)) {
      for (const p of byId.get(m.id)?.performers || []) out.add(p);
    }
  }
  return out;
}

export function spinPool(ctx: SpinContext, f: SpinFilters = ctx.settings.spin): Weighted[] {
  const today = todayIso(new Date(ctx.now));
  const recentCutoff = addDays(today, -90);
  const skipCutoff = ctx.now - 30 * DAY;
  const w: Weights = { ...ctx.settings.weights };
  const skipped = new Map<string, number>();
  for (const e of ctx.spins) {
    if (e.action === 'not_tonight' && e.at >= skipCutoff) skipped.set(e.specialId, (skipped.get(e.specialId) || 0) + 1);
  }
  const avoid = f.skipRecentComedianDays ? seenRecently(ctx, f.skipRecentComedianDays) : new Set<string>();
  const out: Weighted[] = [];
  for (const s of ctx.db.specials) {
    if (!isReleased(s, today)) continue;
    const m = ctx.marks.get(s.id);
    const status = m?.status ?? null;
    if (status === 'not_interested') continue;
    const seen = status === 'seen' || (m?.watches.length ?? 0) > 0;
    if (f.pool === 'want' && status !== 'want') continue;
    if (f.pool === 'unseen' && seen) continue;
    if (f.maxRuntime && (!s.runtime_min || s.runtime_min > f.maxRuntime)) continue;
    if (f.availability === 'free' && !isFree(s)) continue;
    if (f.availability === 'mine' && !onServices(s, ctx.settings.services)) continue;
    const year = Number((s.release_date || '').slice(0, 4));
    if (f.yearFrom && year < f.yearFrom) continue;
    if (f.yearTo && year > f.yearTo) continue;
    if (f.format !== 'any' && s.format !== f.format) continue;
    if (s.performers.some((p) => avoid.has(p))) continue;

    let weight = 1;
    const why: string[] = [];
    if (status === 'want') { weight *= w.want; why.push('on your Want to see list'); }
    if (s.performers.some((p) => ctx.follows.has(p))) { weight *= w.followed; why.push('a comedian you follow'); }
    if ((s.release_date || '') >= recentCutoff) { weight *= w.recent; why.push('new in the last 90 days'); }
    if (skipped.has(s.id)) { weight *= w.skipped ** skipped.get(s.id)!; why.push('you skipped it recently'); }
    out.push({ special: s, weight, why });
  }
  return out;
}

export function pick(pool: Weighted[], rand: () => number = Math.random, avoidId?: string): Weighted | null {
  const candidates = pool.length > 1 && avoidId ? pool.filter((p) => p.special.id !== avoidId) : pool;
  const total = candidates.reduce((a, p) => a + p.weight, 0);
  if (!candidates.length || total <= 0) return null;
  let r = rand() * total;
  for (const p of candidates) {
    r -= p.weight;
    if (r < 0) return p;
  }
  return candidates[candidates.length - 1];
}

// --- Redirects & backup ---------------------------------------------------------

export function resolveId(id: string, redirects: Record<string, string>): string {
  const seen = new Set<string>();
  while (redirects[id] && !seen.has(id)) {
    seen.add(id);
    id = redirects[id];
  }
  return id;
}

/** Merge two marks for the same special (after a redirect, or on import). */
export function mergeMarks(a: Mark, b: Mark): Mark {
  const [newer, older] = a.updatedAt >= b.updatedAt ? [a, b] : [b, a];
  const rank = (s: Mark['status']) => (s === 'seen' ? 3 : s === 'want' ? 2 : s === 'not_interested' ? 1 : 0);
  return {
    id: newer.id,
    status: rank(newer.status) >= rank(older.status) ? newer.status : older.status,
    rating: newer.rating ?? older.rating,
    notes: [older.notes, newer.notes].filter(Boolean).filter((v, i, arr) => arr.indexOf(v) === i).join('\n') || undefined,
    watches: [...new Set([...older.watches, ...newer.watches])].sort(),
    updatedAt: Math.max(a.updatedAt, b.updatedAt),
  };
}

/** Marks whose special was merged into another record move to the survivor. */
export function migrateMarks(marks: Mark[], redirects: Record<string, string>): { keep: Mark[]; removed: string[] } {
  const out = new Map<string, Mark>();
  const removed: string[] = [];
  for (const m of marks) {
    const target = resolveId(m.id, redirects);
    if (target !== m.id) removed.push(m.id);
    const moved = { ...m, id: target };
    const existing = out.get(target);
    out.set(target, existing ? mergeMarks(existing, moved) : moved);
  }
  return { keep: [...out.values()], removed };
}

export interface Backup {
  app: 'specials-tracker';
  version: 1;
  exported: string;
  marks: Mark[];
  follows: { slug: string; since: number }[];
  spins: SpinEvent[];
  settings: Settings;
}

export function parseBackup(text: string): Backup {
  const b = JSON.parse(text);
  if (b?.app !== 'specials-tracker' || !Array.isArray(b.marks)) throw new Error('Not a Specials Tracker backup file');
  return b as Backup;
}
