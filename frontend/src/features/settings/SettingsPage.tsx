import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Check, Pencil, X } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useMe, ME_KEY } from "@/hooks/useMe";
import { useFormat } from "@/hooks/useFormat";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { LOCALES, type Locale } from "@/lib/locale";
import type { Connection } from "@/lib/types";

const GOOGLE_SCOPES = ["gmail.send", "calendar"];

function supportedTimeZones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const f = useFormat();
  const qc = useQueryClient();
  const u = me.data?.user;
  const q = useQuery({ queryKey: ["settings", "connections"], queryFn: api.settings.connections });
  const google = q.data?.connections.find((c) => c.provider === "google");

  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");

  const saveName = useMutation({
    mutationFn: (name: string) => api.me.update({ name }),
    onSuccess: () => {
      setEditingName(false);
      qc.invalidateQueries({ queryKey: ME_KEY });
    },
  });

  const setLocale = useMutation({
    mutationFn: (locale: Locale) => api.me.update({ locale }),
    onMutate: (locale) => void i18n.changeLanguage(locale),
    onSettled: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });

  const setTimezone = useMutation({
    mutationFn: (timezone: string) => api.me.update({ timezone }),
    onSettled: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });

  async function disconnect(provider: string) {
    await api.settings.disconnect(provider);
    qc.invalidateQueries({ queryKey: ["settings", "connections"] });
  }

  const startEditingName = () => {
    setNameDraft(u?.name ?? "");
    saveName.reset();
    setEditingName(true);
  };

  const rowCls = "flex items-center justify-between gap-4 px-5 py-3.5 text-sm";

  return (
    <div className="mx-auto w-full max-w-2xl p-6">
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <Card className="divide-y divide-white/5 p-0">
        <div className={rowCls}>
          <span className="text-fog-500">{t("settings.name")}</span>
          {editingName ? (
            <form
              className="flex min-w-0 flex-1 items-center justify-end gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (nameDraft.trim() && nameDraft.trim() !== u?.name) saveName.mutate(nameDraft.trim());
                else setEditingName(false);
              }}
            >
              <input
                autoFocus
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                className="h-8 w-full max-w-[14rem] rounded-lg border border-white/10 bg-ink-950/60 px-2.5 text-sm"
              />
              <button type="submit" disabled={!nameDraft.trim() || saveName.isPending} className="rounded-md p-1.5 text-fog-500 hover:bg-white/5 hover:text-ember-300 ring-focus disabled:opacity-40" aria-label={t("common.save")} title={t("common.save")}>
                <Check className="size-4" />
              </button>
              <button type="button" onClick={() => setEditingName(false)} className="rounded-md p-1.5 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus" aria-label={t("common.cancel")} title={t("common.cancel")}>
                <X className="size-4" />
              </button>
            </form>
          ) : (
            <button type="button" onClick={startEditingName} className="group flex min-w-0 items-center gap-1.5 truncate font-medium ring-focus rounded-md" title={t("settings.editName")}>
              <span className="truncate">{u?.name || "—"}</span>
              <Pencil className="size-3.5 shrink-0 text-fog-700 opacity-0 transition group-hover:opacity-100" />
            </button>
          )}
        </div>
        {saveName.isError && (
          <p className="px-5 py-2 text-xs text-red-300">{t("settings.nameSaveFailed")}</p>
        )}

        <div className={rowCls}>
          <span className="text-fog-500">{t("settings.email")}</span>
          <span className="truncate font-medium">{u?.email || "—"}</span>
        </div>

        <div className={rowCls}>
          <span className="text-fog-500">{t("settings.language")}</span>
          <select
            value={i18n.language}
            disabled={setLocale.isPending}
            onChange={(e) => setLocale.mutate(e.target.value as Locale)}
            className="rounded-lg border border-white/10 bg-ink-950/60 px-2.5 py-1 text-sm font-medium"
          >
            {LOCALES.map((l) => (
              <option key={l} value={l} className="bg-ink-950 text-fog-100">
                {t(`locales.${l}`)}
              </option>
            ))}
          </select>
        </div>

        <div className={rowCls}>
          <span className="text-fog-500">{t("settings.timezone")}</span>
          <select
            value={u?.timezone || f.timeZone}
            disabled={setTimezone.isPending}
            onChange={(e) => setTimezone.mutate(e.target.value)}
            className="max-w-[14rem] rounded-lg border border-white/10 bg-ink-950/60 px-2.5 py-1 text-sm font-medium"
          >
            {supportedTimeZones().map((tz) => (
              <option key={tz} value={tz} className="bg-ink-950 text-fog-100">
                {tz}
              </option>
            ))}
          </select>
        </div>

        <div className={rowCls}>
          <span className="text-fog-500">{t("settings.workspaces")}</span>
          <span className="truncate font-medium">{me.data?.workspaces.map((w) => w.name).join(", ") || "—"}</span>
        </div>
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
