import { useEffect, useRef, useState } from "react";
import { BookOpen, CreditCard, LogOut, Settings, ShieldCheck } from "lucide-react";
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

  // Collapsing the rail used to remove Billing/Settings/Logout from the DOM entirely (they were
  // only ever rendered when !collapsed) -- not just icon-only, genuinely unreachable until the
  // rail was expanded again. When collapsed, the same links/button now live in a popover opened
  // from the avatar, mirroring HistoryDropdown.tsx's own useState+useRef+outside-click pattern
  // (the only popover precedent in this codebase) rather than introducing a new one (T02798).
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    // `click`, not `mousedown`: this popover holds real navigation (the Billing/Settings
    // <Link>s), unlike HistoryDropdown's inert placeholder buttons this pattern was copied
    // from. mousedown fires, and closes the popover (unmounting the Link), before the
    // subsequent click event that actually drives React Router's navigation -- confirmed live,
    // every click landed on whatever was left behind once the Link had already unmounted.
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  const logout = useMutation({
    mutationFn: api.auth.logout,
    onSettled: () => {
      clear();
      qc.clear();
      nav("/login", { replace: true });
    },
  });

  const itemCls = "flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-fog-300 hover:bg-white/5 hover:text-fog-100 ring-focus";
  const name = user?.name || user?.email || "—";

  const links = (
    <>
      <Link to="/app/library" className={itemCls}>
        <BookOpen className="size-3.5" /> {t("app.profile.library")}
      </Link>
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
    </>
  );

  const avatar = (
    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ember-500 to-orange-600 text-xs font-bold text-ink-950">
      {name.slice(0, 1).toUpperCase()}
    </span>
  );

  // Billing/Settings/Logout/Library used to render permanently below the name in expanded mode --
  // fixed rail space spent on every screen for links used rarely. Now both rail states open the
  // same popover from the same trigger; only the trigger's own appearance (icon-only vs full
  // name+email row) and the popover's anchor side differ.
  return (
    <div className="border-t border-white/5 p-2">
      <div ref={ref} className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-label={name}
          aria-haspopup="true"
          aria-expanded={open}
          title={name}
          className={cn(
            "ring-focus rounded-xl",
            collapsed ? "mx-auto flex items-center justify-center rounded-full" : "flex w-full items-center gap-2.5 px-1.5 py-1.5 hover:bg-white/5",
          )}
        >
          {avatar}
          {!collapsed && (
            <div className="min-w-0 flex-1 text-left">
              <div className="truncate text-sm font-medium">{user?.name || "—"}</div>
              <div className="truncate text-[11px] text-fog-700">{user?.email}</div>
            </div>
          )}
        </button>
        {open && (
          <div
            className={cn(
              "glass absolute bottom-full z-20 mb-1.5 w-48 rounded-xl p-1.5 animate-fade-up",
              collapsed ? "left-0" : "left-0 right-0 w-auto",
            )}
          >
            <div className="truncate px-2 pb-1.5 pt-0.5 text-xs font-medium text-fog-100">{name}</div>
            <div className="grid grid-cols-2 gap-0.5">{links}</div>
          </div>
        )}
      </div>
    </div>
  );
}
