import { Languages } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { LOCALES, type Locale } from "@/lib/locale";
import { ME_KEY } from "@/hooks/useMe";
import { Dropdown } from "@/components/ui/Dropdown";

export function LanguageSelect({ collapsed }: { collapsed: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();

  const setLocale = useMutation({
    mutationFn: (locale: Locale) => api.me.update({ locale }),
    onMutate: (locale) => void i18n.changeLanguage(locale),
    onSettled: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });

  return (
    <div className="relative" title={t("app.profile.language")}>
      <Languages className="pointer-events-none absolute left-1.5 top-1/2 size-3.5 -translate-y-1/2 text-fog-500" />
      <Dropdown
        label={t("app.profile.language")}
        value={i18n.language as Locale}
        options={LOCALES}
        disabled={setLocale.isPending}
        onChange={(l) => setLocale.mutate(l)}
        trigger={collapsed ? i18n.language : t(`locales.${i18n.language as Locale}`)}
        renderOption={(l) => (collapsed ? l : t(`locales.${l}`))}
      />
    </div>
  );
}
