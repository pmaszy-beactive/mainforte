import { useTranslation } from "react-i18next";
export function Divider({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wider text-fog-700">
      <span className="h-px flex-1 bg-white/10" />
      {label ?? t("auth.or")}
      <span className="h-px flex-1 bg-white/10" />
    </div>
  );
}
