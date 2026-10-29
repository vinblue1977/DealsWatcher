import type { Route } from './router';

const TABS: { route: Route; href: string; label: string; icon: string }[] = [
  { route: 'watching', href: '#/', label: 'Watching', icon: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z' },
  { route: 'settings', href: '#/settings', label: 'Settings', icon: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM9 15a2 2 0 1 0 0 4 2 2 0 0 0 0-4z' },
];

export function Nav({ active }: { active: Route }) {
  return (
    <nav class="tabs" aria-label="Main">
      {TABS.map((t) => (
        <a href={t.href} class={t.route === active ? 'tab on' : 'tab'} aria-current={t.route === active ? 'page' : undefined}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d={t.icon} />
          </svg>
          {t.label}
        </a>
      ))}
    </nav>
  );
}
