import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import { useFormat } from "@/hooks/useFormat";

export const tiers = [
  { id: "good", price: 19, features: 4, featured: false },
  { id: "better", price: 29, features: 5, featured: true },
  { id: "best", price: 59, features: 5, featured: false },
] as const;

export function Pricing() {
  const { t } = useTranslation();
  const f = useFormat();
  return (
    <section id="pricing" className="mx-auto max-w-6xl px-5 py-20">
      <h2 className="text-center text-3xl font-semibold tracking-tight">{t("pricing.title")}</h2>
      <p className="mt-3 text-center text-fog-500">{t("pricing.subtitle")}</p>
      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {tiers.map((tier) => (
          <Card key={tier.id} className={cn("relative flex flex-col p-6", tier.featured && "border-ember-500/40 shadow-glow")}>
            {tier.featured && (
              <span className="absolute -top-3 left-6 rounded-full bg-ember-500 px-2.5 py-0.5 text-[11px] font-semibold text-ink-950">
                {t("pricing.popular")}
              </span>
            )}
            <h3 className="text-lg font-semibold">{t(`pricing.tiers.${tier.id}.name`)}</h3>
            <p className="text-sm text-fog-500">{t(`pricing.tiers.${tier.id}.blurb`)}</p>
            <div className="mt-5 flex items-baseline gap-1">
              <span className="text-4xl font-semibold tracking-tight">{f.usd(tier.price)}</span>
              <span className="text-sm text-fog-500">{t("pricing.perMonth")}</span>
            </div>
            <ul className="mt-6 flex-1 space-y-2.5 text-sm">
              {Array.from({ length: tier.features }, (_, i) => (
                <li key={i} className="flex items-center gap-2 text-fog-300">
                  <Check className="size-4 text-ember-400" /> {t(`pricing.tiers.${tier.id}.features.${i}`)}
                </li>
              ))}
            </ul>
            <Link to={`/signup?plan=${tier.id}`} className="mt-8">
              <Button className="w-full" variant={tier.featured ? "primary" : "outline"}>
                {t("pricing.choose", { name: t(`pricing.tiers.${tier.id}.name`) })}
              </Button>
            </Link>
          </Card>
        ))}
      </div>
    </section>
  );
}
