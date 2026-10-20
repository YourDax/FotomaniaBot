"""Хеширование пароля и HTTP Basic-аутентификация."""

from __future__ import annotations

import base64
import hashlib
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .db import session_scope
from .models import Setting

PBKDF2_ITERATIONS = 200_000
PBKDF2_SCHEME = "pbkdf2"
OPERATOR_USERNAME = "operator"

security = HTTPBasic(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        f"{PBKDF2_SCHEME}${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_raw, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != PBKDF2_SCHEME:
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations_raw)
        )
        return secrets.compare_digest(digest, expected)
    except Exception:
        return False


def _stored_password_hash() -> str | None:
    with session_scope() as session:
        setting = session.get(Setting, "password_hash")
        return setting.value if setting is not None else None


def require_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> bool:
    """Allow everything until a password is configured (local single-user app)."""
    stored = _stored_password_hash()
    if stored is None:
        return True
    if (
        credentials is None
        or not secrets.compare_digest(credentials.username, OPERATOR_USERNAME)
        or not verify_password(credentials.password, stored)
    ):
        raise HTTPException(
            401, "Неверные учетные данные", headers={"WWW-Authenticate": "Basic"}
        )
    return True
