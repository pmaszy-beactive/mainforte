import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { useFormat } from "@/hooks/useFormat";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Alert } from "@/components/ui/Alert";

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
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {stats.map(([label, value, cls]) => (
        <Card key={label} className="p-5">
          <div className="text-xs uppercase tracking-wider text-fog-500">{label}</div>
          <div className={"mt-2 text-2xl font-semibold tabular-nums " + (cls ?? "")}>{value}</div>
        </Card>
      ))}
    </div>
  );
}
