import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminWorkers } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Alert } from "@/components/ui/Alert";

type Worker = AdminWorkers["workers"][number];

function PoolControl({
  label,
  live,
  value,
  onChange,
  onSave,
  saving,
  dirty,
  saved,
  error,
}: {
  label: string;
  live: number;
  value: number;
  onChange: (n: number) => void;
  onSave: () => void;
  saving: boolean;
  dirty: boolean;
  saved: boolean;
  error?: Error | null;
}) {
  const { t } = useTranslation();
  return (
    <form
      className="glass flex flex-wrap items-end gap-3 rounded-2xl p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <label className="block space-y-1.5">
        <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{label}</span>
        <input
          type="number"
          min={0}
          max={100}
          value={value}
          onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
          className="block h-10 w-28 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm tabular-nums focus:border-ember-500/60"
        />
      </label>
      <div className="text-sm text-fog-500">
        {t("admin.workers.live")}: <b className="text-fog-100">{live}</b>
      </div>
      <Button type="submit" loading={saving} disabled={!dirty}>
        {t("common.save")}
      </Button>
      {saved && <span className="text-xs text-emerald-300">{t("common.saved")}</span>}
      {error && <span className="text-xs text-red-300">{error.message}</span>}
    </form>
  );
}

export default function WorkersTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "workers"], queryFn: api.admin.workers, refetchInterval: 10_000 });

  const [desired, setDesired] = useState<number>(0);
  const [sandboxDesired, setSandboxDesired] = useState<number>(0);
  useEffect(() => {
    if (q.data) {
      setDesired(q.data.pools.full);
      setSandboxDesired(q.data.pools.sandbox);
    }
  }, [q.data]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["admin", "workers"] });
  const save = useMutation({ mutationFn: api.admin.setDesiredWorkers, onSuccess: invalidate });
  const saveSandbox = useMutation({ mutationFn: api.admin.setDesiredSandboxWorkers, onSuccess: invalidate });

  const destroy = useMutation({ mutationFn: api.admin.destroyWorker, onSuccess: invalidate });
  const [armedId, setArmedId] = useState<string | null>(null);

  const isSandbox = (w: Worker) => w.container_name.includes("-sandbox-");
  const liveFull = q.data?.workers.filter((w) => !isSandbox(w)).length ?? 0;
  const liveSandbox = q.data?.workers.filter(isSandbox).length ?? 0;

  const columns: Column<Worker>[] = [
    { key: "id", header: "ID", render: (w) => <span className="font-mono text-xs">{w.id}</span> },
    {
      key: "status",
      header: t("admin.workers.status"),
      render: (w) => <Badge tone={w.status === "online" ? "green" : w.status === "offline" ? "red" : "amber"}>{w.status}</Badge>,
    },
    { key: "version", header: t("admin.workers.version"), render: (w) => <span className="font-mono text-xs">{w.version ?? "—"}</span> },
    { key: "hb", header: t("admin.workers.heartbeat"), render: (w) => <span className="text-fog-500">{f.relative(w.last_heartbeat)}</span> },
    { key: "job", header: t("admin.workers.currentJob"), render: (w) => <span className="font-mono text-xs text-fog-500">{w.current_job ?? "—"}</span> },
    {
      key: "actions",
      header: "",
      render: (w) => {
        const armed = armedId === w.id;
        return (
          <Button
            size="sm"
            variant="danger"
            loading={destroy.isPending && destroy.variables === w.id}
            onClick={() => {
              if (armed) {
                destroy.mutate(w.id);
                setArmedId(null);
              } else {
                setArmedId(w.id);
              }
            }}
          >
            {armed ? t("admin.workers.confirmDestroy") : t("admin.workers.destroy")}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      {q.data && !q.data.reconciler_configured && <Alert tone="info">{t("admin.workers.notConfigured")}</Alert>}
      <div className="flex flex-wrap gap-4">
        <PoolControl
          label={t("admin.workers.fullPool")}
          live={liveFull}
          value={desired}
          onChange={setDesired}
          onSave={() => save.mutate(desired)}
          saving={save.isPending}
          dirty={q.data?.pools.full !== desired}
          saved={save.isSuccess}
          error={save.error}
        />
        <PoolControl
          label={t("admin.workers.sandboxPool")}
          live={liveSandbox}
          value={sandboxDesired}
          onChange={setSandboxDesired}
          onSave={() => saveSandbox.mutate(sandboxDesired)}
          saving={saveSandbox.isPending}
          dirty={q.data?.pools.sandbox !== sandboxDesired}
          saved={saveSandbox.isSuccess}
          error={saveSandbox.error}
        />
      </div>
      {destroy.isError && <Alert tone="error">{destroy.error.message}</Alert>}
      <Table columns={columns} rows={q.data?.workers} rowKey={(w) => w.id} loading={q.isLoading} error={q.error} empty={t("admin.workers.empty")} />
    </div>
  );
}
