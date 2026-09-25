import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import type { Me } from "@/lib/types";
import { api } from "@/lib/api";
import { detectLocale, detectTimezone, isLocale } from "@/lib/locale";
import { ME_KEY } from "./useMe";

/**
 * Once per session after /api/me loads:
 *  - if the server has a locale, switch the UI to it;
 *  - otherwise PATCH the detected locale/timezone up if they differ from the server's.
 */
export function useLocaleSync(me: Me | undefined) {
  const { i18n } = useTranslation();
  const qc = useQueryClient();
  const synced = useRef<string | null>(null);

  useEffect(() => {
    if (!me || synced.current === me.user.id) return;
    synced.current = me.user.id;

    const serverLocale = isLocale(me.user.locale) ? me.user.locale : null;
    const locale = serverLocale ?? detectLocale();
    const timezone = me.user.timezone || detectTimezone();
    if (i18n.language !== locale) void i18n.changeLanguage(locale);

    if (me.user.locale !== locale || me.user.timezone !== timezone) {
      void api.me
        .update({ locale, timezone })
        .then(() => qc.invalidateQueries({ queryKey: ME_KEY }))
        .catch(() => {});
    }
  }, [me, i18n, qc]);
}
