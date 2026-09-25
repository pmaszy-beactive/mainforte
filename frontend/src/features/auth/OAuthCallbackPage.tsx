import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/stores/auth";
import { AuthLayout } from "./AuthLayout";
import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";

/** /oauth/callback#token=… — the backend lands here after Google OAuth. */
export default function OAuthCallbackPage() {
  const { t } = useTranslation();
  const setSession = useAuth((s) => s.setSession);
  const qc = useQueryClient();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const frag = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = frag.get("token");
    const err = frag.get("error");
    if (token) {
      setSession(token, null);
      qc.clear();
      history.replaceState(null, "", window.location.pathname); // drop the token from the URL
      nav("/app", { replace: true });
    } else {
      setError(err ?? t("auth.oauth.noToken"));
    }
  }, [setSession, qc, nav, t]);

  return (
    <AuthLayout title={t("auth.oauth.title")} footer={<Link to="/login" className="text-ember-400 hover:underline">{t("auth.backToLogin")}</Link>}>
      {error ? (
        <Alert>{error}</Alert>
      ) : (
        <div className="flex items-center gap-3 text-sm text-fog-300">
          <Spinner /> {t("auth.oauth.wait")}
        </div>
      )}
    </AuthLayout>
  );
}
