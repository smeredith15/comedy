import { data, dataError, ready, refreshing } from './store';
import { href, route } from './router';
import { Home } from './pages/Home';
import { Browse } from './pages/Browse';
import { SpecialPage } from './pages/SpecialPage';
import { ComedianPage } from './pages/ComedianPage';
import { Lists } from './pages/Lists';
import { Spin } from './pages/Spin';
import { Settings } from './pages/Settings';

const NAV = [
  { name: 'home', label: 'Home', href: href.home(), icon: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z' },
  { name: 'browse', label: 'Browse', href: href.browse(), icon: 'M11 4a7 7 0 1 0 4.2 12.6l4.6 4.6 1.4-1.4-4.6-4.6A7 7 0 0 0 11 4zm0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10z' },
  { name: 'spin', label: 'Spin', href: href.spin(), icon: 'M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 3a2 2 0 1 1-2 2 2 2 0 0 1 2-2zm-5 5a2 2 0 1 1-2 2 2 2 0 0 1 2-2zm10 0a2 2 0 1 1-2 2 2 2 0 0 1 2-2zm-5 5a2 2 0 1 1-2 2 2 2 0 0 1 2-2z' },
  { name: 'lists', label: 'My lists', href: href.lists(), icon: 'M4 5h16v2H4zm0 6h16v2H4zm0 6h10v2H4z' },
  { name: 'settings', label: 'Settings', href: href.settings(), icon: 'M12 8a4 4 0 1 0 4 4 4 4 0 0 0-4-4zm9 4a7.7 7.7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a8 8 0 0 0-2-1.2L16 3h-4l-.5 2.6a8 8 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7.7 7.7 0 0 0 7 12a7.7 7.7 0 0 0 .1 1.2l-2 1.6 2 3.4 2.4-1a8 8 0 0 0 2 1.2L12 21h4l.5-2.6a8 8 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6A7.7 7.7 0 0 0 21 12z' },
] as const;

const TITLES: Record<string, string> = {
  home: 'Specials', browse: 'Browse', spin: 'Spin', lists: 'My lists', settings: 'Settings', special: 'Special', comedian: 'Comedian',
};

export function App() {
  const r = route.value;
  const db = data.value;
  const section = r.name === 'special' || r.name === 'comedian' ? null : r.name;

  let page;
  if (!ready.value) page = <div class="page center muted">Loading…</div>;
  else if (!db) page = (
    <div class="page center">
      <p>{dataError.value || (refreshing.value ? 'Downloading the specials database…' : 'Loading…')}</p>
      {dataError.value && <p class="muted small">Check your connection and reopen the app.</p>}
    </div>
  );
  else {
    switch (r.name) {
      case 'browse': page = <Browse key={location.hash} />; break;
      case 'special': page = <SpecialPage key={r.param} />; break;
      case 'comedian': page = <ComedianPage />; break;
      case 'lists': page = <Lists />; break;
      case 'spin': page = <Spin />; break;
      case 'settings': page = <Settings />; break;
      default: page = <Home />;
    }
  }

  return (
    <div class="shell">
      <header class="topbar">
        {section ? <span class="brand">{TITLES[r.name]}</span> : (
          <button class="back" onClick={() => (history.length > 1 ? history.back() : (location.hash = '#/'))} aria-label="Back">‹ Back</button>
        )}
        {refreshing.value && db && <span class="sync" title="Checking for new specials">●</span>}
      </header>
      <main>{page}</main>
      <nav class="tabbar" aria-label="Main">
        {NAV.map((n) => (
          <a key={n.name} href={n.href} class={'tabbar-item' + (section === n.name ? ' on' : '')} aria-current={section === n.name ? 'page' : undefined}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d={n.icon} /></svg>
            <span>{n.label}</span>
          </a>
        ))}
      </nav>
    </div>
  );
}
