import { useMemo, useState } from 'preact/hooks';
import { data, marks } from '../store';
import { browse, EMPTY_BROWSE, todayIso, type BrowseFilters } from '../logic';
import { route } from '../router';
import { Empty, List } from '../components/ui';
import { missingSpecialUrl } from './Settings';

const PAGE = 60;

export function Browse() {
  const db = data.value!;
  const q = route.value.query;
  const [f, setF] = useState<BrowseFilters>({
    ...EMPTY_BROWSE,
    q: q.get('q') || '',
    platform: q.get('platform') || '',
    comedian: q.get('comedian') || '',
  });
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState(false);
  const upcomingOnly = q.get('upcoming') === '1';
  const today = todayIso();

  const results = useMemo(() => {
    let r = browse(db, marks.value, f, today);
    if (upcomingOnly) r = r.filter((s) => !s.release_date || s.release_date > today);
    return r;
  }, [db, marks.value, f, upcomingOnly]);

  const years = useMemo(
    () => [...new Set(db.specials.map((s) => (s.release_date || '').slice(0, 4)).filter(Boolean))].sort().reverse(),
    [db],
  );
  const platforms = useMemo(() => {
    const used = new Set(db.specials.flatMap((s) => (s.platforms || []).map((p) => p.platform)));
    return [...used].sort((a, b) => (db.platforms[a]?.name || a).localeCompare(db.platforms[b]?.name || b));
  }, [db]);

  const set = (patch: Partial<BrowseFilters>) => {
    setF({ ...f, ...patch });
    setLimit(PAGE);
  };
  const active = [f.platform, f.comedian, f.year, f.format, f.maxRuntime].filter(Boolean).length +
    Number(f.freeOnly) + Number(f.unseenOnly) + Number(!f.includeUpcoming);

  return (
    <div class="page">
      <div class="searchbar">
        <input type="search" placeholder="Search titles and comedians" value={f.q} aria-label="Search"
          onInput={(e) => set({ q: (e.target as HTMLInputElement).value })} />
        <button class={'btn' + (active ? ' on' : '')} onClick={() => setOpen(!open)} aria-expanded={open}>
          Filters{active ? ` (${active})` : ''}
        </button>
      </div>
      {open && (
        <div class="card filters">
          <label>Platform
            <select value={f.platform} onChange={(e) => set({ platform: (e.target as HTMLSelectElement).value })}>
              <option value="">Any</option>
              {platforms.map((p) => <option key={p} value={p}>{db.platforms[p]?.name || p}</option>)}
            </select>
          </label>
          <label>Year
            <select value={f.year} onChange={(e) => set({ year: (e.target as HTMLSelectElement).value })}>
              <option value="">Any</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label>Format
            <select value={f.format} onChange={(e) => set({ format: (e.target as HTMLSelectElement).value })}>
              <option value="">Any</option>
              <option value="hour">Hour</option>
              <option value="half_hour">Half-hour</option>
            </select>
          </label>
          <label>Max runtime
            <select value={f.maxRuntime} onChange={(e) => set({ maxRuntime: (e.target as HTMLSelectElement).value })}>
              <option value="">Any</option>
              {[30, 45, 60, 75, 90].map((m) => <option key={m} value={m}>{m} min</option>)}
            </select>
          </label>
          {f.comedian && (
            <div class="filter-pill">Comedian: {db.comedians[f.comedian]?.name || f.comedian}
              <button class="link" onClick={() => set({ comedian: '' })}>clear</button></div>
          )}
          <label class="check"><input type="checkbox" checked={f.freeOnly} onChange={() => set({ freeOnly: !f.freeOnly })} /> Free only</label>
          <label class="check"><input type="checkbox" checked={f.unseenOnly} onChange={() => set({ unseenOnly: !f.unseenOnly })} /> Unseen only</label>
          <label class="check"><input type="checkbox" checked={f.includeUpcoming} onChange={() => set({ includeUpcoming: !f.includeUpcoming })} /> Include upcoming</label>
          {active > 0 && <button class="link" onClick={() => set({ ...EMPTY_BROWSE, q: f.q })}>Reset filters</button>}
        </div>
      )}
      <p class="muted count">{results.length.toLocaleString()} special{results.length === 1 ? '' : 's'}</p>
      {results.length ? <List items={results.slice(0, limit)} /> : <Empty>No specials match.</Empty>}
      {f.q.trim() && results.length < 3 && missingSpecialUrl() && (
        <p class="muted small center">Missing one?{' '}
          <a href={missingSpecialUrl({ title: `Missing special: ${f.q.trim()}` })!} target="_blank" rel="noopener">Report missing special</a></p>
      )}
      {results.length > limit && <button class="btn wide" onClick={() => setLimit(limit + PAGE)}>Show more</button>}
    </div>
  );
}
