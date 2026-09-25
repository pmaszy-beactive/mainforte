import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Logo } from "@/components/ui/Logo";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/stores/auth";

export function Nav() {
  const { t } = useTranslation();
  const token = useAuth((s) => s.token);
  return (
    <header className="sticky top-0 z-20 border-b border-white/5 bg-ink-900/70 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Link to="/" aria-label={t("common.home")}>
          <Logo />
        </Link>
        <nav className="flex items-center gap-2">
          <a href="#benefits" className="hidden px-3 text-sm text-fog-300 hover:text-fog-100 sm:inline">
            {t("nav.why")}
          </a>
          <a href="#pricing" className="hidden px-3 text-sm text-fog-300 hover:text-fog-100 sm:inline">
            {t("nav.pricing")}
          </a>
          {token ? (
            <Link to="/app">
              <Button size="sm">{t("nav.openApp")}</Button>
            </Link>
          ) : (
            <>
              <Link to="/login">
                <Button size="sm" variant="ghost">
                  {t("nav.login")}
                </Button>
              </Link>
              <Link to="/signup">
                <Button size="sm">{t("nav.getStarted")}</Button>
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
