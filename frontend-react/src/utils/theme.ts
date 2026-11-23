import { useState, useEffect, useCallback } from 'react';

export type StoredColorScheme = 'light' | 'dark' | null;
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'color-scheme';
const THEME_EVENT = 'eztech-theme-change';

// In-memory fallback when localStorage is blocked (private mode / site data disabled)
let _memoryOverride: StoredColorScheme = null;
let _storageBlocked = false;

function getSystemDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function getStoredScheme(): StoredColorScheme {
  if (_storageBlocked) return _memoryOverride;
  try {
    const val = localStorage.getItem(STORAGE_KEY);
    return val === 'light' || val === 'dark' ? val : null;
  } catch {
    _storageBlocked = true;
    return _memoryOverride;
  }
}

export function resolveTheme(stored: StoredColorScheme = getStoredScheme()): ResolvedTheme {
  if (stored === 'light' || stored === 'dark') return stored;
  return getSystemDark() ? 'dark' : 'light';
}

export function applyThemeToDom(stored: StoredColorScheme): ResolvedTheme {
  const resolved = resolveTheme(stored);
  const meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
  if (meta) {
    meta.content = stored ?? 'light dark';
  }
  document.documentElement.classList.toggle('dark', resolved === 'dark');
  return resolved;
}

/** Chuyển trực tiếp sang 'light' hoặc 'dark'; nếu trùng OS sẽ gỡ override để theo hệ thống. */
export function setColorScheme(target: ResolvedTheme): ResolvedTheme {
  const systemDark = getSystemDark();
  const nextStored: StoredColorScheme = (target === 'dark') !== systemDark ? target : null;
  _memoryOverride = nextStored;

  try {
    if (nextStored) {
      localStorage.setItem(STORAGE_KEY, nextStored);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
    _storageBlocked = false;
  } catch {
    _storageBlocked = true;
  }

  const meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
  if (meta) {
    meta.content = nextStored ?? 'light dark';
  }
  document.documentElement.classList.toggle('dark', target === 'dark');
  window.dispatchEvent(new Event(THEME_EVENT));
  return target;
}

export function toggleColorScheme(): ResolvedTheme {
  const currentlyDark = resolveTheme(getStoredScheme()) === 'dark';
  return setColorScheme(currentlyDark ? 'light' : 'dark');
}

export function useTheme() {
  const [theme, setTheme] = useState<ResolvedTheme>(() => resolveTheme());
  const [storedScheme, setStoredScheme] = useState<StoredColorScheme>(() => getStoredScheme());

  const sync = useCallback(() => {
    const stored = getStoredScheme();
    setStoredScheme(stored);
    setTheme(applyThemeToDom(stored));
  }, []);

  useEffect(() => {
    sync();
    const mql = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    const onMediaChange = () => sync();
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === STORAGE_KEY) {
        _storageBlocked = false;
        sync();
      }
    };

    mql?.addEventListener('change', onMediaChange);
    window.addEventListener('storage', onStorage);
    window.addEventListener(THEME_EVENT, sync);

    return () => {
      mql?.removeEventListener('change', onMediaChange);
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(THEME_EVENT, sync);
    };
  }, [sync]);

  return {
    theme,
    isDark: theme === 'dark',
    storedScheme,
    setScheme: setColorScheme,
    toggle: toggleColorScheme,
  };
}
