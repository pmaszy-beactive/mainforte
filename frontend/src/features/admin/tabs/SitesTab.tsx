import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminSites } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Alert } from "@/components/ui/Alert";

type SiteRow = AdminSites["sites"][number];

const STATUS_TONE: Record<string, "green" | "red" | "amber"> = {
  ready: "green",
  published: "green",
  error: "red",
  destroying: "red",
  provisioning: "amber",
  building: "amber",
};

export default function SitesTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "sites"], queryFn: api.admin.sites, refetchInterval: 10_000 });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["admin", "sites"] });
  const destroy = useMutation({ mutationFn: api.admin.destroySite, onSuccess: invalidate });
  const [armedId, setArmedId] = useState<string | null>(null);

  const columns: Column<SiteRow>[] = [
    {
      key: "name",
      header: t("admin.sites.name"),
      render: (s) => (
        <div>
          <div className="text-fog-100">{s.name}</div>
          <div className="font-mono text-xs text-fog-500">{s.slug}</div>
        </div>
      ),
    },
    { key: "workspace", header: t("admin.sites.workspace"), render: (s) => <span className="text-fog-300">{s.workspace_name}</span> },
    {
      key: "status",
      header: t("admin.sites.status"),
      render: (s) => <Badge tone={STATUS_TONE[s.status] ?? "amber"}>{s.status}</Badge>,
    },
    { key: "stage", header: t("admin.sites.stage"), render: (s) => <Badge tone={s.stage === "published" ? "green" : "amber"}>{s.stage}</Badge> },
    { key: "version", header: t("admin.sites.sourceVersion"), render: (s) => <span className="tabular-nums text-fog-500">{s.source_version}</span> },
    { key: "created", header: t("admin.sites.created"), render: (s) => <span className="text-fog-500">{f.relative(s.created_at)}</span> },
    {
      key: "error",
      header: t("admin.sites.lastError"),
      render: (s) => <span className="max-w-xs truncate text-xs text-red-300" title={s.last_error ?? undefined}>{s.last_error ?? "—"}</span>,
    },
    {
      key: "actions",
      header: "",
      render: (s) => {
        const armed = armedId === s.id;
        return (
          <Button
            size="sm"
            variant="danger"
            loading={destroy.isPending && destroy.variables === s.id}
            onClick={() => {
              if (armed) {
                destroy.mutate(s.id);
                setArmedId(null);
              } else {
                setArmedId(s.id);
              }
            }}
          >
            {armed ? t("admin.sites.confirmDestroy") : t("admin.sites.destroy")}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      {destroy.isError && <Alert tone="error">{destroy.error.message}</Alert>}
      <Table columns={columns} rows={q.data?.sites} rowKey={(s) => s.id} loading={q.isLoading} error={q.error} empty={t("admin.sites.empty")} />
    </div>
  );
}
