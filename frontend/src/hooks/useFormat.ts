import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/stores/auth";
import { detectTimezone } from "@/lib/locale";

/** Intl formatters bound to the user's locale and timezone. */
export function useFormat() {
  const { i18n } = useTranslation();
  const user = useAuth((s) => s.user);
  const locale = i18n.language;
  const timeZone = user?.timezone || detectTimezone();

  return useMemo(() => {
    const safe = (opts: Intl.DateTimeFormatOptions) => {
      try {
        return new Intl.DateTimeFormat(locale, { timeZone, ...opts });
      } catch {
        return new Intl.DateTimeFormat(locale, opts);
      }
    };
    const dateTime = safe({ dateStyle: "medium", timeStyle: "short" });
    const date = safe({ dateStyle: "medium" });
    const time = safe({ timeStyle: "short" });
    const num = new Intl.NumberFormat(locale);
    const usd = new Intl.NumberFormat(locale, { style: "currency", currency: "USD" });
    const rel = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    const toDate = (v: string | number | Date) => (v instanceof Date ? v : new Date(v));
    const valid = (d: Date) => !Number.isNaN(d.getTime());

    return {
      locale,
      timeZone,
      dateTime: (v: string | number | Date | null | undefined) => (v == null || !valid(toDate(v)) ? "" : dateTime.format(toDate(v))),
      date: (v: string | number | Date | null | undefined) => (v == null || !valid(toDate(v)) ? "" : date.format(toDate(v))),
      time: (v: string | number | Date | null | undefined) => (v == null || !valid(toDate(v)) ? "" : time.format(toDate(v))),
      number: (n: number) => num.format(n),
      bytes: (n: number) => {
        const units = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
        let i = 0;
        let v = n;
        while (v >= 1024 && i < units.length - 1) {
          v /= 1024;
          i++;
        }
        try {
          return new Intl.NumberFormat(locale, { style: "unit", unit: units[i], maximumFractionDigits: i === 0 ? 0 : 1 }).format(v);
        } catch {
          return `${v.toFixed(i === 0 ? 0 : 1)} ${["B", "KB", "MB", "GB"][i]}`;
        }
      },
      usd: (n: number) => usd.format(n),
      relative: (v: string | number | Date) => {
        const d = toDate(v);
        if (!valid(d)) return "";
        const s = Math.round((d.getTime() - Date.now()) / 1000);
        const a = Math.abs(s);
        if (a < 60) return rel.format(s, "second");
        if (a < 3600) return rel.format(Math.round(s / 60), "minute");
        if (a < 86400) return rel.format(Math.round(s / 3600), "hour");
        return rel.format(Math.round(s / 86400), "day");
      },
    };
  }, [locale, timeZone]);
}
