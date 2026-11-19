import type { ComponentChildren } from 'preact';
import { data, getMark, marks, setStatus, settings } from '../store';
import { href } from '../router';
import { bestWatch, todayIso } from '../logic';
import type { MarkStatus, Special } from '../types';

export function formatDate(iso?: string): string {
  if (!iso) return 'Date TBA';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function runtimeLabel(s: Special): string {
  const parts = [];
  if (s.runtime_min) parts.push(`${s.runtime_min} min`);
  if (s.format === 'half_hour') parts.push('half-hour');
  return parts.join(' · ');
}

export function Performers({ s }: { s: Special }) {
  const db = data.value!;
  return (
    <>
      {s.performers.map((p, i) => (
        <span key={p}>
          {i > 0 && ', '}
          <a href={href.comedian(p)} class="performer">{db.comedians[p]?.name || p}</a>
        </span>
      ))}
    </>
  );
}

export function PlatformChips({ s, links = false }: { s: Special; links?: boolean }) {
  const db = data.value!;
  const services = settings.value.services;
  return (
    <span class="chips">
      {(s.platforms || []).map((p) => {
        const info = db.platforms[p.platform];
        const mine = services.includes(p.platform);
        const label = (info?.name || p.platform) + (p.kind === 'early_access' ? ' (early)' : '');
        return (
          <span key={p.platform + (p.url || '')} class={'chip' + (mine ? ' mine' : '')}
            style={info?.color ? { '--chip': info.color } : undefined}>
            {links && p.url ? <a href={p.url} target="_blank" rel="noopener">{label}</a> : label}
          </span>
        );
      })}
    </span>
  );
}

const STATUS_LABEL: Record<MarkStatus, string> = { want: 'Want', seen: 'Seen', not_interested: 'Not interested' };

export function StatusBadge({ id }: { id: string }) {
  const m = marks.value.get(id);
  if (!m?.status) return null;
  return <span class={`badge badge-${m.status}`}>{STATUS_LABEL[m.status]}</span>;
}

export function SpecialRow({ s }: { s: Special }) {
  const upcoming = !s.release_date || s.release_date > todayIso();
  return (
    <a class="row" href={href.special(s.id)}>
      <div class="row-main">
        <div class="row-title">{s.title} <StatusBadge id={s.id} /></div>
        <div class="row-sub">
          {s.performers.map((p) => data.value!.comedians[p]?.name || p).join(', ')}
        </div>
        <div class="row-meta">
          <span class={upcoming ? 'upcoming' : ''}>{upcoming ? 'Coming ' : ''}{formatDate(s.release_date)}</span>
          {runtimeLabel(s) && <span> · {runtimeLabel(s)}</span>}
        </div>
      </div>
      <PlatformChips s={s} />
    </a>
  );
}

export function StatusButtons({ s }: { s: Special }) {
  const m = getMark(s.id);
  const btn = (st: MarkStatus, label: string) => (
    <button class={'seg' + (m.status === st ? ' on' : '')} aria-pressed={m.status === st}
      onClick={() => setStatus(s.id, st)}>{label}</button>
  );
  return (
    <div class="segmented" role="group" aria-label="Your status">
      {btn('want', 'Want to see')}
      {btn('seen', 'Seen')}
      {btn('not_interested', 'Not interested')}
    </div>
  );
}

export function WatchButton({ s, onClick }: { s: Special; onClick?: () => void }) {
  const w = bestWatch(s, data.value!, settings.value.services);
  if (!w) return <span class="muted">No watch link yet</span>;
  return (
    <a class="btn primary" href={w.url} target="_blank" rel="noopener" onClick={onClick}>
      Watch on {w.label}
    </a>
  );
}

export function Section({ title, children, action }: { title: string; children: ComponentChildren; action?: ComponentChildren }) {
  return (
    <section class="section">
      <div class="section-head"><h2>{title}</h2>{action}</div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ComponentChildren }) {
  return <p class="empty">{children}</p>;
}

export function List({ items, limit, more }: { items: Special[]; limit?: number; more?: string }) {
  const shown = limit ? items.slice(0, limit) : items;
  return (
    <div class="list">
      {shown.map((s) => <SpecialRow key={s.id} s={s} />)}
      {more && limit && items.length > limit && <a class="more" href={more}>See all {items.length} →</a>}
    </div>
  );
}
