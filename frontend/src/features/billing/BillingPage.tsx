import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { loadStripe } from "@stripe/stripe-js";
import { Elements } from "@stripe/react-stripe-js";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useFormat } from "@/hooks/useFormat";
import { useUi } from "@/stores/ui";
import type { BillingPlan, BillingPrice } from "@/lib/types";
import { CardSetupForm } from "./CardSetupForm";
import { CreditCard } from "lucide-react";

const stripePromise = (() => {
  const key = import.meta.env.VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY as string | undefined;
  return key ? loadStripe(key) : null;
})();

const STATUS_TONE: Record<string, "success" | "info" | "error"> = {
  active: "success",
  incomplete: "info",
  requires_action: "info",
  past_due: "error",
  canceled: "error",
  unpaid: "error",
};

function monthlyPrice(plan: BillingPlan): BillingPrice | undefined {
  return plan.prices.find((p) => p.interval === "month") ?? plan.prices[0];
}

export default function BillingPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();
  const wsId = useUi((s) => s.workspaceId);
  const [clientSecret, setClientSecret] = useState<string | null>(null);

  const billing = useQuery({
    queryKey: ["billing", wsId],
    queryFn: () => api.billing.get(wsId!),
    enabled: !!wsId,
  });

  const startCardSetup = useMutation({
    mutationFn: () => api.billing.createSetupIntent(wsId!),
    onSuccess: (r) => setClientSecret(r.client_secret),
  });

  const confirmCardSetup = useMutation({
    mutationFn: (setupIntentId: string) => api.billing.confirmSetupIntent(wsId!, setupIntentId),
    onSuccess: () => {
      setClientSecret(null);
      qc.invalidateQueries({ queryKey: ["billing", wsId] });
    },
  });

  const subscribe = useMutation({
    mutationFn: (priceId: string) => api.billing.subscribe(wsId!, { price_id: priceId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing", wsId] }),
  });

  const cancel = useMutation({
    mutationFn: () => api.billing.cancel(wsId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing", wsId] }),
  });

  const currentPlan = useMemo(() => {
    if (!billing.data?.subscription) return null;
    return billing.data.plans.find((p) => p.id === billing.data!.subscription!.plan_id) ?? null;
  }, [billing.data]);

  if (!wsId) {
    return (
      <div className="mx-auto w-full max-w-3xl p-6">
        <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} />
        <EmptyState icon={<CreditCard className="size-5" />} title={t("chat.noWorkspace")} />
      </div>
    );
  }

  const sub = billing.data?.subscription ?? null;
  const hasCard = billing.data?.has_card ?? false;

  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} />

      {billing.isError && <Alert>{errorMessage(billing.error, t("common.error"))}</Alert>}

      {sub && (
        <Card className="mb-4 p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold">
                {t("billing.current")}: {currentPlan?.name ?? sub.plan_id}
              </div>
              <div className="mt-1 text-xs text-fog-500">
                {sub.current_period_end && !sub.cancel_at_period_end
                  ? t("billing.renewsOn", { date: f.date(sub.current_period_end) })
                  : null}
                {sub.cancel_at_period_end && t("billing.cancelAtPeriodEnd")}
              </div>
            </div>
            <Alert tone={STATUS_TONE[sub.status] ?? "info"} className="py-1">
              {t(`billing.status.${sub.status}`)}
            </Alert>
          </div>

          {sub.status === "requires_action" && (
            <p className="mt-3 text-sm text-fog-300">{t("billing.requiresAction")}</p>
          )}

          {!sub.cancel_at_period_end && sub.status !== "canceled" && (
            <Button
              size="sm"
              variant="outline"
              className="mt-4"
              onClick={() => cancel.mutate()}
              loading={cancel.isPending}
            >
              {cancel.isPending ? t("billing.canceling") : t("billing.cancel")}
            </Button>
          )}
          {cancel.isError && (
            <Alert className="mt-3">{errorMessage(cancel.error, t("common.error"))}</Alert>
          )}
        </Card>
      )}

      <Card className="mb-4 p-5">
        <div className="text-sm font-semibold">{t("billing.card.title")}</div>
        <p className="mt-1 text-xs text-fog-500">{hasCard ? t("billing.card.onFile") : t("billing.card.none")}</p>

        {!clientSecret && (
          <Button
            size="sm"
            variant="outline"
            className="mt-3"
            onClick={() => startCardSetup.mutate()}
            loading={startCardSetup.isPending}
          >
            {t("billing.card.save")}
          </Button>
        )}
        {startCardSetup.isError && (
          <Alert className="mt-3">{errorMessage(startCardSetup.error, t("common.error"))}</Alert>
        )}
        {confirmCardSetup.isError && (
          <Alert className="mt-3">{errorMessage(confirmCardSetup.error, t("common.error"))}</Alert>
        )}
        {confirmCardSetup.isSuccess && <Alert tone="success" className="mt-3">{t("billing.card.saved")}</Alert>}

        {clientSecret && stripePromise && (
          <div className="mt-3">
            <Elements stripe={stripePromise} options={{ clientSecret }}>
              <CardSetupForm onSaved={(setupIntentId) => confirmCardSetup.mutate(setupIntentId)} />
            </Elements>
          </div>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        {(billing.data?.plans ?? []).map((plan) => {
          const price = monthlyPrice(plan);
          const isCurrent = currentPlan?.id === plan.id && sub?.status !== "canceled";
          return (
            <Card key={plan.id} className={cn("p-5", isCurrent && "border-ember-500/40")}>
              <div className="text-sm font-semibold">{plan.name}</div>
              {price && (
                <div className="mt-1 text-2xl font-semibold">
                  {f.usd(price.amount_cents / 100)}
                  <span className="text-xs font-normal text-fog-500">{t("billing.perMonth")}</span>
                </div>
              )}
              <Button
                size="sm"
                variant={isCurrent ? "primary" : "outline"}
                className="mt-4 w-full"
                disabled={isCurrent || !price || !hasCard}
                loading={subscribe.isPending}
                onClick={() => price && subscribe.mutate(price.id)}
              >
                {isCurrent ? t("billing.status.active") : t("billing.choose")}
              </Button>
            </Card>
          );
        })}
        {!billing.isLoading && (billing.data?.plans.length ?? 0) === 0 && (
          <Card className="p-5 text-sm text-fog-500 sm:col-span-3">{t("billing.placeholder")}</Card>
        )}
      </div>

      {!hasCard && (billing.data?.plans.length ?? 0) > 0 && (
        <p className="mt-3 text-xs text-fog-500">{t("billing.subscribeNeedsCard")}</p>
      )}
      {subscribe.isError && <Alert className="mt-3">{errorMessage(subscribe.error, t("common.error"))}</Alert>}
    </div>
  );
}
