import { useEffect } from "react";
import { create } from "zustand";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

interface LightboxState {
  src: string | null;
  name: string;
  open: (src: string, name: string) => void;
  close: () => void;
}

export const useLightbox = create<LightboxState>()((set) => ({
  src: null,
  name: "",
  open: (src, name) => set({ src, name }),
  close: () => set({ src: null, name: "" }),
}));

export function Lightbox() {
  const { t } = useTranslation();
  const src = useLightbox((s) => s.src);
  const name = useLightbox((s) => s.name);
  const close = useLightbox((s) => s.close);

  useEffect(() => {
    if (!src) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [src, close]);

  if (!src) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/90 p-6 backdrop-blur-sm animate-fade-up" onClick={close} role="dialog" aria-modal>
      <button onClick={close} className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-fog-100 hover:bg-white/20 ring-focus" aria-label={t("chat.closeLightbox")}>
        <X className="size-5" />
      </button>
      <figure className="max-h-full max-w-full" onClick={(e) => e.stopPropagation()}>
        <img src={src} alt={name} className="max-h-[85dvh] max-w-[90vw] rounded-2xl object-contain shadow-2xl ring-1 ring-white/10" />
        <figcaption className="mt-3 text-center text-xs text-fog-500">{name}</figcaption>
      </figure>
    </div>
  );
}
