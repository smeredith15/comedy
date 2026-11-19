import { data, follows } from '../store';
import { addDays, todayIso } from '../logic';
import { href } from '../router';
import { Empty, List, Section } from '../components/ui';

export function Home() {
  const db = data.value!;
  const today = todayIso();
  const monthAgo = addDays(today, -30);
  const halfYear = addDays(today, -180);
  const released = db.specials.filter((s) => s.release_date && s.release_date <= today);
  const fresh = released.filter((s) => s.release_date! >= monthAgo);
  const upcoming = db.specials
    .filter((s) => !s.release_date || s.release_date > today)
    .sort((a, b) => (a.release_date || '9999').localeCompare(b.release_date || '9999'));
  const followed = db.specials.filter(
    (s) => s.performers.some((p) => follows.value.has(p)) && (!s.release_date || s.release_date >= halfYear),
  );

  return (
    <div class="page">
      {db.specials.length === 0 && (
        <div class="card notice">
          <strong>No specials yet.</strong> The database fills in after the first nightly run
          {db.last_run ? ` (last run ${db.last_run.slice(0, 10)})` : ''}. You can still set up your services in{' '}
          <a href={href.settings()}>Settings</a>.
        </div>
      )}
      <Section title="New this month" action={<a href={href.browse({ sort: 'new' })}>Browse</a>}>
        {fresh.length ? <List items={fresh} limit={8} more={href.browse()} /> : <Empty>Nothing new in the last 30 days.</Empty>}
      </Section>
      <Section title="Upcoming">
        {upcoming.length ? <List items={upcoming} limit={6} more={href.browse({ upcoming: '1' })} /> : <Empty>No announced specials.</Empty>}
      </Section>
      <Section title="From comedians you follow">
        {follows.value.size === 0 ? (
          <Empty>Follow comedians from their page and their new specials show up here.</Empty>
        ) : followed.length ? (
          <List items={followed} limit={8} />
        ) : (
          <Empty>Nothing recent from the {follows.value.size} comedian{follows.value.size === 1 ? '' : 's'} you follow.</Empty>
        )}
      </Section>
    </div>
  );
}
