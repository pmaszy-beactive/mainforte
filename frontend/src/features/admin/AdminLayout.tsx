import { Suspense } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Logo } from "@/components/ui/Logo";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

const tabs = ["users", "finances", "errors", "jobs", "workers", "events"] as const;

export default function AdminLayout() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-10 border-b border-white/5 bg-ink-900/70 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-5">
          <Logo />
          <span className="rounded-md bg-ember-500/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-ember-300">{t("admin.badge")}</span>
          <Link to="/app" className="ml-auto inline-flex items-center gap-1.5 text-xs text-fog-500 hover:text-fog-100">
            <ArrowLeft className="size-3.5" /> {t("admin.backToApp")}
          </Link>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-5">
          {tabs.map((tab) => (
            <NavLink
              key={tab}
              to={tab}
              className={({ isActive }) =>
                cn(
                  "-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition",
                  isActive ? "border-ember-500 text-fog-100" : "border-transparent text-fog-500 hover:text-fog-300",
                )
              }
            >
              {t(`admin.tabs.${tab}`)}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 p-5">
        <Suspense fallback={<FullPageSpinner />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
