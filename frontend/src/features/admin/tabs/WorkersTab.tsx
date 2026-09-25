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

export default function WorkersTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "workers"], queryFn: api.admin.workers, refetchInterval: 10_000 });
  const [desired, setDesired] = useState<number>(0);
  useEffect(() => {
    if (q.data) setDesired(q.data.desired);
  }, [q.data]);

  const save = useMutation({
    mutationFn: api.admin.setDesiredWorkers,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "workers"] }),
  });

  const columns: Column<Worker>[] = [
    { key: "id", header: "ID", render: (w) => <span className="font-mono text-xs">{w.id}</span> },
    {
      key: "status",
      header: t("admin.workers.status"),
      render: (w) => <Badge tone={w.status === "online" ? "green" : w.status === "offline" ? "red" : "amber"}>{w.status}</Badge>,
    },
    { key: "node", header: t("admin.workers.node"), render: (w) => w.node },
    { key: "hb", header: t("admin.workers.heartbeat"), render: (w) => <span className="text-fog-500">{f.relative(w.last_heartbeat)}</span> },
    { key: "job", header: t("admin.workers.currentJob"), render: (w) => <span className="font-mono text-xs text-fog-500">{w.current_job ?? "—"}</span> },
  ];

  return (
    <div className="space-y-4">
      <form
        className="glass flex flex-wrap items-end gap-3 rounded-2xl p-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(desired);
        }}
      >
        <label className="block space-y-1.5">
          <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("admin.workers.desired")}</span>
          <input
            type="number"
            min={0}
            max={100}
            value={desired}
            onChange={(e) => setDesired(Math.max(0, Number(e.target.value) || 0))}
            className="block h-10 w-28 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm tabular-nums focus:border-ember-500/60"
          />
        </label>
        <div className="text-sm text-fog-500">
          {t("admin.workers.live")}: <b className="text-fog-100">{f.number(q.data?.workers.length ?? 0)}</b>
        </div>
        <Button type="submit" loading={save.isPending} disabled={q.data?.desired === desired}>
          {t("common.save")}
        </Button>
        {save.isSuccess && <span className="text-xs text-emerald-300">{t("common.saved")}</span>}
      </form>
      {save.isError && <Alert>{save.error.message}</Alert>}
      <Table columns={columns} rows={q.data?.workers} rowKey={(w) => w.id} loading={q.isLoading} error={q.error} empty={t("admin.workers.empty")} />
    </div>
  );
}
