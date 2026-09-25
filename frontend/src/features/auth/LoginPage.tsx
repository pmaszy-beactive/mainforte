import { useTranslation } from "react-i18next";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuthLayout } from "./AuthLayout";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { GoogleButton } from "./GoogleButton";
import { Divider } from "./Divider";
import { errorMessage, useLoginMutation } from "./useAuthActions";

export default function LoginPage() {
  const { t } = useTranslation();
  const [form, setForm] = useState({ email: "", password: "" });
  const login = useLoginMutation(api.auth.login);
  const magic = useMutation({ mutationFn: api.auth.magicLink });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate(form);
  };

  return (
    <AuthLayout
      title={t("auth.login.welcome")}
      subtitle={t("auth.login.subtitle")}
      footer={
        <>
          {t("auth.login.newHere")}{" "}
          <Link to="/signup" className="text-ember-400 hover:underline">
            {t("auth.login.createAccount")}
          </Link>
        </>
      }
    >
      <GoogleButton />
      <Divider />
      <form onSubmit={submit} className="space-y-4">
        <Input label={t("auth.fields.email")} name="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Input label={t("auth.fields.password")} name="password" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        {login.isError && <Alert>{errorMessage(login.error, t("common.error"))}</Alert>}
        {magic.isSuccess && <Alert tone="success">{t("auth.login.magicSent")}</Alert>}
        {magic.isError && <Alert>{errorMessage(magic.error, t("common.error"))}</Alert>}
        <Button type="submit" className="w-full" loading={login.isPending}>
          {t("auth.login.submit")}
        </Button>
        <div className="flex justify-between text-xs text-fog-500">
          <button type="button" className="hover:text-fog-100 disabled:opacity-50" disabled={!form.email || magic.isPending} onClick={() => magic.mutate(form.email)}>
            {t("auth.login.magic")}
          </button>
          <Link to="/forgot-password" className="hover:text-fog-100">
            {t("auth.login.forgot")}
          </Link>
        </div>
      </form>
    </AuthLayout>
  );
}
