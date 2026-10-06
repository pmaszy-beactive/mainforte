import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Image as ImageIcon, LayoutGrid, Library, Video, Globe } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { useFormat } from "@/hooks/useFormat";
import { useUi } from "@/stores/ui";
import type { LibraryUpload, Site, Widget } from "@/lib/types";

function fileIcon(contentType: string) {
  if (contentType.startsWith("image/")) return <ImageIcon className="size-4" />;
  if (contentType.startsWith("video/")) return <Video className="size-4" />;
  return <FileText className="size-4" />;
}

export default function LibraryPage() {
  const { t } = useTranslation();
  const wsId = useUi((s) => s.workspaceId);
  const [tab, setTab] = useState<"in" | "out">("in");

  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader title={t("library.title")} subtitle={t("library.subtitle")} />

      <div className="mb-4 flex gap-1 rounded-xl border border-white/10 p-1">
        {(["in", "out"] as const).map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={`flex-1 rounded-lg py-1.5 text-sm transition ring-focus ${tab === tb ? "bg-ember-500/15 text-ember-300" : "text-fog-500 hover:text-fog-100"}`}
          >
            {t(`library.tabs.${tb}`)}
          </button>
        ))}
      </div>

      {!wsId ? <EmptyState icon={<Library className="size-5" />} title={t("chat.noWorkspace")} /> : tab === "in" ? <InTab wsId={wsId} /> : <OutTab wsId={wsId} />}
    </div>
  );
}

function InTab({ wsId }: { wsId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState<string | null>(null);

  const uploads = useQuery({ queryKey: ["library", "uploads", wsId], queryFn: () => api.library.uploads.list(wsId) });
  const remove = useMutation({
    mutationFn: (id: string) => api.library.uploads.remove(wsId, id),
    onSuccess: () => {
      setConfirming(null);
      qc.invalidateQueries({ queryKey: ["library", "uploads", wsId] });
    },
  });

  const list = uploads.data ?? [];

  return (
    <>
      {uploads.isError && <Alert className="mb-4">{errorMessage(uploads.error, t("common.error"))}</Alert>}
      {remove.isError && <Alert className="mb-4">{errorMessage(remove.error, t("common.error"))}</Alert>}
      {!uploads.isLoading && list.length === 0 && <EmptyState icon={<FileText className="size-5" />} title={t("library.in.empty")} hint={t("library.in.emptyHint")} />}
      <div className="space-y-2">
        {list.map((u) => (
          <UploadRow
            key={u.id}
            upload={u}
            f={f}
            t={t}
            confirming={confirming === u.id}
            onDeleteClick={() => setConfirming(u.id)}
            onCancel={() => setConfirming(null)}
            onConfirm={() => remove.mutate(u.id)}
            deleting={remove.isPending && remove.variables === u.id}
          />
        ))}
      </div>
    </>
  );
}

function UploadRow({ upload, f, t, confirming, onDeleteClick, onCancel, onConfirm, deleting }: {
  upload: LibraryUpload;
  f: ReturnType<typeof useFormat>;
  t: (key: string, opts?: Record<string, unknown>) => string;
  confirming: boolean;
  onDeleteClick: () => void;
  onCancel: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <Card className="flex items-center gap-3 p-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white/5 text-fog-500">{fileIcon(upload.content_type)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-fog-100">{upload.name}</div>
        <div className="text-xs text-fog-700">
          {f.bytes(upload.size)} · {f.date(upload.created_at)}
        </div>
      </div>
      {confirming ? (
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-fog-500">{t("library.deleteConfirm")}</span>
          <Button size="sm" variant="danger" loading={deleting} onClick={onConfirm}>
            {t("library.delete")}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={deleting}>
            {t("common.cancel")}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="ghost" onClick={onDeleteClick}>
          {t("library.delete")}
        </Button>
      )}
    </Card>
  );
}

function OutTab({ wsId }: { wsId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState<string | null>(null);

  const widgets = useQuery({ queryKey: ["library", "widgets", wsId], queryFn: () => api.widgets.list(wsId) });
  const sites = useQuery({ queryKey: ["library", "sites", wsId], queryFn: () => api.sites.list(wsId) });

  const removeWidget = useMutation({
    mutationFn: (id: string) => api.widgets.remove(wsId, id),
    onSuccess: () => {
      setConfirming(null);
      qc.invalidateQueries({ queryKey: ["library", "widgets", wsId] });
    },
  });
  const destroySite = useMutation({
    mutationFn: (id: string) => api.sites.destroy(wsId, id),
    onSuccess: () => {
      setConfirming(null);
      qc.invalidateQueries({ queryKey: ["library", "sites", wsId] });
    },
  });

  const loading = widgets.isLoading || sites.isLoading;
  const widgetList = widgets.data ?? [];
  const siteList = sites.data ?? [];
  const empty = !loading && widgetList.length === 0 && siteList.length === 0;

  return (
    <>
      {widgets.isError && <Alert className="mb-4">{errorMessage(widgets.error, t("common.error"))}</Alert>}
      {sites.isError && <Alert className="mb-4">{errorMessage(sites.error, t("common.error"))}</Alert>}
      {(removeWidget.isError || destroySite.isError) && (
        <Alert className="mb-4">{errorMessage(removeWidget.error ?? destroySite.error, t("common.error"))}</Alert>
      )}
      {empty && <EmptyState icon={<LayoutGrid className="size-5" />} title={t("library.out.empty")} hint={t("library.out.emptyHint")} />}
      <div className="space-y-2">
        {widgetList.map((w) => (
          <WidgetRow
            key={w.id}
            widget={w}
            t={t}
            confirming={confirming === w.id}
            onDeleteClick={() => setConfirming(w.id)}
            onCancel={() => setConfirming(null)}
            onConfirm={() => removeWidget.mutate(w.id)}
            deleting={removeWidget.isPending && removeWidget.variables === w.id}
          />
        ))}
        {siteList.map((s) => (
          <SiteRow
            key={s.id}
            site={s}
            f={f}
            t={t}
            confirming={confirming === s.id}
            onDeleteClick={() => setConfirming(s.id)}
            onCancel={() => setConfirming(null)}
            onConfirm={() => destroySite.mutate(s.id)}
            deleting={destroySite.isPending && destroySite.variables === s.id}
          />
        ))}
      </div>
    </>
  );
}

function WidgetRow({ widget, t, confirming, onDeleteClick, onCancel, onConfirm, deleting }: {
  widget: Widget;
  t: (key: string, opts?: Record<string, unknown>) => string;
  confirming: boolean;
  onDeleteClick: () => void;
  onCancel: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <Card className="flex items-center gap-3 p-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white/5 text-fog-500">
        <LayoutGrid className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <a href={widget.url} target="_blank" rel="noreferrer" className="truncate text-sm font-medium text-fog-100 hover:text-ember-300">
          {widget.title}
        </a>
        <div className="flex items-center gap-1.5 text-xs text-fog-700">
          <Badge>{t("library.out.widget")}</Badge>
        </div>
      </div>
      {confirming ? (
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-fog-500">{t("library.deleteConfirm")}</span>
          <Button size="sm" variant="danger" loading={deleting} onClick={onConfirm}>
            {t("library.delete")}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={deleting}>
            {t("common.cancel")}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="ghost" onClick={onDeleteClick}>
          {t("library.delete")}
        </Button>
      )}
    </Card>
  );
}

function SiteRow({ site, f, t, confirming, onDeleteClick, onCancel, onConfirm, deleting }: {
  site: Site;
  f: ReturnType<typeof useFormat>;
  t: (key: string, opts?: Record<string, unknown>) => string;
  confirming: boolean;
  onDeleteClick: () => void;
  onCancel: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <Card className="flex items-center gap-3 p-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white/5 text-fog-500">
        <Globe className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <a href={site.published_url ?? site.preview_url} target="_blank" rel="noreferrer" className="truncate text-sm font-medium text-fog-100 hover:text-ember-300">
          {site.name}
        </a>
        <div className="flex items-center gap-1.5 text-xs text-fog-700">
          <Badge>{t("library.out.site")}</Badge>
          <Badge tone={site.has_error ? "red" : site.is_destroying ? "amber" : "neutral"}>{site.status_label}</Badge>
          <span>{f.date(site.created_at)}</span>
        </div>
      </div>
      {site.is_destroying ? (
        <span className="shrink-0 text-xs text-fog-700" title={t("library.out.alreadyDestroying")}>
          {t("library.out.alreadyDestroying")}
        </span>
      ) : confirming ? (
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-fog-500">{t("library.deleteConfirm")}</span>
          <Button size="sm" variant="danger" loading={deleting} onClick={onConfirm}>
            {t("library.delete")}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={deleting}>
            {t("common.cancel")}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="ghost" onClick={onDeleteClick}>
          {t("library.delete")}
        </Button>
      )}
    </Card>
  );
}
