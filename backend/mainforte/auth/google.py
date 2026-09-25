"""Google OIDC login. Incremental consent for Gmail/Calendar scopes comes later (same identity row)."""
from __future__ import annotations

from authlib.integrations.httpx_client import OAuth2Client

from mainforte.config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
BASE_SCOPES = "openid email profile"


def enabled() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def redirect_uri() -> str:
    return f"{get_settings().api_url}/api/auth/google/callback"


def client(scope: str = BASE_SCOPES) -> OAuth2Client:
    s = get_settings()
    return OAuth2Client(s.google_client_id, s.google_client_secret, scope=scope, redirect_uri=redirect_uri())


def authorization_url(state: str, scope: str = BASE_SCOPES, *, offline: bool = False) -> str:
    c = client(scope)
    kw = {"access_type": "offline", "prompt": "consent"} if offline else {}
    url, _ = c.create_authorization_url(AUTH_URL, state=state, **kw)
    return url


def exchange(code: str, scope: str = BASE_SCOPES) -> tuple[dict, dict]:
    c = client(scope)
    token = c.fetch_token(TOKEN_URL, code=code, grant_type="authorization_code")
    info = c.get(USERINFO_URL).json()
    return token, info
