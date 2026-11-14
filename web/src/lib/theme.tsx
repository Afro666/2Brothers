import { createContext, type ReactNode, useContext, useEffect, useState, useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

interface ThemeContextValue {
  choice: ThemeChoice;
  /** What is shown: `system` resolved against the device setting. */
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// The inline script in index.html reads the same key and uses the same bar colours.
const STORAGE_KEY = "purchasing-theme";
const BAR_COLOUR: Record<ResolvedTheme, string> = { light: "#F4F1E9", dark: "#151410" };

function storedChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage can be blocked; the choice still works for this visit.
  }
  return "system";
}

/** Null where there is no `matchMedia` (jsdom): the device then counts as light. */
function deviceDarkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
}

function subscribeToDevice(onChange: () => void) {
  const query = deviceDarkQuery();
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}

function deviceIsDark(): boolean {
  return deviceDarkQuery()?.matches ?? false;
}

/** Keeps `data-theme` on `<html>` and the browser bar colour in step with the viewer's choice. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setCurrent] = useState<ThemeChoice>(storedChoice);
  const deviceDark = useSyncExternalStore(subscribeToDevice, deviceIsDark);
  const resolved: ResolvedTheme = choice === "system" ? (deviceDark ? "dark" : "light") : choice;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", BAR_COLOUR[resolved]);
  }, [resolved]);

  function setChoice(next: ThemeChoice) {
    setCurrent(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not remembered next visit; nothing else depends on it.
    }
  }

  return <ThemeContext.Provider value={{ choice, resolved, setChoice }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used within ThemeProvider");
  return value;
}
