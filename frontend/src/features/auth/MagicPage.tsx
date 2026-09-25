import { useTranslation } from "react-i18next";
import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "@/lib/api";
import { AuthLayout } from "./AuthLayout";
import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import { errorMessage, useLoginMutation } from "./useAuthActions";

/** /magic?token=… — verifies the magic-link token and signs the user in. */
export default function MagicPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token");
  const m = useLoginMutation(api.auth.magicVerify);
  const { mutate } = m;
  const fired = useRef(false);

  useEffect(() => {
    if (token && !fired.current) {
      fired.current = true;
      mutate(token);
    }
  }, [token, mutate]);

  return (
    <AuthLayout title={t("auth.magic.title")} footer={<Link to="/login" className="text-ember-400 hover:underline">{t("auth.backToLogin")}</Link>}>
      {!token ? (
        <Alert>{t("auth.magic.missingToken")}</Alert>
      ) : m.isError ? (
        <Alert>{errorMessage(m.error, t("common.error"))}</Alert>
      ) : (
        <div className="flex items-center gap-3 text-sm text-fog-300">
          <Spinner /> {t("auth.magic.verifying")}
        </div>
      )}
    </AuthLayout>
  );
}
