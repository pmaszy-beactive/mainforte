import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ImagePlus, Loader2, X } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { uploadXhr } from "@/lib/upload";
import { useUi } from "@/stores/ui";
import type { ListingCategory, ListingCondition, ListingKind, MarketplaceListingIn } from "@/lib/types";

const CATEGORIES: ListingCategory[] = [
  "general", "electronics", "furniture", "clothing", "kids_baby", "tools", "sports_outdoors",
  "books_media", "home_garden", "tickets_events", "services_lessons", "services_home",
  "services_other", "free",
];
const CONDITIONS: ListingCondition[] = ["new", "like_new", "good", "fair", "worn"];

interface PendingPhoto {
  localId: string;
  uploadId?: string;
  progress: number;
  error?: string;
}

export default function MarketplaceNewListingPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { id } = useParams();
  const isEdit = !!id;
  const wsId = useUi((s) => s.workspaceId);
  const fileRef = useRef<HTMLInputElement>(null);

  const existing = useQuery({
    queryKey: ["marketplace", "listing", id],
    queryFn: () => api.marketplace.get(id!),
    enabled: isEdit,
  });

  const [kind, setKind] = useState<ListingKind>("good");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<ListingCategory>("general");
  const [condition, setCondition] = useState<ListingCondition | "">("");
  const [price, setPrice] = useState("");
  const [locationLabel, setLocationLabel] = useState("");
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);

  useEffect(() => {
    const l = existing.data;
    if (!l) return;
    setKind(l.kind);
    setTitle(l.title);
    setDescription(l.description);
    setCategory(l.category);
    setCondition(l.condition ?? "");
    setPrice(String(l.price_cents / 100));
    setLocationLabel(l.location_label ?? "");
    setPhotos(l.photos.map((p) => ({ localId: p.id, uploadId: p.upload_id, progress: 1 })));
  }, [existing.data]);

  const save = useMutation({
    mutationFn: async () => {
      const priceCents = Math.round(parseFloat(price || "0") * 100);
      const body: MarketplaceListingIn = {
        kind, title: title.trim(), description: description.trim(), category,
        condition: condition || null, price_cents: priceCents,
        location_label: locationLabel.trim() || null, ws_id: wsId,
      };
      const uploadIds = photos.filter((p) => p.uploadId).map((p) => p.uploadId!);
      if (isEdit) {
        return api.marketplace.update(id!, { ...body, photo_upload_ids: uploadIds });
      }
      const listing = await api.marketplace.create(body);
      if (uploadIds.length) {
        return api.marketplace.update(listing.id, { photo_upload_ids: uploadIds });
      }
      return listing;
    },
    onSuccess: (listing) => nav(`/app/marketplace/${listing.id}`),
  });

  const publish = useMutation({
    mutationFn: async () => {
      const saved = await save.mutateAsync();
      return api.marketplace.publish(saved.id);
    },
    onSuccess: (listing) => nav(`/app/marketplace/${listing.id}`),
  });

  const onFiles = (files: FileList | null) => {
    if (!files || !wsId) return;
    Array.from(files).forEach((file) => {
      const localId = `${Date.now()}-${file.name}`;
      setPhotos((p) => [...p, { localId, progress: 0 }]);
      uploadXhr(wsId, file, (fraction) => {
        setPhotos((p) => p.map((ph) => (ph.localId === localId ? { ...ph, progress: fraction } : ph)));
      }, () => {}).then((result) => {
        setPhotos((p) => p.map((ph) => (ph.localId === localId ? { ...ph, uploadId: result.id, progress: 1 } : ph)));
      }).catch((err) => {
        setPhotos((p) => p.map((ph) => (ph.localId === localId ? { ...ph, error: errorMessage(err) } : ph)));
      });
    });
  };

  const removePhoto = (localId: string) => setPhotos((p) => p.filter((ph) => ph.localId !== localId));

  const canSubmit = title.trim().length > 0 && price.trim().length > 0 && !!wsId;

  if (!wsId) {
    return (
      <div className="mx-auto w-full max-w-2xl p-6">
        <PageHeader title={t("marketplace.newListing")} />
        <EmptyState title={t("chat.noWorkspace")} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl p-6">
      <PageHeader title={isEdit ? t("marketplace.form.editTitle") : t("marketplace.form.newTitle")} subtitle={t("marketplace.disclaimer")} />

      <Card className="space-y-4 p-5">
        <div className="flex gap-2">
          {(["good", "service"] as ListingKind[]).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={`flex-1 rounded-xl border px-3 py-2 text-sm transition ring-focus ${kind === k ? "border-ember-500/50 bg-ember-500/10 text-ember-300" : "border-white/10 text-fog-300 hover:border-white/20"}`}
            >
              {t(`marketplace.kind.${k}`)}
            </button>
          ))}
        </div>

        <Input label={t("marketplace.form.titleLabel")} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />

        <label className="block space-y-1.5">
          <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.form.descriptionLabel")}</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-3.5 py-2.5 text-sm text-fog-100 placeholder:text-fog-700 focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.form.categoryLabel")}</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as ListingCategory)}
              className="h-11 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm text-fog-100 ring-focus"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{t(`marketplace.category.${c}`)}</option>
              ))}
            </select>
          </label>
          {kind === "good" && (
            <label className="block space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.form.conditionLabel")}</span>
              <select
                value={condition}
                onChange={(e) => setCondition(e.target.value as ListingCondition | "")}
                className="h-11 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm text-fog-100 ring-focus"
              >
                <option value="">{t("marketplace.filters.anyCondition")}</option>
                {CONDITIONS.map((c) => (
                  <option key={c} value={c}>{t(`marketplace.condition.${c}`)}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Input
            label={t("marketplace.form.priceLabel")}
            type="number"
            min={0}
            step="0.01"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
          <Input
            label={t("marketplace.form.locationLabel")}
            value={locationLabel}
            onChange={(e) => setLocationLabel(e.target.value)}
            placeholder={t("marketplace.form.locationPlaceholder")}
          />
        </div>

        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-fog-500">{t("marketplace.form.photosLabel")}</span>
          <div className="flex flex-wrap gap-2">
            {photos.map((p) => (
              <div key={p.localId} className="relative size-20 overflow-hidden rounded-lg border border-white/10 bg-ink-950/60">
                {p.progress < 1 && !p.error && (
                  <div className="flex size-full items-center justify-center"><Loader2 className="size-4 animate-spin text-fog-500" /></div>
                )}
                {p.error && <div className="flex size-full items-center justify-center p-1 text-center text-[10px] text-red-300">{p.error}</div>}
                {p.uploadId && p.progress >= 1 && (
                  <img
                    src={api.workspaces.uploadUrl(wsId).replace(/\/uploads$/, `/uploads/${p.uploadId}`)}
                    alt=""
                    className="size-full object-cover"
                  />
                )}
                <button
                  type="button"
                  onClick={() => removePhoto(p.localId)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-ink-950/80 p-0.5 text-fog-300 hover:text-fog-100"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex size-20 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-white/15 text-fog-700 hover:border-white/30 hover:text-fog-300 ring-focus"
            >
              <ImagePlus className="size-4" />
              <span className="text-[10px]">{t("marketplace.form.addPhoto")}</span>
            </button>
          </div>
          <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
        </div>

        {(save.isError || publish.isError) && (
          <Alert>{errorMessage(save.error ?? publish.error, t("common.error"))}</Alert>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" disabled={!canSubmit} loading={save.isPending} onClick={() => save.mutate()}>
            {t("marketplace.form.saveDraft")}
          </Button>
          <Button disabled={!canSubmit} loading={publish.isPending} onClick={() => publish.mutate()}>
            {t("marketplace.form.publish")}
          </Button>
        </div>
      </Card>
    </div>
  );
}
