import { cn } from "@/lib/cn";

const tones = {
  neutral: "bg-white/5 text-fog-300 border-white/10",
  amber: "bg-ember-500/15 text-ember-300 border-ember-500/30",
  green: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  red: "bg-red-500/15 text-red-300 border-red-500/30",
};

export function Badge({ tone = "neutral", children, className }: { tone?: keyof typeof tones; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none", tones[tone], className)}>
      {children}
    </span>
  );
}
