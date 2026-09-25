import { useTranslation } from "react-i18next";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuthLayout } from "./AuthLayout";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { errorMessage } from "./useAuthActions";

export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const m = useMutation({ mutationFn: api.auth.resetPassword });
  const mismatch = confirm.length > 0 && confirm !== password;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    m.mutate({ token, password });
  };

  return (
    <AuthLayout title={t("auth.reset.title")} footer={<Link to="/login" className="text-ember-400 hover:underline">{t("auth.backToLogin")}</Link>}>
      {!token ? (
        <Alert>{t("auth.reset.missingToken")}</Alert>
      ) : m.isSuccess ? (
        <div className="space-y-4">
          <Alert tone="success">{t("auth.reset.done")}</Alert>
          <Link to="/login">
            <Button className="w-full">{t("auth.login.submit")}</Button>
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Input label={t("auth.fields.newPassword")} name="password" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input label={t("auth.fields.confirm")} name="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} hint={mismatch ? t("auth.reset.mismatch") : undefined} />
          {m.isError && <Alert>{errorMessage(m.error, t("common.error"))}</Alert>}
          <Button type="submit" className="w-full" loading={m.isPending} disabled={mismatch}>
            {t("auth.reset.submit")}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
