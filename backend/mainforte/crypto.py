"""At-rest encryption for small secrets we store (ai-proxy keys, OAuth refresh tokens).
Key is derived from SECRET_KEY so no separate secret needs to be provisioned."""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from mainforte.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
