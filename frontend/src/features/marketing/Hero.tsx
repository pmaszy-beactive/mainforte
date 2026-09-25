import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";

const staff = ["jeeves", "margo", "reed"] as const;

export function Hero() {
  const { t } = useTranslation();
  return (
    <section className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-[-20rem] h-[40rem] w-[60rem] -translate-x-1/2 rounded-full bg-ember-500/10 blur-3xl" />
      </div>
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-5 pb-24 pt-20 md:grid-cols-2 md:pt-28">
        <div className="animate-fade-up">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-ember-500/30 bg-ember-500/10 px-3 py-1 text-xs font-medium text-ember-300">
            <Sparkles className="size-3.5" /> {t("hero.badge")}
          </span>
          <h1 className="mt-6 text-5xl font-semibold leading-[1.02] tracking-tight text-fog-100 md:text-6xl">
            {t("hero.title1")}
            <br />
            <span className="bg-gradient-to-r from-ember-300 via-ember-500 to-orange-400 bg-clip-text text-transparent">
              {t("hero.title2")}
            </span>
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-fog-300">
            {t("hero.lead")}
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link to="/signup">
              <Button size="lg">
                {t("hero.cta")} <ArrowRight className="size-4" />
              </Button>
            </Link>
            <a href="#pricing">
              <Button size="lg" variant="outline">
                {t("hero.seePricing")}
              </Button>
            </a>
          </div>
        </div>

        <div className="glass relative rounded-3xl p-5 animate-fade-up [animation-delay:120ms]">
          <div className="mb-4 flex items-center gap-2 text-xs text-fog-500">
            <span className="size-2 rounded-full bg-emerald-400 animate-pulse-soft" /> {t("app.staff.global")}
          </div>
          <ul className="space-y-3">
            {staff.map((s, i) => (
              <li key={s} className="flex items-start gap-3 animate-fade-up" style={{ animationDelay: `${250 + i * 140}ms` }}>
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-600 to-ink-800 text-sm font-semibold text-ember-300 ring-1 ring-white/10">
                  {t(`hero.staff.${s}.name`)[0]}
                </span>
                <div className="max-w-[85%] rounded-bubble rounded-tl-md bg-ink-700/80 px-4 py-2.5 ring-1 ring-white/5">
                  <div className="mb-0.5 text-[11px] font-medium text-fog-500">
                    {t(`hero.staff.${s}.name`)} <span className="text-fog-700">· {t(`hero.staff.${s}.role`)}</span>
                  </div>
                  <p className="text-sm text-fog-100">{t(`hero.staff.${s}.line`)}</p>
                </div>
              </li>
            ))}
            <li className="flex justify-end animate-fade-up [animation-delay:700ms]">
              <div className="rounded-bubble rounded-tr-md bg-ember-500 px-4 py-2.5 text-sm font-medium text-ink-950 shadow-glow">
                {t("hero.userLine")}
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}
