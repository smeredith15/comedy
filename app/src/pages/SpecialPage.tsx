import { useState } from 'preact/hooks';
import { addWatch, data, getMark, removeWatch, specialsById, updateMark } from '../store';
import { resolveId, todayIso, watchUrl } from '../logic';
import { route } from '../router';
import { Empty, formatDate, Performers, runtimeLabel, StatusButtons } from '../components/ui';
import { notASpecialUrl } from './Settings';

const KIND_LABEL: Record<string, string> = {
  subscription: 'Subscription', free: 'Free', ads: 'Free with ads', early_access: 'Early access', paid: 'Paid', tv: 'TV',
};

export function SpecialPage() {
  const db = data.value!;
  const raw = route.value.param || '';
  const s = specialsById.value.get(resolveId(raw, db.redirects));
  const [date, setDate] = useState(todayIso());
  if (!s) return <div class="page"><Empty>That special isn't in the database.</Empty></div>;
  const m = getMark(s.id);
  const upcoming = !s.release_date || s.release_date > todayIso();

  return (
    <div class="page special">
      <h1>{s.title}</h1>
      <p class="byline"><Performers s={s} /></p>
      <p class="facts">
        <span class={upcoming ? 'upcoming' : ''}>{upcoming ? 'Coming ' : ''}{formatDate(s.release_date)}</span>
        {s.public_release_date && <span> · free from {formatDate(s.public_release_date)}</span>}
        {runtimeLabel(s) && <span> · {runtimeLabel(s)}</span>}
      </p>

      <div class="watch-list">
        {(s.platforms || []).length === 0 && <span class="muted">Where to watch isn't known yet.</span>}
        {(s.platforms || []).map((p) => {
          const url = watchUrl(s, p, db);
          const info = db.platforms[p.platform];
          return (
            <a key={p.platform + (p.url || '')} class="watch" href={url || undefined} target="_blank" rel="noopener"
              style={info?.color ? { '--chip': info.color } : undefined}>
              <span class="watch-name">{info?.name || p.platform}</span>
              <span class="watch-kind">{KIND_LABEL[p.kind || ''] || p.kind}{p.date ? ` · ${formatDate(p.date)}` : ''}{!p.url && url ? ' · search' : ''}</span>
            </a>
          );
        })}
      </div>

      <StatusButtons s={s} />

      <div class="card">
        <div class="field">
          <span class="label">Rating</span>
          <div class="stars" role="radiogroup" aria-label="Rating">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} role="radio" aria-checked={m.rating === n} aria-label={`${n} star${n > 1 ? 's' : ''}`}
                class={'star' + ((m.rating || 0) >= n ? ' on' : '')}
                onClick={() => updateMark(s.id, { rating: m.rating === n ? undefined : n })}>★</button>
            ))}
          </div>
        </div>
        <div class="field">
          <span class="label">Watched</span>
          <ul class="watches">
            {m.watches.map((w, i) => (
              <li key={w + i}>{formatDate(w)} <button class="link" onClick={() => removeWatch(s.id, i)} aria-label={`Remove ${w}`}>remove</button></li>
            ))}
          </ul>
          <div class="inline">
            <input type="date" value={date} max={todayIso()} onInput={(e) => setDate((e.target as HTMLInputElement).value)} aria-label="Watch date" />
            <button class="btn" onClick={() => date && addWatch(s.id, date)}>{m.watches.length ? 'Add rewatch' : 'Add watch date'}</button>
          </div>
        </div>
        <label class="field">
          <span class="label">Notes</span>
          <textarea rows={3} value={m.notes || ''} placeholder="Favorite bits, who recommended it…"
            onChange={(e) => updateMark(s.id, { notes: (e.target as HTMLTextAreaElement).value || undefined })} />
        </label>
      </div>

      <p class="muted small">
        {s.ids?.tmdb && <a href={`https://www.themoviedb.org/movie/${s.ids.tmdb}`} target="_blank" rel="noopener">TMDB</a>}
        {s.ids?.imdb && <> · <a href={`https://www.imdb.com/title/${s.ids.imdb}/`} target="_blank" rel="noopener">IMDb</a></>}
        {s.ids?.wikipedia && <> · <a href={`https://en.wikipedia.org/wiki/${s.ids.wikipedia}`} target="_blank" rel="noopener">Wikipedia</a></>}
      </p>
      {notASpecialUrl(s.id, s.title) && (
        <p class="muted small remove">
          Not actually a special (a podcast, clip, interview)?{' '}
          <a href={notASpecialUrl(s.id, s.title)!} target="_blank" rel="noopener">Remove it from the database</a>.
          It opens a short GitHub form; the next nightly run removes it for good.
        </p>
      )}
    </div>
  );
}
