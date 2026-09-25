import { cn } from "@/lib/cn";

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 select-none", className)}>
      <span className="grid size-8 place-items-center rounded-lg bg-ink-800 border border-white/10 shadow-glow">
        <svg viewBox="0 0 64 64" className="size-5">
          <path
            d="M16 46V18l8 12 8-12 8 12 8-12v28"
            fill="none"
            stroke="currentColor"
            className="text-ember-500"
            strokeWidth="6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      {!compact && <span className="font-semibold tracking-tight text-fog-100">Mainforte</span>}
    </span>
  );
}
