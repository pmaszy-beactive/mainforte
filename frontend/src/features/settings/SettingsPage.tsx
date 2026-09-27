import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useMe } from "@/hooks/useMe";
import { useFormat } from "@/hooks/useFormat";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const { t } = useTranslation();
  const me = useMe();
  const f = useFormat();
  const [params] = useSearchParams();
  const u = me.data?.user;
  const gmailConnected = params.get("gmail") === "connected";
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
      <Card className="mt-4 flex items-center justify-between gap-4 p-5">
        <div>
          <p className="text-sm font-medium">{t("settings.gmail.title")}</p>
          <p className="text-xs text-fog-500">{t("settings.gmail.subtitle")}</p>
        </div>
        {gmailConnected ? (
          <span className="text-xs font-medium text-green-500">{t("settings.gmail.connected")}</span>
        ) : (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              window.location.href = api.auth.connectGmailUrl();
            }}
          >
            {t("settings.gmail.connect")}
          </Button>
        )}
      </Card>
      <p className="mt-4 text-xs text-fog-700">{t("common.comingSoon")}</p>
    </div>
  );
}
