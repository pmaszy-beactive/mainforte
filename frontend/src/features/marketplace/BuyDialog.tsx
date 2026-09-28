import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { Banknote, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useFormat } from "@/hooks/useFormat";
import type { MarketplaceListing, MarketplaceOrder, MarketplacePaymentMethod } from "@/lib/types";
import { Dialog } from "./Dialog";

export function BuyDialog({ listing, open, onClose, onPlaced }: {
  listing: MarketplaceListing;
  open: boolean;
  onClose: () => void;
  onPlaced: (order: MarketplaceOrder) => void;
}) {
  const { t } = useTranslation();
  const f = useFormat();
  const [method, setMethod] = useState<MarketplacePaymentMethod>("cash");
  const [notes, setNotes] = useState("");

  const placeOrder = useMutation({
    mutationFn: () => api.marketplace.placeOrder(listing.id, { payment_method: method, notes: notes || undefined }),
    onSuccess: (order) => {
      onPlaced(order);
      onClose();
    },
  });

  const optionCls = (active: boolean) =>
    cn(
      "flex flex-1 flex-col items-start gap-1 rounded-xl border p-3.5 text-left transition ring-focus",
      active ? "border-ember-500/50 bg-ember-500/10" : "border-white/10 hover:border-white/20",
    );

  return (
    <Dialog open={open} onClose={onClose} title={t("marketplace.buy.title")}>
      <div className="mb-4">
        <div className="text-sm font-medium text-fog-100">{listing.title}</div>
        <div className="text-lg font-semibold text-ember-300">{f.usd(listing.price_cents / 100)}</div>
      </div>

      <div className="flex gap-2">
        <button type="button" className={optionCls(method === "cash")} onClick={() => setMethod("cash")}>
          <Banknote className="size-4 text-fog-300" />
          <span className="text-sm font-medium">{t("marketplace.payment.cash")}</span>
          <span className="text-xs text-fog-700">{t("marketplace.payment.cashHint")}</span>
        </button>
        <button type="button" className={optionCls(method === "stripe_escrow")} onClick={() => setMethod("stripe_escrow")}>
          <ShieldCheck className="size-4 text-fog-300" />
          <span className="text-sm font-medium">{t("marketplace.payment.escrow")}</span>
          <span className="text-xs text-fog-700">{t("marketplace.payment.escrowHint")}</span>
        </button>
      </div>

      {method === "stripe_escrow" && (
        <Alert tone="info" className="mt-3">{t("marketplace.payment.escrowStubNotice")}</Alert>
      )}

      <label className="mt-4 block space-y-1.5">
        <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.buy.notes")}</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder={t("marketplace.buy.notesPlaceholder")}
          className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-3.5 py-2.5 text-sm text-fog-100 placeholder:text-fog-700 focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20"
        />
      </label>

      {placeOrder.isError && <Alert className="mt-3">{errorMessage(placeOrder.error, t("common.error"))}</Alert>}

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button onClick={() => placeOrder.mutate()} loading={placeOrder.isPending}>
          {t("marketplace.buy.confirm")}
        </Button>
      </div>
    </Dialog>
  );
}
