import type { ReactNode } from "react";

export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 px-3 py-5 text-center">
      {icon && <div className="text-fog-700">{icon}</div>}
      <p className="text-sm text-fog-300">{title}</p>
      {hint && <p className="text-xs text-fog-700">{hint}</p>}
      {action}
    </div>
  );
}
