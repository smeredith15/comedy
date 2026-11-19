import { signal } from '@preact/signals';

/** Hash routes work on GitHub Pages without server rewrites. */
export interface Route {
  name: 'home' | 'browse' | 'special' | 'comedian' | 'lists' | 'spin' | 'settings';
  param?: string;
  query: URLSearchParams;
}

function parse(): Route {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, qs] = raw.split('?');
  const [name, param] = path.split('/');
  const query = new URLSearchParams(qs || '');
  const known = ['browse', 'special', 'comedian', 'lists', 'spin', 'settings'];
  return { name: (known.includes(name) ? name : 'home') as Route['name'], param: param && decodeURIComponent(param), query };
}

export const route = signal<Route>(parse());

window.addEventListener('hashchange', () => {
  route.value = parse();
  window.scrollTo(0, 0);
});

export const href = {
  home: () => '#/',
  browse: (q?: Record<string, string>) => '#/browse' + (q ? '?' + new URLSearchParams(q) : ''),
  special: (id: string) => `#/special/${encodeURIComponent(id)}`,
  comedian: (slug: string) => `#/comedian/${encodeURIComponent(slug)}`,
  lists: (tab?: string) => '#/lists' + (tab ? `?tab=${tab}` : ''),
  spin: () => '#/spin',
  settings: () => '#/settings',
};
