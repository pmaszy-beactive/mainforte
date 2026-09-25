import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import enUS from "@/locales/en-US.json";
import frCA from "@/locales/fr-CA.json";
import { DEFAULT_LOCALE, LOCALES, normalizeLocale } from "@/lib/locale";

export const resources = {
  "en-US": { translation: enUS },
  "fr-CA": { translation: frCA },
} as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: [...LOCALES],
    load: "currentOnly",
    interpolation: { escapeValue: false },
    detection: {
      // navigator only; the server-side preference is applied by useLocaleSync after login.
      order: ["navigator"],
      caches: [],
      convertDetectedLanguage: (lng) => normalizeLocale(lng),
    },
  });

export default i18n;
