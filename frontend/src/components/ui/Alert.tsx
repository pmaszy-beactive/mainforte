import { cn } from "@/lib/cn";

export function Alert({ tone = "error", children, className }: { tone?: "error" | "success" | "info"; children: React.ReactNode; className?: string }) {
  const t = {
    error: "border-red-500/30 bg-red-500/10 text-red-200",
    success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    info: "border-ember-500/30 bg-ember-500/10 text-ember-200",
  }[tone];
  return <div className={cn("rounded-xl border px-3.5 py-2.5 text-sm", t, className)}>{children}</div>;
}
