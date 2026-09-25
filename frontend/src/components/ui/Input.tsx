import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
}

export function Input({ label, hint, className, id, ...rest }: Props) {
  const inputId = id ?? rest.name;
  return (
    <label className="block space-y-1.5" htmlFor={inputId}>
      {label && <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{label}</span>}
      <input
        id={inputId}
        className={cn(
          "w-full h-11 rounded-xl bg-ink-950/60 border border-white/10 px-3.5 text-sm text-fog-100 placeholder:text-fog-700",
          "focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20 transition",
          className,
        )}
        {...rest}
      />
      {hint && <span className="text-xs text-fog-700">{hint}</span>}
    </label>
  );
}
