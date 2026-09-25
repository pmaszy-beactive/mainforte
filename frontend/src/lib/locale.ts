export const LOCALES = ["en-US", "fr-CA"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

/** Any `fr*` browser language maps to fr-CA; everything else to en-US. */
export function normalizeLocale(lang: string | null | undefined): Locale {
  if (!lang) return DEFAULT_LOCALE;
  return /^fr\b/i.test(lang) ? "fr-CA" : "en-US";
}

export function detectLocale(): Locale {
  return normalizeLocale(typeof navigator !== "undefined" ? navigator.language : undefined);
}

export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function isLocale(v: unknown): v is Locale {
  return typeof v === "string" && (LOCALES as readonly string[]).includes(v);
}
