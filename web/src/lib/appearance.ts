import { useSyncExternalStore } from "react";

/**
 * Display choices, kept per browser until the backend stores them per user.
 * The first option of each is the default. Accent and density are attributes
 * on `<html>` that index.css reads; the formats are read by lib/format.ts.
 */
export const APPEARANCE_OPTIONS = {
  accent: ["herb", "blue", "plum", "clay", "teal"],
  density: ["comfortable", "compact"],
  /** `comma` is 1,000.50 and `space` is 1 000,50. */
  numberFormat: ["comma", "space"],
  /** 14 Nov, 14.11. or Nov 14. */
  dateFormat: ["dmy", "numeric", "mdy"],
  weekStartsMonday: [true, false],
} as const;

export type Appearance = { [K in keyof typeof APPEARANCE_OPTIONS]: (typeof APPEARANCE_OPTIONS)[K][number] };

/** The oklch hue index.css builds a preset's tokens from. Herb keeps its own brand colours there. */
export const ACCENT_HUES: Record<Appearance["accent"], number> = {
  herb: 148,
  blue: 255,
  plum: 320,
  clay: 45,
  teal: 195,
};

const STORAGE_KEY = "purchasing-appearance";
const listeners = new Set<() => void>();
let current: Appearance;

function apply() {
  const root = document.documentElement;
  root.dataset.accent = current.accent;
  root.dataset.density = current.density;
  root.style.setProperty("--accent-hue", String(ACCENT_HUES[current.accent]));
}

/** Reads the stored choices and applies them. Runs once on import; anything stored that is not an option is ignored. */
export function loadAppearance() {
  let stored: Record<string, unknown> = {};
  try {
    stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") ?? {};
  } catch {
    // Storage blocked or not JSON: the defaults apply.
  }
  const next: Record<string, unknown> = {};
  for (const [key, options] of Object.entries(APPEARANCE_OPTIONS)) {
    next[key] = (options as readonly unknown[]).includes(stored[key]) ? stored[key] : options[0];
  }
  current = next as Appearance;
  apply();
  listeners.forEach((listener) => listener());
}
loadAppearance();

export function getAppearance(): Appearance {
  return current;
}

export function setAppearance(change: Partial<Appearance>) {
  current = { ...current, ...change };
  apply();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    // Not remembered next visit; it still applies for this one.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAppearance(): Appearance {
  return useSyncExternalStore(subscribe, getAppearance);
}
