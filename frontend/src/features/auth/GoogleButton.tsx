import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";

export function GoogleButton({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <Button
      type="button"
      variant="outline"
      className="w-full"
      onClick={() => {
        window.location.href = api.auth.googleStartUrl();
      }}
    >
      <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
        <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.6 3.8-5.5 3.8-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.9 1.5l2.6-2.6C16.9 3.1 14.7 2 12 2 6.5 2 2 6.5 2 12s4.5 10 10 10c5.8 0 9.6-4.1 9.6-9.8 0-.7-.1-1.2-.2-1.7H12z" />
      </svg>
      {label ?? t("auth.google")}
    </Button>
  );
}
