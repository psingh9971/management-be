import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt

from app.core.config import settings

# scrypt parameters (OWASP-recommended minimum: N=2^17, r=8, p=1).
# Stored alongside each hash, so they can be raised later without breaking old hashes.
_SCRYPT_N = 2 ** 17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 256 * 1024 * 1024
_SALT_BYTES = 16
_KEY_BYTES = 64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """Return 'scrypt$N$r$p$salt$hash' using the standard library's scrypt."""
    salt = os.urandom(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM, dklen=_KEY_BYTES,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algo, n, r, p, salt_b64, key_b64 = hashed.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(key_b64)
        key = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected)


# Used when the username doesn't exist, so login takes the same time either way
# (stops attackers discovering valid usernames by timing the response).
DUMMY_HASH = hash_password("timing-attack-dummy-password")


def create_access_token(subject: str, extra_claims: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **extra_claims,
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Raises jwt.PyJWTError if the token is invalid or expired."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload
