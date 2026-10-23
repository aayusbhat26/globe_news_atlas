import { useSyncExternalStore } from 'react';

const NAVIGATION_EVENT = 'gna:navigate';

function subscribe(onChange: () => void) {
  window.addEventListener('popstate', onChange);
  window.addEventListener(NAVIGATION_EVENT, onChange);
  return () => {
    window.removeEventListener('popstate', onChange);
    window.removeEventListener(NAVIGATION_EVENT, onChange);
  };
}

function currentPath(): string {
  return window.location.pathname;
}

export function usePathname(): string {
  return useSyncExternalStore(subscribe, currentPath, () => '/');
}

export function useLocationKey(): string {
  return useSyncExternalStore(
    subscribe,
    () => `${window.location.pathname}${window.location.search}`,
    () => '/',
  );
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  if (options.replace) {
    window.history.replaceState(null, '', to);
  } else {
    window.history.pushState(null, '', to);
  }
  window.dispatchEvent(new Event(NAVIGATION_EVENT));
  window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
}

export function replaceQuerySilently(to: string): void {
  window.history.replaceState(null, '', to);
}

export function safeNextPath(value: string | null, fallback = '/'): string {
  if (!value) return fallback;
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    return fallback;
  }
  return value;
}
