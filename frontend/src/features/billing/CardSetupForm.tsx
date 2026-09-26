import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";

/** Mounted inside an <Elements> provider scoped to one SetupIntent client_secret. */
export function CardSetupForm({ onSaved }: { onSaved: (setupIntentId: string) => void }) {
  const { t } = useTranslation();
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError(null);
    const { error: confirmError, setupIntent } = await stripe.confirmSetup({
      elements,
      redirect: "if_required",
    });
    setSubmitting(false);
    if (confirmError) {
      setError(confirmError.message ?? t("common.error"));
      return;
    }
    if (setupIntent?.status === "succeeded") onSaved(setupIntent.id);
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <PaymentElement />
      {error && <Alert>{error}</Alert>}
      <Button type="submit" size="sm" className="w-full" loading={submitting} disabled={!stripe || !elements}>
        {submitting ? t("billing.card.saving") : t("billing.card.save")}
      </Button>
    </form>
  );
}
