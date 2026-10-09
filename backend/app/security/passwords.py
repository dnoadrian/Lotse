"""Passwort-Hashing mit Argon2id (Parameter nach RFC 9106, Profil für wenig Speicher)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id, t=3, m=64 MiB, p=4

# Wird verifiziert, wenn ein Benutzer nicht existiert, damit die Antwortzeit
# nicht verrät, ob ein Benutzername vergeben ist.
_DUMMY_HASH = _hasher.hash("lotse-dummy-password-for-timing")

MIN_LENGTH = 4
MAX_LENGTH = 256


class WeakPasswordError(ValueError):
    pass


def validate_password(password: str, username: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Das Passwort muss mindestens {MIN_LENGTH} Zeichen lang sein.")
    if len(password) > MAX_LENGTH:
        raise WeakPasswordError(f"Das Passwort darf höchstens {MAX_LENGTH} Zeichen lang sein.")
    if username and username.lower() in password.lower():
        raise WeakPasswordError("Das Passwort darf den Benutzernamen nicht enthalten.")
    if len(set(password)) < 2:
        raise WeakPasswordError("Das Passwort ist zu gleichförmig.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
