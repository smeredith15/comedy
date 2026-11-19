// Writes a FICTIONAL sample database to public/data/db.json so the app can be tried
// before the first nightly run. Every name and title here is made up.
import { mkdirSync, writeFileSync } from 'node:fs';

const day = (offset) => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);
const people = {
  'avery-sample': 'Avery Sample', 'jordan-placeholder': 'Jordan Placeholder', 'casey-example': 'Casey Example',
  'riley-demo': 'Riley Demo', 'morgan-test': 'Morgan Test', 'sam-fixture': 'Sam Fixture', 'quinn-mock': 'Quinn Mock',
};
const plats = [
  ['netflix', 'subscription'], ['max', 'subscription'], ['youtube', 'free'], ['prime-video', 'subscription'],
  ['hulu', 'subscription'], ['peacock', 'subscription'], ['800-pound-gorilla', 'early_access'],
];
const titles = ['Loud Thoughts', 'Kitchen Table', 'Grown-Up Problems', 'The Long Way Home', 'Small Talk', 'Overthinker',
  'Bad Advice', 'Dinner Party', 'Second Opinion', 'Late Again', 'Hometown Hero', 'Nervous Energy', 'Group Chat',
  'Mild Inconvenience', 'Middle Seat', 'Out of Office', 'Plus One', 'Spare Room'];
const specials = titles.map((title, i) => {
  const slug = Object.keys(people)[i % 7];
  const offset = i < 3 ? 20 + i * 15 : -(i * 37);
  const [p, kind] = plats[i % plats.length];
  const platforms = [{ platform: p, kind, date: day(offset) }];
  if (p === '800-pound-gorilla') platforms.push({ platform: 'youtube', kind: 'free', url: 'https://www.youtube.com/', date: day(offset + 35) });
  const runtime = i % 5 === 4 ? 28 : 52 + (i * 7) % 30;
  return {
    id: `${slug}--${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}--${day(offset).slice(0, 4)}`,
    title, performers: [slug], status: offset > 0 ? 'upcoming' : 'released',
    format: runtime < 40 ? 'half_hour' : 'hour', runtime_min: offset > 0 ? undefined : runtime,
    release_date: day(offset), public_release_date: platforms[1]?.date, platforms, ids: {},
  };
}).sort((a, b) => b.release_date.localeCompare(a.release_date));

const db = {
  version: 1, generated: new Date().toISOString(), last_run: null, repo: null, region: 'US', counts: {},
  specials,
  comedians: Object.fromEntries(Object.entries(people).map(([k, name]) => [k, { name, ...(k === 'casey-example' ? { followed: true } : {}) }])),
  platforms: {
    netflix: { name: 'Netflix', kind: 'subscription', color: '#e50914', search_url: 'https://www.netflix.com/search?q={q}' },
    max: { name: 'Max', kind: 'subscription', color: '#002be7' },
    youtube: { name: 'YouTube', kind: 'free', color: '#ff0033' },
    'prime-video': { name: 'Prime Video', kind: 'subscription', color: '#1399ff' },
    hulu: { name: 'Hulu', kind: 'subscription', color: '#1ce783' },
    peacock: { name: 'Peacock', kind: 'subscription', color: '#f5c518' },
    '800-pound-gorilla': { name: '800 Pound Gorilla', kind: 'early_access', color: '#666666' },
  },
  redirects: {},
};
mkdirSync(new URL('../public/data/', import.meta.url), { recursive: true });
writeFileSync(new URL('../public/data/db.json', import.meta.url), JSON.stringify(db));
console.log(`sample db: ${specials.length} fictional specials`);
