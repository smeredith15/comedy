import { data, follows, marks, toggleFollow } from '../store';
import { route } from '../router';
import { Empty, List } from '../components/ui';

export function ComedianPage() {
  const db = data.value!;
  const slug = route.value.param || '';
  const c = db.comedians[slug];
  const specials = db.specials.filter((s) => s.performers.includes(slug));
  const following = follows.value.has(slug);
  const seen = specials.filter((s) => {
    const m = marks.value.get(s.id);
    return m?.status === 'seen' || (m?.watches.length ?? 0) > 0;
  }).length;

  return (
    <div class="page">
      <div class="comedian-head">
        <div>
          <h1>{c?.name || slug}</h1>
          <p class="muted">{specials.length} special{specials.length === 1 ? '' : 's'}{specials.length ? ` · ${seen} seen` : ''}</p>
        </div>
        <button class={'btn' + (following ? ' on' : ' primary')} aria-pressed={following} onClick={() => toggleFollow(slug)}>
          {following ? 'Following' : 'Follow'}
        </button>
      </div>
      {specials.length ? <List items={specials} /> : <Empty>No specials in the database yet.</Empty>}
    </div>
  );
}
