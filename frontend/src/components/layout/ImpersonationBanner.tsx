import { Trans, useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { useMe } from "@/hooks/useMe";

export function ImpersonationBanner() {
  const { t } = useTranslation();
  const me = useMe();
  const setSession = useAuth((s) => s.setSession);
  const qc = useQueryClient();
  const stop = useMutation({
    mutationFn: api.auth.stopImpersonate,
    onSuccess: ({ token }) => {
      setSession(token, null);
      qc.clear();
    },
  });
  if (!me.data?.impersonating) return null;
  return (
    <div className="flex items-center justify-center gap-3 bg-yellow-400 px-4 py-1.5 text-sm font-medium text-yellow-950">
      <ShieldAlert className="size-4" />
      <span>
        <Trans i18nKey="impersonation.banner" values={{ email: me.data.user.email, by: me.data.impersonating.by_email }} components={{ b: <b /> }} />
      </span>
      <button className="underline underline-offset-2 hover:no-underline disabled:opacity-60" onClick={() => stop.mutate()} disabled={stop.isPending}>
        {t("impersonation.stop")}
      </button>
    </div>
  );
}
