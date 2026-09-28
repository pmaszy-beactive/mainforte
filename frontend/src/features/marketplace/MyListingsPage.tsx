import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Store } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { useFormat } from "@/hooks/useFormat";

const STATUS_TONE: Record<string, "neutral" | "amber" | "green" | "red"> = {
  draft: "neutral", active: "green", sold: "amber", removed: "red",
};

export default function MyListingsPage() {
  const { t } = useTranslation();
  const f = useFormat();
  const qc = useQueryClient();

  const mine = useQuery({ queryKey: ["marketplace", "mine"], queryFn: () => api.marketplace.mine() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["marketplace", "mine"] });
  const publish = useMutation({ mutationFn: (id: string) => api.marketplace.publish(id), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => api.marketplace.remove(id), onSuccess: invalidate });

  const listings = mine.data?.listings ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <PageHeader
        title={t("marketplace.myListings")}
        action={
          <Link to="/app/marketplace/new">
            <Button size="sm"><Plus className="size-4" /> {t("marketplace.newListing")}</Button>
          </Link>
        }
      />

      {mine.isError && <Alert className="mb-4">{errorMessage(mine.error, t("common.error"))}</Alert>}
      {(publish.isError || remove.isError) && (
        <Alert className="mb-4">{errorMessage(publish.error ?? remove.error, t("common.error"))}</Alert>
      )}

      {!mine.isLoading && listings.length === 0 && (
        <EmptyState icon={<Store className="size-5" />} title={t("marketplace.myListingsEmpty")} />
      )}

      <div className="space-y-3">
        {listings.map((l) => (
          <Card key={l.id} className="flex items-center justify-between gap-3 p-4">
            <div className="min-w-0 flex-1">
              <Link to={`/app/marketplace/${l.id}`} className="truncate text-sm font-medium text-fog-100 hover:underline">
                {l.title}
              </Link>
              <div className="mt-1 flex items-center gap-2 text-xs text-fog-500">
                <Badge tone={STATUS_TONE[l.status]}>{t(`marketplace.status.${l.status}`)}</Badge>
                <span>{f.usd(l.price_cents / 100)}</span>
                {l.flagged && <Badge tone="red">{t("marketplace.flagged")}</Badge>}
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {l.status === "draft" && (
                <Button size="sm" variant="outline" loading={publish.isPending} onClick={() => publish.mutate(l.id)}>
                  {t("marketplace.form.publish")}
                </Button>
              )}
              {l.status === "draft" && (
                <Link to={`/app/marketplace/${l.id}/edit`}>
                  <Button size="sm" variant="ghost">{t("marketplace.edit")}</Button>
                </Link>
              )}
              {l.status === "active" && (
                <Button size="sm" variant="ghost" loading={remove.isPending} onClick={() => remove.mutate(l.id)}>
                  {t("marketplace.remove")}
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
