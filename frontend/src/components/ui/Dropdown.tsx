import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * A native <select>'s popup is rendered by the browser/OS, not the page -- the app can't control
 * where it opens, so in a narrow container it can render on top of unrelated UI (T02799: the rail
 * logo). This renders the trigger and option list entirely in-page instead, anchored below the
 * trigger's own left edge so it only ever grows right/down into open space.
 */
export function Dropdown<T extends string>({
  value,
  options,
  onChange,
  trigger,
  renderOption,
  label,
  disabled,
}: {
  value: T;
  options: readonly T[];
  onChange: (v: T) => void;
  trigger: ReactNode;
  renderOption: (v: T) => ReactNode;
  label?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="rounded-lg py-1.5 pl-7 pr-1.5 text-xs text-fog-300 ring-focus hover:bg-white/5 hover:text-fog-100 disabled:opacity-50"
      >
        {trigger}
      </button>
      {open && (
        <div
          role="listbox"
          className="glass absolute left-0 top-full z-20 mt-1.5 min-w-full overflow-hidden rounded-xl p-1 animate-fade-up"
        >
          {options.map((o) => (
            <button
              key={o}
              type="button"
              role="option"
              aria-selected={o === value}
              onClick={() => {
                onChange(o);
                setOpen(false);
              }}
              className={
                "block w-full whitespace-nowrap rounded-lg px-2.5 py-1.5 text-left text-xs transition " +
                (o === value ? "bg-ember-500/10 text-ember-300" : "text-fog-300 hover:bg-white/5 hover:text-fog-100")
              }
            >
              {renderOption(o)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
