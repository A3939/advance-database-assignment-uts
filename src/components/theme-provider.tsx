"use client";

import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { DEFAULT_THEME, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

export type { Theme } from "@/lib/theme";

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);
const listeners = new Set<() => void>();
let activeTheme: Theme = DEFAULT_THEME;
let initialized = false;

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
  root.style.colorScheme = theme;
}

function updateTheme(theme: Theme) {
  activeTheme = theme;
  applyTheme(theme);
  listeners.forEach((listener) => listener());
}

function setTheme(theme: Theme) {
  initialized = true;
  updateTheme(theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Switching remains available when browser storage is blocked or full.
  }
}

function toggleTheme() {
  setTheme(activeTheme === "dark" ? "light" : "dark");
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  function syncStorage(event: StorageEvent) {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    try {
      if (event.storageArea !== localStorage) return;
    } catch {
      return;
    }
    updateTheme(event.newValue === "light" ? "light" : "dark");
  }
  window.addEventListener("storage", syncStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", syncStorage);
  };
}

const getSnapshot = () => activeTheme;
const getServerSnapshot = () => DEFAULT_THEME;

export function ThemeProvider({ children }: { children: ReactNode }) {
  // The server snapshot also serves the first hydration render.
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useLayoutEffect(() => {
    if (!initialized) {
      try {
        activeTheme =
          localStorage.getItem(THEME_STORAGE_KEY) === "dark"
            ? "dark"
            : "light";
      } catch {
        activeTheme = DEFAULT_THEME;
      }
      initialized = true;
    }
    // Reapply on development Strict Mode remounts without losing the preference.
    updateTheme(activeTheme);
  }, []);

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme]);
  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("Theme provider missing");
  return context;
}
