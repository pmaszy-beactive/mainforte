import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShoppingBag } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { useFormat } from "@/hooks/useFormat";
import { useAuth } from "@/stores/auth";
import type { MarketplaceOrder } from "@/lib/types";

const ESCROW_TONE: Record<string, "neutral" | "amber" | "green" | "red"> = {
  none: "neutral", held: "amber", released: "green", refunded: "neutral", disputed: "red",
};

export default function MyOrdersPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState<"buying" | "selling">("buying");

  const orders = useQuery({ queryKey: ["marketplace", "orders", "mine"], queryFn: () => api.marketplace.myOrders() });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["marketplace", "orders", "mine"] });

  const release = useMutation({ mutationFn: (id: string) => api.marketplace.releaseEscrow(id), onSuccess: invalidate });
  const refund = useMutation({ mutationFn: (id: string) => api.marketplace.refundEscrow(id), onSuccess: invalidate });
  const dispute = useMutation({ mutationFn: (id: string) => api.marketplace.disputeOrder(id), onSuccess: invalidate });

  const all = orders.data?.orders ?? [];
  const buying = all.filter((o) => o.buyer_user_id === user?.id);
  const selling = all.filter((o) => o.seller_user_id === user?.id);
  const shown = tab === "buying" ? buying : selling;

  const anyPending = release.isError || refund.isError || dispute.isError;

  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader title={t("marketplace.myOrders")} />

      <div className="mb-4 flex gap-1 rounded-xl border border-white/10 p-1">
        {(["buying", "selling"] as const).map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={`flex-1 rounded-lg py-1.5 text-sm transition ring-focus ${tab === tb ? "bg-ember-500/15 text-ember-300" : "text-fog-500 hover:text-fog-100"}`}
          >
            {t(`marketplace.orders.${tb}`)}
          </button>
        ))}
      </div>

      {orders.isError && <Alert className="mb-4">{errorMessage(orders.error, t("common.error"))}</Alert>}
      {anyPending && <Alert className="mb-4">{errorMessage(release.error ?? refund.error ?? dispute.error, t("common.error"))}</Alert>}

      {!orders.isLoading && shown.length === 0 && (
        <EmptyState icon={<ShoppingBag className="size-5" />} title={t("marketplace.orders.empty")} />
      )}

      <div className="space-y-3">
        {shown.map((o) => (
          <OrderRow
            key={o.id}
            order={o}
            isSeller={tab === "selling"}
            onRelease={() => release.mutate(o.id)}
            onRefund={() => refund.mutate(o.id)}
            onDispute={() => dispute.mutate(o.id)}
            releasing={release.isPending}
            refunding={refund.isPending}
            disputing={dispute.isPending}
            f={f}
            t={t}
          />
        ))}
      </div>
    </div>
  );
}

function OrderRow({ order, isSeller, onRelease, onRefund, onDispute, releasing, refunding, disputing, f, t }: {
  order: MarketplaceOrder;
  isSeller: boolean;
  onRelease: () => void;
  onRefund: () => void;
  onDispute: () => void;
  releasing: boolean;
  refunding: boolean;
  disputing: boolean;
  f: ReturnType<typeof useFormat>;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const canEscrowAction = order.payment_method === "stripe_escrow" && order.escrow_status === "held";
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-fog-100">{f.usd(order.amount_cents / 100)}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fog-500">
            <Badge>{t(`marketplace.payment.${order.payment_method}`)}</Badge>
            <Badge tone={ESCROW_TONE[order.escrow_status]}>{t(`marketplace.escrowStatus.${order.escrow_status}`)}</Badge>
            <Badge>{t(`marketplace.orderStatus.${order.status}`)}</Badge>
          </div>
          {order.notes && <p className="mt-1.5 text-xs text-fog-700">{order.notes}</p>}
        </div>
        {canEscrowAction && (
          <div className="flex shrink-0 gap-2">
            {isSeller && (
              <Button size="sm" variant="outline" loading={releasing} onClick={onRelease}>
                {t("marketplace.orders.release")}
              </Button>
            )}
            <Button size="sm" variant="ghost" loading={refunding} onClick={onRefund}>
              {t("marketplace.orders.refund")}
            </Button>
            <Button size="sm" variant="danger" loading={disputing} onClick={onDispute}>
              {t("marketplace.orders.dispute")}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
