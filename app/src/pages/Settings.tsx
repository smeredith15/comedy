import { useState } from 'preact/hooks';
import { data, exportBackup, importBackup, persisted, refresh, refreshing, saveSettings, settings } from '../store';
import { parseBackup, todayIso } from '../logic';
import { DEFAULT_WEIGHTS, type Weights } from '../types';
import { Section } from '../components/ui';

const WEIGHT_LABELS: Record<keyof Weights, string> = {
  want: 'On Want to see',
  followed: 'Comedian you follow',
  recent: 'Released in the last 90 days',
  skipped: 'Skipped in an earlier spin',
};

export function repoSlug(): string | null {
  return (import.meta.env.VITE_REPO as string) || data.value?.repo || null;
}

export function notASpecialUrl(id: string, title: string): string | null {
  const repo = repoSlug();
  if (!repo) return null;
  const q = new URLSearchParams({ template: 'not-a-special.yml', title: `Not a special: ${title}`, special_id: id });
  return `https://github.com/${repo}/issues/new?${q}`;
}

export function missingSpecialUrl(prefill: Record<string, string> = {}): string | null {
  const repo = repoSlug();
  if (!repo) return null;
  const q = new URLSearchParams({ template: 'missing-special.yml', title: 'Missing special: ', ...prefill });
  return `https://github.com/${repo}/issues/new?${q}`;
}

export function Settings() {
  const db = data.value!;
  const s = settings.value;
  const [msg, setMsg] = useState<string | null>(null);

  const platforms = Object.entries(db.platforms)
    .filter(([, p]) => p.kind !== 'free' && p.kind !== 'ads')
    .sort((a, b) => a[1].name.localeCompare(b[1].name));

  const toggleService = (slug: string) => {
    const services = s.services.includes(slug) ? s.services.filter((x) => x !== slug) : [...s.services, slug];
    saveSettings({ ...s, services });
  };

  const setWeight = (k: keyof Weights, v: string) => {
    const n = Number(v);
    if (Number.isFinite(n) && n >= 0) saveSettings({ ...s, weights: { ...s.weights, [k]: n } });
  };

  const doExport = async () => {
    const b = await exportBackup();
    const blob = new Blob([JSON.stringify(b, null, 1)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `specials-backup-${todayIso()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    setMsg(`Exported ${b.marks.length} marks and ${b.follows.length} follows.`);
  };

  const doImport = async (e: Event) => {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    try {
      const r = await importBackup(parseBackup(await file.text()));
      setMsg(`Restored ${r.marks} marks and ${r.follows} follows. Existing marks were kept and merged.`);
    } catch (err) {
      setMsg(`Couldn't import: ${(err as Error).message}`);
    }
    (e.target as HTMLInputElement).value = '';
  };

  const doRefresh = async () => {
    const r = await refresh();
    setMsg(r === 'updated' ? 'Database updated.' : r === 'same' ? 'Already up to date.' : "Couldn't reach the server. Using the saved copy.");
  };

  const report = missingSpecialUrl();

  return (
    <div class="page settings">
      {msg && <p class="toast" role="status">{msg}</p>}

      <Section title="My streaming services">
        <p class="muted small">Used by Spin's “Only my services” and to highlight links. Free platforms always count.</p>
        <div class="service-grid">
          {platforms.map(([slug, p]) => (
            <label key={slug} class={'service' + (s.services.includes(slug) ? ' on' : '')}>
              <input type="checkbox" checked={s.services.includes(slug)} onChange={() => toggleService(slug)} />
              <span class="dot" style={p.color ? { background: p.color } : undefined} />
              {p.name}
            </label>
          ))}
        </div>
        <label class="inline-label">Region
          <select value={s.region} onChange={(e) => saveSettings({ ...s, region: (e.target as HTMLSelectElement).value })}>
            <option value="US">United States</option>
          </select>
        </label>
        <p class="muted small">Where-to-watch data is collected for the {db.region || 'US'} region.</p>
      </Section>

      <Section title="Spin weights">
        <div class="grid2">
          {(Object.keys(WEIGHT_LABELS) as (keyof Weights)[]).map((k) => (
            <label key={k}>{WEIGHT_LABELS[k]}
              <input type="number" step="0.1" min="0" value={s.weights[k]} onChange={(e) => setWeight(k, (e.target as HTMLInputElement).value)} />
            </label>
          ))}
        </div>
        <button class="link" onClick={() => saveSettings({ ...s, weights: DEFAULT_WEIGHTS })}>Reset to defaults (×3, ×2, ×1.5, ×0.5)</button>
      </Section>

      <Section title="Backup">
        <p class="muted small">Your lists are stored only on this device. Export a backup now and then.</p>
        <div class="inline">
          <button class="btn" onClick={doExport}>Export backup</button>
          <label class="btn">Import backup<input type="file" accept="application/json,.json" hidden onChange={doImport} /></label>
        </div>
        <p class="muted small">
          Persistent storage: {persisted.value === null ? 'unknown' : persisted.value ? 'on (the browser won’t clear your lists)' : 'not granted yet. It’s requested when you first mark something. Installing the app helps.'}
        </p>
      </Section>

      <Section title="Data">
        <p class="muted small">
          {db.specials.length.toLocaleString()} specials · database built {new Date(db.generated).toLocaleString()}
          {db.last_run && <> · last collected {new Date(db.last_run).toLocaleDateString()}</>}
        </p>
        <div class="inline">
          <button class="btn" onClick={doRefresh} disabled={refreshing.value}>{refreshing.value ? 'Refreshing…' : 'Refresh data'}</button>
          {report && <a class="btn" href={report} target="_blank" rel="noopener">Report missing special</a>}
        </div>
      </Section>

      <Section title="About">
        <p class="small">
          A personal, non-commercial project. Specials are collected nightly from TMDB, Wikipedia and YouTube.
        </p>
        <p class="small attribution">
          <img src={`${import.meta.env.BASE_URL}icons/tmdb.svg`} alt="TMDB" height={14}
            onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} />
          <span>This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming availability by JustWatch, via TMDB.</span>
        </p>
        <p class="small muted">Facts from Wikipedia link back to the source page. YouTube data is used under the YouTube API Services Terms of Service.</p>
      </Section>
    </div>
  );
}
