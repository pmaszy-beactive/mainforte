import { useTranslation } from "react-i18next";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "@/lib/api";
import { AuthLayout } from "./AuthLayout";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { GoogleButton } from "./GoogleButton";
import { Divider } from "./Divider";
import { errorMessage, useLoginMutation } from "./useAuthActions";

export default function SignupPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const plan = params.get("plan");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm.length > 0 && confirm !== form.password;
  const m = useLoginMutation(api.auth.register);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    m.mutate(form);
  };

  return (
    <AuthLayout
      title={t("auth.signup.title")}
      subtitle={plan && ["good", "better", "best"].includes(plan) ? t("auth.signup.subtitlePlan", { plan: t(`pricing.tiers.${plan}.name`) }) : t("auth.signup.subtitle")}
      footer={
        <>
          {t("auth.signup.haveAccount")}{" "}
          <Link to="/login" className="text-ember-400 hover:underline">
            {t("auth.login.title")}
          </Link>
        </>
      }
    >
      <GoogleButton label={t("auth.googleSignup")} />
      <Divider />
      <form onSubmit={submit} className="space-y-4">
        <Input label={t("auth.fields.name")} name="name" autoComplete="name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input label={t("auth.fields.email")} name="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Input label={t("auth.fields.password")} name="password" type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <Input
          label={t("auth.fields.confirm")}
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          hint={mismatch ? t("auth.reset.mismatch") : undefined}
        />
        {m.isError && <Alert>{errorMessage(m.error, t("common.error"))}</Alert>}
        <Button type="submit" className="w-full" loading={m.isPending} disabled={mismatch}>
          {t("auth.signup.submit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
