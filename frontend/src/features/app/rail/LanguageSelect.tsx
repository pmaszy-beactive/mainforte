import { Languages } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { LOCALES, type Locale } from "@/lib/locale";
import { ME_KEY } from "@/hooks/useMe";

export function LanguageSelect({ collapsed }: { collapsed: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();

  const setLocale = useMutation({
    mutationFn: (locale: Locale) => api.me.update({ locale }),
    onMutate: (locale) => void i18n.changeLanguage(locale),
    onSettled: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });

  return (
    <div className={collapsed ? "" : "relative"} title={t("app.profile.language")}>
      <Languages className="pointer-events-none absolute left-1.5 top-1/2 size-3.5 -translate-y-1/2 text-fog-500" />
      <select
        aria-label={t("app.profile.language")}
        value={i18n.language}
        disabled={setLocale.isPending}
        onChange={(e) => setLocale.mutate(e.target.value as Locale)}
        className="appearance-none rounded-lg bg-transparent py-1.5 pl-7 pr-1.5 text-xs text-fog-300 hover:bg-white/5 hover:text-fog-100 ring-focus"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l} className="bg-ink-950 text-fog-100">
            {collapsed ? l : t(`locales.${l}`)}
          </option>
        ))}
      </select>
    </div>
  );
}
