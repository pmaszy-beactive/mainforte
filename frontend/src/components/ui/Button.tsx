import type { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-ember-500 text-ink-950 hover:bg-ember-400 shadow-glow font-semibold",
  ghost: "text-fog-300 hover:text-fog-100 hover:bg-white/5",
  outline: "border border-white/10 text-fog-100 hover:bg-white/5 hover:border-white/20",
  danger: "bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...rest }: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-xl transition-all duration-150 ring-focus disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}
