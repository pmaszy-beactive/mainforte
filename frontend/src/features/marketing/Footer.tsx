import { useTranslation } from "react-i18next";
import { Logo } from "@/components/ui/Logo";

export function Footer() {
  const { t } = useTranslation();
  return (
    <footer className="border-t border-white/5">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-xs text-fog-700">
        <Logo compact />
        <span>{t("footer.copy", { year: new Date().getFullYear() })}</span>
      </div>
    </footer>
  );
}
