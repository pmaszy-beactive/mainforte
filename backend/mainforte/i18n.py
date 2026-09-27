"""Server-side i18n: locale normalization + the few strings the backend itself renders (emails)."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SUPPORTED = ("en-US", "fr-CA")
DEFAULT = "en-US"


def normalize_locale(raw: str | None) -> str:
    if not raw:
        return DEFAULT
    r = raw.strip().replace("_", "-")
    if r in SUPPORTED:
        return r
    return "fr-CA" if r.lower().startswith("fr") else DEFAULT


def valid_timezone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def email_layout(*, preheader: str, heading: str, body_html: str, cta_label: str, cta_url: str, footer: str) -> str:
    """Minimal inline-CSS branded wrapper shared by transactional emails (task #39). Inline styles
    only, table-free single-column layout, no external assets/fonts/JS -- matches what mainstream
    email clients (Gmail, Outlook) reliably render without stripping. `preheader` is a hidden
    snippet email clients show next to the subject in the inbox list.
    """
    return (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>'
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:480px;margin:0 auto;padding:32px 24px;color:#1a1a1a;">'
        '<div style="font-size:20px;font-weight:700;color:#2563eb;margin-bottom:24px;">Mainforte</div>'
        f'<h1 style="font-size:20px;margin:0 0 16px;">{heading}</h1>'
        f'<div style="font-size:15px;line-height:1.5;margin-bottom:24px;">{body_html}</div>'
        f'<a href="{cta_url}" style="display:inline-block;background:#2563eb;color:#fff;'
        "text-decoration:none;padding:12px 24px;border-radius:6px;font-size:15px;font-weight:600;"
        f'">{cta_label}</a>'
        '<p style="font-size:13px;color:#6b7280;margin-top:32px;">'
        f"{footer}</p>"
        "</div>"
    )


STRINGS: dict[str, dict[str, str]] = {
    "en-US": {
        "magic.subject": "Your Mainforte sign-in link",
        "magic.html": "<p>Click to sign in: <a href=\"{url}\">{url}</a></p><p>This link expires in 15 minutes.</p>",
        "magic.text": "Sign in: {url} (expires in 15 minutes)",
        "reset.subject": "Reset your Mainforte password",
        "reset.html": email_layout(
            preheader="Reset your Mainforte password. This link expires in 1 hour.",
            heading="Reset your password",
            body_html="We received a request to reset your Mainforte password. Click the button "
                       "below to choose a new one.",
            cta_label="Reset password",
            cta_url="{url}",
            footer="This link expires in 1 hour. If you didn't request a password reset, you can "
                   "safely ignore this email.",
        ),
        "reset.text": "Reset your password: {url} (expires in 1 hour)",
    },
    "fr-CA": {
        "magic.subject": "Votre lien de connexion Mainforte",
        "magic.html": "<p>Cliquez pour vous connecter : <a href=\"{url}\">{url}</a></p><p>Ce lien expire dans 15 minutes.</p>",
        "magic.text": "Connexion : {url} (expire dans 15 minutes)",
        "reset.subject": "Réinitialisez votre mot de passe Mainforte",
        "reset.html": email_layout(
            preheader="Réinitialisez votre mot de passe Mainforte. Ce lien expire dans 1 heure.",
            heading="Réinitialisez votre mot de passe",
            body_html="Nous avons reçu une demande de réinitialisation de votre mot de passe "
                      "Mainforte. Cliquez sur le bouton ci-dessous pour en choisir un nouveau.",
            cta_label="Réinitialiser le mot de passe",
            cta_url="{url}",
            footer="Ce lien expire dans 1 heure. Si vous n'avez pas demandé cette "
                   "réinitialisation, vous pouvez ignorer cet e-mail en toute sécurité.",
        ),
        "reset.text": "Réinitialisez votre mot de passe : {url} (expire dans 1 heure)",
    },
}


def t(locale: str | None, key: str, **kw: str) -> str:
    table = STRINGS.get(normalize_locale(locale), STRINGS[DEFAULT])
    return table.get(key, STRINGS[DEFAULT].get(key, key)).format(**kw)
