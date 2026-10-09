"""Authentifizierte Verschlüsselung (AES-256-GCM) für gespeicherte Zugangsdaten.

Format: "v1:<key-id>:<base64(nonce || ciphertext+tag)>". Die "purpose"-Zeichenkette wird
als Associated Data gebunden, damit ein Chiffrat nicht in ein anderes Feld oder zu einem
anderen Nutzer kopiert werden kann.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings


class DecryptionError(Exception):
    pass


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"lotse-key-id" + key).hexdigest()[:8]


def _keys() -> tuple[bytes, dict[str, bytes]]:
    s = get_settings()
    primary = s.decoded_key(s.encryption_key)
    keys = {_key_id(primary): primary}
    for old in filter(None, (k.strip() for k in s.encryption_keys_old.split(","))):
        k = s.decoded_key(old)
        keys[_key_id(k)] = k
    return primary, keys


def encrypt(plaintext: str, purpose: str) -> str:
    primary, _ = _keys()
    nonce = os.urandom(12)
    ct = AESGCM(primary).encrypt(nonce, plaintext.encode("utf-8"), purpose.encode("utf-8"))
    return f"v1:{_key_id(primary)}:" + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str, purpose: str) -> str:
    try:
        version, kid, payload = token.split(":", 2)
        if version != "v1":
            raise DecryptionError("Unbekanntes Format")
        _, keys = _keys()
        key = keys.get(kid)
        if key is None:
            raise DecryptionError("Unbekannter Schlüssel")
        raw = base64.b64decode(payload, validate=True)
        return AESGCM(key).decrypt(raw[:12], raw[12:], purpose.encode("utf-8")).decode("utf-8")
    except DecryptionError:
        raise
    except Exception as exc:  # InvalidTag, ValueError …
        raise DecryptionError("Entschlüsselung fehlgeschlagen") from exc


def needs_reencrypt(token: str) -> bool:
    primary, _ = _keys()
    try:
        return token.split(":", 2)[1] != _key_id(primary)
    except IndexError:
        return True


def token_hash(token: str) -> str:
    """Nicht umkehrbarer Hash für Sitzungs- und State-Tokens (hohe Entropie → SHA-256 genügt)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hmac_sign(message: str) -> str:
    key = base64.b64decode(get_settings().secret_key)
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
