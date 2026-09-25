import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { tiers } from "@/features/marketing/Pricing";
import { useFormat } from "@/hooks/useFormat";
import { cn } from "@/lib/cn";

export default function BillingPage() {
  const { t } = useTranslation();
  const f = useFormat();
  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader title={t("billing.title")} subtitle={t("billing.subtitle")} />
      <div className="grid gap-4 sm:grid-cols-3">
        {tiers.map((tier) => (
          <Card key={tier.id} className={cn("p-5", tier.featured && "border-ember-500/40")}>
            <div className="text-sm font-semibold">{t(`pricing.tiers.${tier.id}.name`)}</div>
            <div className="mt-1 text-2xl font-semibold">
              {f.usd(tier.price)}
              <span className="text-xs font-normal text-fog-500">{t("pricing.perMonth")}</span>
            </div>
            <Button size="sm" variant="outline" className="mt-4 w-full" disabled>
              {t("billing.choose")}
            </Button>
          </Card>
        ))}
      </div>
      <Card className="mt-4 p-5 text-sm text-fog-500">{t("billing.placeholder")}</Card>
    </div>
  );
}
