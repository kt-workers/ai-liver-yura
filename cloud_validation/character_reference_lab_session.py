from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CharacterReferenceLabSession:
    username: str
    password: str
    ttl_seconds: int = 180 * 24 * 60 * 60

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)

    def validate_credentials(self, username: str, password: str) -> bool:
        if not self.configured:
            return False
        return hmac.compare_digest(username, self.username) and hmac.compare_digest(
            password, self.password
        )

    def issue(self, *, now: int | None = None) -> str:
        if not self.configured:
            raise RuntimeError("Lab session authentication is not configured")
        issued_at = int(time.time()) if now is None else int(now)
        payload = {
            "sub": self.username,
            "iat": issued_at,
            "exp": issued_at + self.ttl_seconds,
        }
        encoded = _base64url_encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        signature = _base64url_encode(
            hmac.new(self._signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}"

    def validate(self, token: str | None, *, now: int | None = None) -> bool:
        if not self.configured or not token:
            return False
        try:
            encoded, signature = token.split(".", 1)
        except ValueError:
            return False
        expected = _base64url_encode(
            hmac.new(self._signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return False
        try:
            payload = json.loads(_base64url_decode(encoded).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("sub") != self.username:
            return False
        expiry = payload.get("exp")
        if not isinstance(expiry, int):
            return False
        current = int(time.time()) if now is None else int(now)
        return current < expiry

    def _signing_key(self) -> bytes:
        material = f"yura-reference-lab\0{self.username}\0{self.password}".encode("utf-8")
        return hashlib.sha256(material).digest()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
