import { CreditCard, LogOut, Settings, ShieldCheck } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { useMe } from "@/hooks/useMe";
import { cn } from "@/lib/cn";

export function ProfileBlock({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const me = useMe();
  const user = me.data?.user;
  const clear = useAuth((s) => s.clear);
  const qc = useQueryClient();
  const nav = useNavigate();

  const logout = useMutation({
    mutationFn: api.auth.logout,
    onSettled: () => {
      clear();
      qc.clear();
      nav("/login", { replace: true });
    },
  });

  const itemCls = "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-fog-300 hover:bg-white/5 hover:text-fog-100 ring-focus";

  return (
    <div className="border-t border-white/5 p-2">
      <div className={cn("flex items-center gap-2.5 px-1.5 py-1.5", collapsed && "justify-center")}>
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ember-500 to-orange-600 text-xs font-bold text-ink-950">
          {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
        </span>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.name || "—"}</div>
            <div className="truncate text-[11px] text-fog-700">{user?.email}</div>
          </div>
        )}
      </div>
      {!collapsed && (
        <div className="mt-1 grid grid-cols-2 gap-0.5">
          <Link to="/app/billing" className={itemCls}>
            <CreditCard className="size-3.5" /> {t("app.profile.billing")}
          </Link>
          <Link to="/app/settings" className={itemCls}>
            <Settings className="size-3.5" /> {t("app.profile.settings")}
          </Link>
          <button className={itemCls} onClick={() => logout.mutate()} disabled={logout.isPending}>
            <LogOut className="size-3.5" /> {t("app.profile.logout")}
          </button>
          {user?.role === "superuser" && (
            <Link to="/admin" className={cn(itemCls, "col-span-2 text-ember-300")}>
              <ShieldCheck className="size-3.5" /> {t("app.profile.admin")}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
