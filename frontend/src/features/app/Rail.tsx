import { Link } from "react-router";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";
import { useUi } from "@/stores/ui";
import { Logo } from "@/components/ui/Logo";
import { WidgetsSection } from "./rail/WidgetsSection";
import { StaffSection } from "./rail/StaffSection";
import { ProfileBlock } from "./rail/ProfileBlock";
import { LanguageSelect } from "./rail/LanguageSelect";

export function Rail() {
  const { t } = useTranslation();
  const collapsed = useUi((s) => s.railCollapsed);
  const toggle = useUi((s) => s.toggleRail);

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r border-white/5 bg-ink-950/50 backdrop-blur-md transition-[width] duration-200",
        collapsed ? "w-16" : "w-72",
      )}
    >
      <div className={cn("flex h-14 items-center border-b border-white/5 px-3", collapsed ? "justify-center" : "justify-between")}>
        <Link to="/app" aria-label={t("common.home")}>
          <Logo compact={collapsed} />
        </Link>
        {!collapsed && (
          <div className="flex items-center gap-1">
            <LanguageSelect collapsed={collapsed} />
            <button onClick={toggle} className="rounded-lg p-1.5 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus" aria-label={t("app.rail.collapse")}>
              <PanelLeftClose className="size-4" />
            </button>
          </div>
        )}
      </div>
      {collapsed && (
        <div className="mx-auto mt-2 flex flex-col items-center gap-1">
          <button onClick={toggle} className="rounded-lg p-1.5 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus" aria-label={t("app.rail.expand")}>
            <PanelLeftOpen className="size-4" />
          </button>
          <LanguageSelect collapsed={collapsed} />
        </div>
      )}
      <div className="flex-1 space-y-5 overflow-y-auto px-2 py-3">
        <WidgetsSection collapsed={collapsed} />
        <StaffSection collapsed={collapsed} />
      </div>
      <ProfileBlock collapsed={collapsed} />
    </aside>
  );
}
