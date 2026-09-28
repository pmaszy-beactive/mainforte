import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { ImageOff, MapPin } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { useFormat } from "@/hooks/useFormat";
import { useUi } from "@/stores/ui";
import { api } from "@/lib/api";
import type { MarketplaceListing } from "@/lib/types";

/** Grid card for the browse page and My Listings. Listing photos are stored under the seller's
 * workspace upload endpoint (`/api/workspaces/{ws}/uploads/{id}`), which is membership-gated —
 * in this v1 conceptual demo we best-effort render using the *viewer's* current workspace, and
 * fall back to a placeholder icon if that 403s/404s (cross-workspace photo viewing is a known v1
 * gap, not attempted to be solved here). */
export function ListingCard({ listing }: { listing: MarketplaceListing }) {
  const { t } = useTranslation();
  const f = useFormat();
  const wsId = useUi((s) => s.workspaceId);
  const photo = listing.photos[0];
  const photoUrl = photo && wsId ? api.workspaces.uploadUrl(wsId).replace(/\/uploads$/, `/uploads/${photo.upload_id}`) : null;

  return (
    <Link to={`/app/marketplace/${listing.id}`}>
      <Card className="flex h-full flex-col overflow-hidden transition hover:border-white/20">
        <div className="flex aspect-[4/3] items-center justify-center bg-ink-950/60 text-fog-700">
          {photoUrl ? (
            <img src={photoUrl} alt={listing.title} className="size-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
          ) : (
            <ImageOff className="size-6" />
          )}
        </div>
        <div className="flex flex-1 flex-col gap-1.5 p-3.5">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 text-sm font-semibold text-fog-100">{listing.title}</h3>
            <Badge tone={listing.kind === "service" ? "amber" : "neutral"}>
              {t(`marketplace.kind.${listing.kind}`)}
            </Badge>
          </div>
          <div className="text-lg font-semibold text-ember-300">{f.usd(listing.price_cents / 100)}</div>
          <div className="mt-auto flex items-center justify-between text-xs text-fog-700">
            <span className="truncate">{t(`marketplace.category.${listing.category}`)}</span>
            {listing.location_label && (
              <span className="flex shrink-0 items-center gap-1 truncate">
                <MapPin className="size-3" /> {listing.location_label}
              </span>
            )}
          </div>
          {typeof listing.distance_km === "number" && (
            <div className="text-xs text-fog-700">{t("marketplace.distanceAway", { km: listing.distance_km.toFixed(1) })}</div>
          )}
        </div>
      </Card>
    </Link>
  );
}
