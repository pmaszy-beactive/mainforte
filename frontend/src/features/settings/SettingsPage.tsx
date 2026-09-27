import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useMe } from "@/hooks/useMe";
import { useFormat } from "@/hooks/useFormat";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import type { Connection } from "@/lib/types";

const GOOGLE_SCOPES = ["gmail.send", "calendar"];

export default function SettingsPage() {
  const { t } = useTranslation();
  const me = useMe();
  const f = useFormat();
  const qc = useQueryClient();
  const u = me.data?.user;
  const q = useQuery({ queryKey: ["settings", "connections"], queryFn: api.settings.connections });
  const google = q.data?.connections.find((c) => c.provider === "google");

  async function disconnect(provider: string) {
    await api.settings.disconnect(provider);
    qc.invalidateQueries({ queryKey: ["settings", "connections"] });
  }

  return (
    <div className="mx-auto w-full max-w-2xl p-6">
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <Card className="divide-y divide-white/5 p-0">
        {[
          [t("settings.name"), u?.name],
          [t("settings.email"), u?.email],
          [t("settings.language"), t(`locales.${f.locale}`)],
          [t("settings.timezone"), f.timeZone],
          [t("settings.workspaces"), me.data?.workspaces.map((w) => w.name).join(", ") || "—"],
        ].map(([k, v]) => (
          <div key={String(k)} className="flex items-center justify-between gap-4 px-5 py-3.5 text-sm">
            <span className="text-fog-500">{k}</span>
            <span className="truncate font-medium">{v || "—"}</span>
          </div>
        ))}
      </Card>

      <h2 className="mt-6 text-sm font-semibold text-fog-300">{t("settings.connections.title")}</h2>
      <p className="text-xs text-fog-500">{t("settings.connections.subtitle")}</p>
      <Card className="mt-3 flex items-center justify-between gap-4 p-5">
        <div>
          <p className="text-sm font-medium">{t("settings.connections.google.name")}</p>
          <p className="text-xs text-fog-500">{t("settings.connections.google.subtitle")}</p>
          {google && (
            <p className="mt-1 text-xs text-fog-700">
              {google.scopes
                .filter((s) => GOOGLE_SCOPES.includes(s))
                .map((s) => t(`settings.connections.scopes.${s}`))
                .join(" · ") || "—"}
            </p>
          )}
        </div>
        <ConnectionAction connection={google} onDisconnect={() => disconnect("google")} />
      </Card>
    </div>
  );
}

function ConnectionAction({ connection, onDisconnect }: { connection: Connection | undefined; onDisconnect: () => void }) {
  const { t } = useTranslation();
  const hasGoogleScopes = connection?.scopes.some((s) => GOOGLE_SCOPES.includes(s));
  if (hasGoogleScopes) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-xs font-medium text-green-500">{t("settings.connections.connected")}</span>
        <Button type="button" variant="outline" onClick={onDisconnect}>
          {t("settings.connections.disconnect")}
        </Button>
      </div>
    );
  }
  return (
    <Button
      type="button"
      variant="outline"
      onClick={() => {
        window.location.href = api.auth.connectGoogleUrl(GOOGLE_SCOPES);
      }}
    >
      {t("settings.connections.connect")}
    </Button>
  );
}
