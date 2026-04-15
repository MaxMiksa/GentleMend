"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import zh from "./zh.json";
import en from "./en.json";

export type Locale = "zh" | "en";

const dictionaries: Record<Locale, typeof zh> = { zh, en };

interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  symptomName: (key: string) => string;
  severityLevels: (key: string) => string[];
}

const I18nContext = createContext<I18nContextValue>(null!);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("gentlemend_locale") as Locale) || "zh";
    }
    return "zh";
  });

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("gentlemend_locale", l);
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      const dict = dictionaries[locale];
      const parts = key.split(".");
      let val: unknown = dict;
      for (const p of parts) {
        if (val && typeof val === "object") val = (val as Record<string, unknown>)[p];
        else return key;
      }
      if (typeof val !== "string") return key;
      if (!vars) return val;
      return val.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`));
    },
    [locale],
  );

  const symptomName = useCallback(
    (key: string): string => {
      const dict = dictionaries[locale];
      return (dict.symptoms as Record<string, string>)[key] ?? key;
    },
    [locale],
  );

  const severityLevels = useCallback(
    (key: string): string[] => {
      const dict = dictionaries[locale];
      return (dict.severityLevels as Record<string, string[]>)[key] ?? [];
    },
    [locale],
  );

  return (
    <I18nContext.Provider value={{ locale, setLocale, t, symptomName, severityLevels }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
