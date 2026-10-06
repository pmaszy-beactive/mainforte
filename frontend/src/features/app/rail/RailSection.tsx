import type { ReactNode } from "react";

export function RailSection({ title, action, collapsed, children }: { title: string; action?: ReactNode; collapsed: boolean; children: ReactNode }) {
  return (
    <section>
      {!collapsed && (
        <div className="mb-1.5 flex items-center justify-between px-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-fog-700">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function RailItem({ icon, label, active, collapsed, onClick, meta }: { icon: ReactNode; label: string; active?: boolean; collapsed: boolean; onClick?: () => void; meta?: ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={
        "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm transition ring-focus " +
        (active ? "bg-ember-500/10 text-ember-300 ring-1 ring-ember-500/20" : "text-fog-300 hover:bg-white/5 hover:text-fog-100") +
        (collapsed ? " justify-center" : "")
      }
    >
      <span className="shrink-0">{icon}</span>
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && meta}
    </button>
  );
}
