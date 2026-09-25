from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from mainforte.config import get_settings

ALG = "HS256"


def mint_session(user_id: str, *, act_as: str | None = None, ttl: timedelta | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = ttl or (timedelta(hours=s.impersonation_ttl_hours) if act_as else timedelta(days=s.session_ttl_days))
    claims: dict[str, Any] = {"sub": user_id, "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp()), "typ": "session"}
    if act_as:
        claims["act_as"] = act_as
        claims["amr"] = ["impersonation"]
    return jwt.encode(claims, s.jwt_secret, algorithm=ALG)


def decode_session(token: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALG])
    except JWTError:
        return None
    return claims if claims.get("typ") == "session" else None
