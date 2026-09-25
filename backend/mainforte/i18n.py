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


STRINGS: dict[str, dict[str, str]] = {
    "en-US": {
        "magic.subject": "Your Mainforte sign-in link",
        "magic.html": "<p>Click to sign in: <a href=\"{url}\">{url}</a></p><p>This link expires in 15 minutes.</p>",
        "magic.text": "Sign in: {url} (expires in 15 minutes)",
        "reset.subject": "Reset your Mainforte password",
        "reset.html": "<p>Reset your password: <a href=\"{url}\">{url}</a></p><p>This link expires in 1 hour.</p>",
        "reset.text": "Reset your password: {url} (expires in 1 hour)",
    },
    "fr-CA": {
        "magic.subject": "Votre lien de connexion Mainforte",
        "magic.html": "<p>Cliquez pour vous connecter : <a href=\"{url}\">{url}</a></p><p>Ce lien expire dans 15 minutes.</p>",
        "magic.text": "Connexion : {url} (expire dans 15 minutes)",
        "reset.subject": "Réinitialisez votre mot de passe Mainforte",
        "reset.html": "<p>Réinitialisez votre mot de passe : <a href=\"{url}\">{url}</a></p><p>Ce lien expire dans 1 heure.</p>",
        "reset.text": "Réinitialisez votre mot de passe : {url} (expire dans 1 heure)",
    },
}


def t(locale: str | None, key: str, **kw: str) -> str:
    table = STRINGS.get(normalize_locale(locale), STRINGS[DEFAULT])
    return table.get(key, STRINGS[DEFAULT].get(key, key)).format(**kw)
