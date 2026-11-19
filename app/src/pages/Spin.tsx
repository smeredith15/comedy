import { useMemo, useState } from 'preact/hooks';
import { data, follows, logSpin, marks, saveSettings, setStatus, settings, spins } from '../store';
import { pick, spinPool, type Weighted } from '../logic';
import { href } from '../router';
import { formatDate, PlatformChips, runtimeLabel, WatchButton } from '../components/ui';
import type { SpinFilters } from '../types';

export function Spin() {
  const db = data.value!;
  const f = settings.value.spin;
  const [result, setResult] = useState<Weighted | null>(null);
  const [rolling, setRolling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const pool = useMemo(
    () => spinPool({ db, marks: marks.value, follows: follows.value, spins: spins.value, settings: settings.value, now: Date.now() }),
    [db, marks.value, follows.value, spins.value, settings.value],
  );

  const setF = (patch: Partial<SpinFilters>) => saveSettings({ ...settings.value, spin: { ...f, ...patch } });

  const spin = () => {
    setMessage(null);
    const p = pick(pool, Math.random, result?.special.id);
    if (!p) {
      setResult(null);
      setMessage('Nothing matches these settings. Loosen a filter and spin again.');
      return;
    }
    setRolling(true);
    setTimeout(() => { setResult(p); setRolling(false); logSpin(p.special.id, 'shown'); }, 450);
  };

  const notTonight = async () => {
    if (!result) return;
    await logSpin(result.special.id, 'not_tonight');
    spin();
  };
  const markSeen = async () => {
    if (!result) return;
    await setStatus(result.special.id, 'seen');
    await logSpin(result.special.id, 'seen');
    setMessage(`Marked “${result.special.title}” as seen.`);
    setResult(null);
  };

  const noServices = f.availability === 'mine' && settings.value.services.length === 0;

  return (
    <div class="page spin">
      <div class="card spin-settings">
        <label>Pool
          <select value={f.pool} onChange={(e) => setF({ pool: (e.target as HTMLSelectElement).value as SpinFilters['pool'] })}>
            <option value="want">Want to see</option>
            <option value="unseen">Any unseen</option>
            <option value="everything">Everything</option>
          </select>
        </label>
        <label>I have
          <select value={f.maxRuntime ?? ''} onChange={(e) => { const v = (e.target as HTMLSelectElement).value; setF({ maxRuntime: v ? Number(v) : null }); }}>
            <option value="">Any amount of time</option>
            {[30, 45, 60, 75, 90].map((m) => <option key={m} value={m}>{m} minutes</option>)}
          </select>
        </label>
        <label>Availability
          <select value={f.availability} onChange={(e) => setF({ availability: (e.target as HTMLSelectElement).value as SpinFilters['availability'] })}>
            <option value="mine">Only my services</option>
            <option value="free">Free only</option>
            <option value="any">Anything</option>
          </select>
        </label>
        <details class="more-filters">
          <summary>More filters</summary>
          <div class="grid2">
            <label>From year
              <input type="number" inputMode="numeric" placeholder="any" value={f.yearFrom ?? ''} min={1950} max={2100}
                onChange={(e) => { const v = (e.target as HTMLInputElement).value; setF({ yearFrom: v ? Number(v) : null }); }} />
            </label>
            <label>To year
              <input type="number" inputMode="numeric" placeholder="any" value={f.yearTo ?? ''} min={1950} max={2100}
                onChange={(e) => { const v = (e.target as HTMLInputElement).value; setF({ yearTo: v ? Number(v) : null }); }} />
            </label>
            <label>Format
              <select value={f.format} onChange={(e) => setF({ format: (e.target as HTMLSelectElement).value as SpinFilters['format'] })}>
                <option value="any">Any</option>
                <option value="hour">Hour</option>
                <option value="half_hour">Half-hour</option>
              </select>
            </label>
            <label>Skip comedians I watched in the last
              <select value={f.skipRecentComedianDays ?? ''} onChange={(e) => { const v = (e.target as HTMLSelectElement).value; setF({ skipRecentComedianDays: v ? Number(v) : null }); }}>
                <option value="">(don't skip)</option>
                {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </label>
          </div>
        </details>
        {noServices && <p class="warn">You haven't picked your services yet. <a href={href.settings()}>Choose them in Settings</a>. Free specials still count.</p>}
        <p class="muted small">{pool.length.toLocaleString()} special{pool.length === 1 ? '' : 's'} in the pool</p>
      </div>

      {!result && (
        <button class={'spin-button' + (rolling ? ' rolling' : '')} onClick={spin} disabled={rolling || pool.length === 0}>
          {rolling ? '…' : 'Spin'}
        </button>
      )}
      {message && <p class="muted center">{message}</p>}

      {result && (
        <div class={'card result' + (rolling ? ' rolling' : '')}>
          <a href={href.special(result.special.id)} class="result-title">{result.special.title}</a>
          <p class="byline">{result.special.performers.map((p) => db.comedians[p]?.name || p).join(', ')}</p>
          <p class="facts">{formatDate(result.special.release_date)}{runtimeLabel(result.special) && ` · ${runtimeLabel(result.special)}`}</p>
          <PlatformChips s={result.special} />
          {result.why.length > 0 && <p class="why">Why this one: {result.why.join(', ')}.</p>}
          <div class="result-actions">
            <WatchButton s={result.special} onClick={() => logSpin(result.special.id, 'watch')} />
            <button class="btn" onClick={spin}>Spin again</button>
            <button class="btn" onClick={notTonight}>Not tonight</button>
            <button class="btn" onClick={markSeen}>Mark seen</button>
          </div>
        </div>
      )}
    </div>
  );
}
