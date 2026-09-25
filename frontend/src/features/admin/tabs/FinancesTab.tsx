import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminUsageByWorkspace } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Alert } from "@/components/ui/Alert";
import { Table, type Column } from "@/components/ui/Table";

export default function FinancesTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["admin", "finances"], queryFn: api.admin.finances, refetchInterval: 60_000 });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <Alert>{q.error.message}</Alert>;
  const d = q.data!;
  const margin = d.ai_charged_usd - d.ai_cost_usd;
  const stats: [string, string, string?][] = [
    [t("admin.finances.mrr"), f.usd(d.mrr_cents / 100)],
    [t("admin.finances.activeSubs"), f.number(d.active_subscriptions)],
    [t("admin.finances.failedPayments"), f.number(d.failed_payments), d.failed_payments > 0 ? "text-red-300" : undefined],
    [t("admin.finances.aiCost"), f.usd(d.ai_cost_usd)],
    [t("admin.finances.aiCharged"), f.usd(d.ai_charged_usd)],
    [t("admin.finances.aiMargin"), f.usd(margin), margin < 0 ? "text-red-300" : "text-emerald-300"],
  ];

  const usageColumns: Column<AdminUsageByWorkspace>[] = [
    { key: "ws", header: t("admin.finances.workspace"), render: (r) => r.ws_name },
    { key: "in", header: t("admin.finances.inputTokens"), render: (r) => <span className="tabular-nums">{f.number(r.input_tokens)}</span> },
    { key: "out", header: t("admin.finances.outputTokens"), render: (r) => <span className="tabular-nums">{f.number(r.output_tokens)}</span> },
    { key: "cost", header: t("admin.finances.cost"), render: (r) => <span className="tabular-nums">{f.usd(r.cost_usd)}</span> },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map(([label, value, cls]) => (
          <Card key={label} className="p-5">
            <div className="text-xs uppercase tracking-wider text-fog-500">{label}</div>
            <div className={"mt-2 text-2xl font-semibold tabular-nums " + (cls ?? "")}>{value}</div>
          </Card>
        ))}
      </div>
      <div>
        <div className="mb-2 text-xs uppercase tracking-wider text-fog-500">{t("admin.finances.usageByWorkspace")}</div>
        <Table
          columns={usageColumns}
          rows={d.usage_by_workspace}
          rowKey={(r) => r.ws_id}
          empty={t("admin.finances.usageEmpty")}
        />
      </div>
    </div>
  );
}
