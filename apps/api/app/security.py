from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from cryptography.fernet import Fernet

from .config import settings


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"{salt}${base64.b64encode(derived).decode('ascii')}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    check = hash_password(password, salt)
    return hmac.compare_digest(check, stored)


def issue_token(payload: dict[str, Any], ttl_seconds: int = 60 * 60 * 24) -> str:
    data = dict(payload)
    data["exp"] = int(time.time()) + ttl_seconds
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii")
    signature = hmac.new(settings.auth_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("bad token format") from exc
    expected = hmac.new(settings.auth_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("bad token signature")
    payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("token expired")
    return payload


def encrypt_text(value: str) -> str:
    return Fernet(settings.fernet_key).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str) -> str:
    return Fernet(settings.fernet_key).decrypt(value.encode("utf-8")).decode("utf-8")
