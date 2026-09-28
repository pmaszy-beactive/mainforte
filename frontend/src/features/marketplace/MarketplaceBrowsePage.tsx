import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Search, ShoppingBag, Store } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ListingCategory, ListingKind, MarketplaceListing } from "@/lib/types";
import { ListingCard } from "./ListingCard";

const CATEGORIES: ListingCategory[] = [
  "general", "electronics", "furniture", "clothing", "kids_baby", "tools", "sports_outdoors",
  "books_media", "home_garden", "tickets_events", "services_lessons", "services_home",
  "services_other", "free",
];

export default function MarketplaceBrowsePage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<ListingKind | "">("");
  const [category, setCategory] = useState<ListingCategory | "">("");
  const [aiResults, setAiResults] = useState<MarketplaceListing[] | null>(null);

  const listings = useQuery({
    queryKey: ["marketplace", "listings", kind, category],
    queryFn: () => api.marketplace.listings({ kind: kind || undefined, category: category || undefined, limit: 60 }),
  });

  const search = useMutation({
    mutationFn: (q: string) => api.marketplace.search({ query: q, kind: kind || null, category: category || null }),
    onSuccess: (r) => setAiResults(r.listings),
  });

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) {
      setAiResults(null);
      return;
    }
    search.mutate(query.trim());
  };

  const results = aiResults ?? listings.data?.listings ?? [];
  const isLoading = aiResults === null && listings.isLoading;

  return (
    <div className="mx-auto w-full max-w-6xl p-6">
      <PageHeader
        title={t("marketplace.title")}
        subtitle={t("marketplace.subtitle")}
        action={
          <div className="flex gap-2">
            <Link to="/app/marketplace/mine">
              <Button size="sm" variant="outline">
                <Store className="size-4" /> {t("marketplace.myListings")}
              </Button>
            </Link>
            <Link to="/app/marketplace/orders">
              <Button size="sm" variant="outline">
                <ShoppingBag className="size-4" /> {t("marketplace.myOrders")}
              </Button>
            </Link>
            <Link to="/app/marketplace/new">
              <Button size="sm">
                <Plus className="size-4" /> {t("marketplace.newListing")}
              </Button>
            </Link>
          </div>
        }
      />

      <Alert tone="info" className="mb-4">{t("marketplace.disclaimer")}</Alert>

      <form onSubmit={onSearch} className="mb-4 flex flex-wrap items-end gap-2">
        <div className="min-w-[220px] flex-1">
          <Input
            placeholder={t("marketplace.searchPlaceholder")}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!e.target.value.trim()) setAiResults(null);
            }}
          />
        </div>
        <select
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as ListingKind | "");
            setAiResults(null);
          }}
          className="h-11 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm text-fog-100 ring-focus"
        >
          <option value="">{t("marketplace.filters.anyKind")}</option>
          <option value="good">{t("marketplace.kind.good")}</option>
          <option value="service">{t("marketplace.kind.service")}</option>
        </select>
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value as ListingCategory | "");
            setAiResults(null);
          }}
          className="h-11 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm text-fog-100 ring-focus"
        >
          <option value="">{t("marketplace.filters.anyCategory")}</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{t(`marketplace.category.${c}`)}</option>
          ))}
        </select>
        <Button type="submit" size="md" variant="outline" loading={search.isPending}>
          <Search className="size-4" /> {t("marketplace.search")}
        </Button>
      </form>

      {search.isError && <Alert className="mb-4">{errorMessage(search.error, t("common.error"))}</Alert>}
      {listings.isError && <Alert className="mb-4">{errorMessage(listings.error, t("common.error"))}</Alert>}

      {!isLoading && results.length === 0 && (
        <EmptyState icon={<Search className="size-5" />} title={t("marketplace.empty")} hint={t("marketplace.emptyHint")} />
      )}

      <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", isLoading && "opacity-50")}>
        {results.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
      </div>
    </div>
  );
}
