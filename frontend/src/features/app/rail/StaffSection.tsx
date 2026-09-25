import { Hash, UserPlus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { RailItem, RailSection } from "./RailSection";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { useUi } from "@/stores/ui";

// Bots/personas arrive in P1. Shell: global channel pinned + empty bot list + invite.
export function StaffSection({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const active = useUi((s) => s.activeThreadId);
  const setThread = useUi((s) => s.setThread);
  const bots: { id: string; name: string; role: string }[] = [];

  const goGlobal = () => {
    setThread(null);
    nav("/app");
  };

  const invite = (
    <button className="rounded-md p-1 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus" aria-label={t("app.staff.invite")} title={t("app.staff.invite")}>
      <UserPlus className="size-3.5" />
    </button>
  );

  return (
    <RailSection title={t("app.staff.title")} collapsed={collapsed} action={invite}>
      <RailItem collapsed={collapsed} icon={<Hash className="size-4" />} label={t("app.staff.global")} active={active === null} onClick={goGlobal} />
      <div className="mt-1 space-y-0.5">
        {bots.map((b) => (
          <RailItem key={b.id} collapsed={collapsed} icon={<Users className="size-4" />} label={b.name} active={active === b.id} onClick={() => setThread(b.id)} />
        ))}
      </div>
      {!collapsed && bots.length === 0 && (
        <div className="mt-2">
          <EmptyState
            icon={<Users className="size-5" />}
            title={t("app.staff.empty")}
            hint={t("app.staff.emptyHint")}
            action={
              <Button size="sm" variant="outline" className="mt-1">
                <UserPlus className="size-3.5" /> {t("app.staff.invite")}
              </Button>
            }
          />
        </div>
      )}
    </RailSection>
  );
}
