/** App state: the public database (signals) and your local lists (IndexedDB via Dexie). */
import { computed, signal } from '@preact/signals';
import { local } from './db';
import { migrateMarks, mergeMarks, todayIso, type Backup } from './logic';
import type { Db, Mark, MarkStatus, Settings, SpinEvent } from './types';
import { DEFAULT_SETTINGS } from './types';

export const data = signal<Db | null>(null);
export const dataError = signal<string | null>(null);
export const refreshing = signal(false);
export const marks = signal<Map<string, Mark>>(new Map());
export const follows = signal<Set<string>>(new Set());
export const spins = signal<SpinEvent[]>([]);
export const settings = signal<Settings>(DEFAULT_SETTINGS);
export const persisted = signal<boolean | null>(null);
export const ready = signal(false);

export const specialsById = computed(() => new Map((data.value?.specials || []).map((s) => [s.id, s])));

const DATA_URL = `${import.meta.env.BASE_URL}data/db.json`;

export async function init() {
  const [cached, s, ms, fs, sp] = await Promise.all([
    local.getCachedData(),
    local.getSettings(),
    local.marks.toArray(),
    local.follows.toArray(),
    local.spins.orderBy('at').reverse().limit(500).toArray(),
  ]);
  settings.value = { ...DEFAULT_SETTINGS, ...(s || {}), weights: { ...DEFAULT_SETTINGS.weights, ...(s?.weights || {}) }, spin: { ...DEFAULT_SETTINGS.spin, ...(s?.spin || {}) } };
  marks.value = new Map(ms.map((m) => [m.id, m]));
  follows.value = new Set(fs.map((f) => f.slug));
  spins.value = sp;
  if (cached) await setData(cached);
  ready.value = true;
  refresh(); // new data loads in the background
  if (navigator.storage?.persisted) persisted.value = await navigator.storage.persisted();
}

async function setData(d: Db) {
  data.value = d;
  // Records merged upstream: move your marks to the surviving ID.
  if (d.redirects && Object.keys(d.redirects).length) {
    const all = [...marks.value.values()];
    const { keep, removed } = migrateMarks(all, d.redirects);
    if (removed.length) {
      await local.transaction('rw', local.marks, async () => {
        await local.marks.bulkDelete(removed);
        await local.marks.bulkPut(keep);
      });
      marks.value = new Map(keep.map((m) => [m.id, m]));
    }
  }
  // First launch on this device: pre-follow the comedians marked followed in comedians.yaml.
  if (!settings.value.initialized) {
    const pre = Object.entries(d.comedians).filter(([, c]) => c.followed).map(([slug]) => slug);
    for (const slug of pre) await local.follows.put({ slug, since: Date.now() });
    follows.value = new Set([...follows.value, ...pre]);
    await saveSettings({ ...settings.value, initialized: true });
  }
}

export async function refresh(): Promise<'updated' | 'same' | 'offline'> {
  refreshing.value = true;
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = (await res.json()) as Db;
    dataError.value = null;
    if (data.value?.generated === d.generated) return 'same';
    await local.putCachedData(d);
    await setData(d);
    return 'updated';
  } catch (e) {
    if (!data.value) dataError.value = `Couldn't load the specials database (${(e as Error).message}).`;
    return 'offline';
  } finally {
    refreshing.value = false;
  }
}

async function requestPersist() {
  if (persisted.value === false && navigator.storage?.persist) {
    persisted.value = await navigator.storage.persist();
  }
}

export function getMark(id: string): Mark {
  return marks.value.get(id) || { id, status: null, watches: [], updatedAt: 0 };
}

export async function updateMark(id: string, patch: Partial<Mark>) {
  const m: Mark = { ...getMark(id), ...patch, id, updatedAt: Date.now() };
  const empty = !m.status && !m.rating && !m.notes && !m.watches.length;
  const next = new Map(marks.value);
  if (empty) {
    next.delete(id);
    await local.marks.delete(id);
  } else {
    next.set(id, m);
    await local.marks.put(m);
  }
  marks.value = next;
  requestPersist();
}

export async function setStatus(id: string, status: MarkStatus | null) {
  const m = getMark(id);
  const patch: Partial<Mark> = { status: m.status === status ? null : status };
  if (status === 'seen' && m.status !== 'seen' && !m.watches.length) patch.watches = [todayIso()];
  await updateMark(id, patch);
}

export async function addWatch(id: string, date: string) {
  const m = getMark(id);
  await updateMark(id, { watches: [...m.watches, date].sort(), status: 'seen' });
}

export async function removeWatch(id: string, index: number) {
  const m = getMark(id);
  await updateMark(id, { watches: m.watches.filter((_, i) => i !== index) });
}

export async function toggleFollow(slug: string) {
  const next = new Set(follows.value);
  if (next.has(slug)) {
    next.delete(slug);
    await local.follows.delete(slug);
  } else {
    next.add(slug);
    await local.follows.put({ slug, since: Date.now() });
  }
  follows.value = next;
  requestPersist();
}

export async function logSpin(specialId: string, action: SpinEvent['action']) {
  const e: SpinEvent = { specialId, action, at: Date.now() };
  e.id = await local.spins.add(e);
  spins.value = [e, ...spins.value].slice(0, 500);
}

export async function saveSettings(s: Settings) {
  settings.value = s;
  await local.putSettings(s);
}

// --- backup ---------------------------------------------------------------------

export async function exportBackup(): Promise<Backup> {
  return {
    app: 'specials-tracker',
    version: 1,
    exported: new Date().toISOString(),
    marks: await local.marks.toArray(),
    follows: await local.follows.toArray(),
    spins: await local.spins.toArray(),
    settings: settings.value,
  };
}

export async function importBackup(b: Backup): Promise<{ marks: number; follows: number }> {
  const redirects = data.value?.redirects || {};
  const current = await local.marks.toArray();
  const byId = new Map(current.map((m) => [m.id, m]));
  for (const m of migrateMarks(b.marks, redirects).keep) {
    const e = byId.get(m.id);
    byId.set(m.id, e ? mergeMarks(e, m) : m);
  }
  await local.transaction('rw', [local.marks, local.follows, local.spins, local.kv], async () => {
    await local.marks.bulkPut([...byId.values()]);
    await local.follows.bulkPut(b.follows || []);
    const spinsNoId = (b.spins || []).map(({ id: _id, ...rest }) => rest);
    if (spinsNoId.length) await local.spins.bulkAdd(spinsNoId as SpinEvent[]);
  });
  if (b.settings) await saveSettings({ ...settings.value, ...b.settings, initialized: true });
  marks.value = byId;
  follows.value = new Set([...follows.value, ...(b.follows || []).map((f) => f.slug)]);
  spins.value = await local.spins.orderBy('at').reverse().limit(500).toArray();
  return { marks: b.marks.length, follows: (b.follows || []).length };
}
