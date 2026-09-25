import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { useMe } from "@/hooks/useMe";
import { useFormat } from "@/hooks/useFormat";
import { PageHeader } from "@/components/ui/PageHeader";

export default function SettingsPage() {
  const { t } = useTranslation();
  const me = useMe();
  const f = useFormat();
  const u = me.data?.user;
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
      <p className="mt-4 text-xs text-fog-700">{t("common.comingSoon")}</p>
    </div>
  );
}
