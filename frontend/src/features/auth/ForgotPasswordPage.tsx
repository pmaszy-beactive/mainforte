import { useTranslation } from "react-i18next";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuthLayout } from "./AuthLayout";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { errorMessage } from "./useAuthActions";

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const m = useMutation({ mutationFn: api.auth.forgotPassword });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate(email);
  };
  return (
    <AuthLayout
      title={t("auth.forgot.title")}
      subtitle={t("auth.forgot.subtitle")}
      footer={
        <Link to="/login" className="text-ember-400 hover:underline">
          {t("auth.backToLogin")}
        </Link>
      }
    >
      {m.isSuccess ? (
        <Alert tone="success">{t("auth.forgot.sent", { email })}</Alert>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Input label={t("auth.fields.email")} name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          {m.isError && <Alert>{errorMessage(m.error, t("common.error"))}</Alert>}
          <Button type="submit" className="w-full" loading={m.isPending}>
            {t("auth.forgot.submit")}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
