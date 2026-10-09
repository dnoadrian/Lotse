"""Verschlüsselte Zugangsdaten je Postfach. Klartext existiert nur kurzzeitig im Speicher."""
from __future__ import annotations

from ..models import MailAccount
from ..security.crypto import decrypt, encrypt


def _purpose(account: MailAccount, field: str) -> str:
    # An Nutzer und Feld gebunden: ein kopiertes Chiffrat ist woanders unbrauchbar
    return f"mail_account:{account.user_id}:{account.provider}:{field}"


def store_credentials(account: MailAccount, username: str, secret: str) -> None:
    account.username_enc = encrypt(username, _purpose(account, "username")) if username else ""
    account.secret_enc = encrypt(secret, _purpose(account, "secret"))


def credentials(account: MailAccount) -> dict[str, str]:
    return {
        "username": decrypt(account.username_enc, _purpose(account, "username")) if account.username_enc else "",
        "secret": decrypt(account.secret_enc, _purpose(account, "secret")),
    }
