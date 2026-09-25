import { useTranslation } from "react-i18next";
import { Bot, Globe, LayoutDashboard } from "lucide-react";
import { Card } from "@/components/ui/Card";

const items = [
  { id: "browse", icon: Globe },
  { id: "team", icon: Bot },
  { id: "widgets", icon: LayoutDashboard },
] as const;

export function Benefits() {
  const { t } = useTranslation();
  return (
    <section id="benefits" className="mx-auto max-w-6xl px-5 py-20">
      <h2 className="text-center text-3xl font-semibold tracking-tight">{t("benefits.title")}</h2>
      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {items.map(({ id, icon: Icon }) => (
          <Card key={id} className="group p-6 transition hover:border-ember-500/30">
            <span className="grid size-11 place-items-center rounded-xl bg-ember-500/10 text-ember-400 ring-1 ring-ember-500/20 transition group-hover:shadow-glow">
              <Icon className="size-5" />
            </span>
            <h3 className="mt-5 text-lg font-semibold">{t(`benefits.items.${id}.title`)}</h3>
            <p className="mt-2 text-sm leading-relaxed text-fog-300">{t(`benefits.items.${id}.body`)}</p>
          </Card>
        ))}
      </div>
    </section>
  );
}
