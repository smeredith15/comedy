import { data, follows, marks } from '../store';
import { href, route } from '../router';
import { Empty, List } from '../components/ui';
import type { MarkStatus, Special } from '../types';

const TABS: { key: MarkStatus | 'following'; label: string }[] = [
  { key: 'want', label: 'Want to see' },
  { key: 'seen', label: 'Seen' },
  { key: 'not_interested', label: 'Not interested' },
  { key: 'following', label: 'Following' },
];

export function Lists() {
  const db = data.value!;
  const tab = (route.value.query.get('tab') || 'want') as (typeof TABS)[number]['key'];
  const byId = new Map(db.specials.map((s) => [s.id, s]));
  const items = (status: MarkStatus): Special[] => {
    const ms = [...marks.value.values()].filter((m) =>
      status === 'seen' ? m.status === 'seen' || (m.watches.length > 0 && m.status !== 'not_interested') : m.status === status);
    const sortKey = (id: string) => {
      const m = marks.value.get(id)!;
      return status === 'seen' ? m.watches[m.watches.length - 1] || '' : String(m.updatedAt);
    };
    return ms.map((m) => byId.get(m.id)).filter((s): s is Special => !!s)
      .sort((a, b) => sortKey(b.id).localeCompare(sortKey(a.id)));
  };
  const count = (k: string) => (k === 'following' ? follows.value.size : items(k as MarkStatus).length);

  return (
    <div class="page">
      <nav class="tabs" role="tablist">
        {TABS.map((t) => (
          <a key={t.key} role="tab" aria-selected={tab === t.key} class={'tab' + (tab === t.key ? ' on' : '')} href={href.lists(t.key)}>
            {t.label} <span class="tab-count">{count(t.key)}</span>
          </a>
        ))}
      </nav>
      {tab === 'following' ? (
        follows.value.size ? (
          <div class="list">
            {[...follows.value].sort((a, b) => (db.comedians[a]?.name || a).localeCompare(db.comedians[b]?.name || b)).map((slug) => (
              <a key={slug} class="row" href={href.comedian(slug)}>
                <div class="row-main"><div class="row-title">{db.comedians[slug]?.name || slug}</div>
                  <div class="row-sub">{db.specials.filter((s) => s.performers.includes(slug)).length} specials</div></div>
              </a>
            ))}
          </div>
        ) : <Empty>You're not following anyone yet.</Empty>
      ) : (() => {
        const list = items(tab as MarkStatus);
        return list.length ? <List items={list} /> : <Empty>Nothing here yet.</Empty>;
      })()}
    </div>
  );
}
