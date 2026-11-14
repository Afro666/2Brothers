import { createContext, Fragment, type ReactNode, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

export type Language = "en" | "fi";
export type TranslationVariables = Record<string, string | number>;

type DictionaryModule = { default: Record<string, string> };

const LanguageContext = createContext<{
  language: Language;
  setLanguage: (language: Language) => void;
} | null>(null);

const STORAGE_KEY = "purchasing-language";
const listeners = new Set<() => void>();

/**
 * One dictionary from all the files. Two files giving one English text different Finnish
 * is an error for the tests ("throw"); the running app keeps the first and carries on
 * ("keep-first"), because a wording clash must never take the site down.
 */
export function collectFinnishDictionaries(
  modules: Record<string, DictionaryModule>,
  onConflict: "throw" | "keep-first" = "throw",
): Record<string, string> {
  const dictionary = Object.create(null) as Record<string, string>;
  for (const [path, module] of Object.entries(modules)) {
    for (const [text, translation] of Object.entries(module.default)) {
      if (Object.prototype.hasOwnProperty.call(dictionary, text)) {
        if (dictionary[text] !== translation && onConflict === "throw") {
          throw new Error(`Conflicting Finnish translations for ${JSON.stringify(text)} in ${path}`);
        }
        continue;
      }
      dictionary[text] = translation;
    }
  }
  return dictionary;
}

const finnish = collectFinnishDictionaries(
  import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<string, DictionaryModule>,
  "keep-first",
);

export function translate(language: Language, text: string, vars: TranslationVariables = {}): string {
  const translated =
    language === "fi" && Object.prototype.hasOwnProperty.call(finnish, text) ? finnish[text] : text;
  return translated.replace(/\{([^{}]+)\}/g, (placeholder, name: string) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : placeholder,
  );
}

function storedLanguage(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === "fi" ? "fi" : "en";
  } catch {
    return "en";
  }
}

let currentLanguage: Language = storedLanguage();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function updateLanguage(next: Language, persist = true) {
  currentLanguage = next;
  document.documentElement.lang = next;
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {}
  }
  listeners.forEach((listener) => listener());
}

export function getLanguage(): Language {
  return currentLanguage;
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const language = useSyncExternalStore(subscribe, getLanguage);

  useEffect(() => {
    const stored = storedLanguage();
    if (stored !== currentLanguage) updateLanguage(stored, false);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <LanguageContext.Provider value={{ language, setLanguage: updateLanguage }}>
      {/* Remount the subtree so non-reactive formatters use the new language immediately. */}
      <Fragment key={language}>{children}</Fragment>
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  const language = useSyncExternalStore(subscribe, getLanguage);
  return value ?? { language, setLanguage: updateLanguage };
}

export function useT() {
  const { language } = useLanguage();
  return useCallback(
    (text: string, vars?: TranslationVariables) => translate(language, text, vars),
    [language],
  );
}
