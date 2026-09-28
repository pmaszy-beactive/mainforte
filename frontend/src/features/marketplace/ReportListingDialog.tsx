import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { Dialog } from "./Dialog";

export function ReportListingDialog({ listingId, open, onClose, onReported }: {
  listingId: string;
  open: boolean;
  onClose: () => void;
  onReported: () => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");

  const report = useMutation({
    mutationFn: () => api.marketplace.report(listingId, reason || undefined),
    onSuccess: () => {
      onReported();
      onClose();
      setReason("");
    },
  });

  return (
    <Dialog open={open} onClose={onClose} title={t("marketplace.report.title")}>
      <p className="text-sm text-fog-500">{t("marketplace.report.hint")}</p>
      <label className="mt-3 block space-y-1.5">
        <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.report.reason")}</span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder={t("marketplace.report.reasonPlaceholder")}
          className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-3.5 py-2.5 text-sm text-fog-100 placeholder:text-fog-700 focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20"
        />
      </label>
      {report.isError && <Alert className="mt-3">{errorMessage(report.error, t("common.error"))}</Alert>}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="danger" onClick={() => report.mutate()} loading={report.isPending}>
          {t("marketplace.report.submit")}
        </Button>
      </div>
    </Dialog>
  );
}
