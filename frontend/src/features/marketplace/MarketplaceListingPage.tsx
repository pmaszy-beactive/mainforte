import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Flag, ImageOff, MapPin, ShoppingBag } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { useFormat } from "@/hooks/useFormat";
import { useAuth } from "@/stores/auth";
import { useUi } from "@/stores/ui";
import { BuyDialog } from "./BuyDialog";
import { ReportListingDialog } from "./ReportListingDialog";

export default function MarketplaceListingPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { id = "" } = useParams();
  const user = useAuth((s) => s.user);
  const wsId = useUi((s) => s.workspaceId);
  const [buyOpen, setBuyOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [placedNotice, setPlacedNotice] = useState(false);
  const [reportedNotice, setReportedNotice] = useState(false);

  const listing = useQuery({
    queryKey: ["marketplace", "listing", id],
    queryFn: () => api.marketplace.get(id),
    enabled: !!id,
  });

  if (listing.isLoading) return null;
  if (listing.isError || !listing.data) {
    return (
      <div className="mx-auto w-full max-w-3xl p-6">
        <Alert>{errorMessage(listing.error, t("marketplace.notFound"))}</Alert>
      </div>
    );
  }

  const l = listing.data;
  const isOwner = user?.id === l.seller_user_id;
  const canBuy = l.status === "active" && !isOwner;
  const photoUrl = l.photos[0] && wsId
    ? api.workspaces.uploadUrl(wsId).replace(/\/uploads$/, `/uploads/${l.photos[0].upload_id}`)
    : null;

  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader
        title={l.title}
        subtitle={t(`marketplace.category.${l.category}`)}
        action={
          !isOwner && (
            <Button size="sm" variant="ghost" onClick={() => setReportOpen(true)}>
              <Flag className="size-3.5" /> {t("marketplace.report.action")}
            </Button>
          )
        }
      />

      {placedNotice && <Alert tone="success" className="mb-4">{t("marketplace.buy.placed")}</Alert>}
      {reportedNotice && <Alert tone="success" className="mb-4">{t("marketplace.report.done")}</Alert>}

      <Card className="overflow-hidden">
        <div className="flex aspect-video items-center justify-center bg-ink-950/60 text-fog-700">
          {photoUrl ? (
            <img src={photoUrl} alt={l.title} className="size-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
          ) : (
            <ImageOff className="size-8" />
          )}
        </div>
        <div className="p-5">
          <div className="flex items-center gap-2">
            <Badge tone={l.kind === "service" ? "amber" : "neutral"}>{t(`marketplace.kind.${l.kind}`)}</Badge>
            {l.condition && <Badge>{t(`marketplace.condition.${l.condition}`)}</Badge>}
            <Badge tone={l.status === "active" ? "green" : l.status === "sold" ? "red" : "neutral"}>
              {t(`marketplace.status.${l.status}`)}
            </Badge>
          </div>
          <div className="mt-3 text-2xl font-semibold text-ember-300">{f.usd(l.price_cents / 100)}</div>
          {l.location_label && (
            <div className="mt-1 flex items-center gap-1 text-sm text-fog-500">
              <MapPin className="size-3.5" /> {l.location_label}
            </div>
          )}
          <p className="mt-4 whitespace-pre-wrap text-sm text-fog-300">{l.description || t("marketplace.noDescription")}</p>

          {canBuy && (
            <Button className="mt-5" onClick={() => setBuyOpen(true)}>
              <ShoppingBag className="size-4" /> {t("marketplace.buy.action")}
            </Button>
          )}
          {isOwner && (
            <p className="mt-5 text-xs text-fog-700">{t("marketplace.ownListingHint")}</p>
          )}
          {l.status === "sold" && !isOwner && (
            <p className="mt-5 text-xs text-fog-700">{t("marketplace.soldHint")}</p>
          )}
        </div>
      </Card>

      <BuyDialog
        listing={l}
        open={buyOpen}
        onClose={() => setBuyOpen(false)}
        onPlaced={() => {
          setPlacedNotice(true);
          qc.invalidateQueries({ queryKey: ["marketplace", "listing", id] });
          setTimeout(() => nav("/app/marketplace/orders"), 900);
        }}
      />
      <ReportListingDialog
        listingId={id}
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        onReported={() => setReportedNotice(true)}
      />
    </div>
  );
}
