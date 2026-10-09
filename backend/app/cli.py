"""Verwaltung über die Kommandozeile (im Container: docker compose exec backend python -m app.cli …).

Es gibt bewusst keine offene Registrierung: Benutzer werden nur hier angelegt.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import db as dbmod
from .config import get_settings
from .db import Base
from .models import User
from .security.passwords import WeakPasswordError, hash_password, validate_password
from .security.sessions import revoke_user_sessions


def _ask_password(username: str) -> str:
    while True:
        pw = getpass.getpass("Passwort: ")
        if pw != getpass.getpass("Passwort wiederholen: "):
            print("Die Passwörter stimmen nicht überein.")
            continue
        try:
            validate_password(pw, username)
            return pw
        except WeakPasswordError as exc:
            print(exc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("username")
    r = sub.add_parser("reset-password")
    r.add_argument("username")
    t = sub.add_parser("disable-2fa")
    t.add_argument("username")
    sub.add_parser("list-users")
    args = p.parse_args(argv)

    s = get_settings()
    s.validate_secrets()
    Base.metadata.create_all(dbmod.init_engine(s.database_url))
    with dbmod.new_session() as db:
        name = getattr(args, "username", "").strip().lower()
        user = db.execute(select(User).where(User.username == name)).scalar_one_or_none() if name else None
        if args.cmd == "list-users":
            for u in db.execute(select(User).order_by(User.id)).scalars():
                print(f"{u.id}\t{u.username}\t2FA={'an' if u.totp_enabled else 'aus'}")
            return 0
        if args.cmd == "create-user":
            if not (3 <= len(name) <= 64) or not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                print("Benutzername: 3–64 Zeichen, nur Buchstaben, Ziffern, . _ -")
                return 1
            if user:
                print("Benutzer existiert bereits.")
                return 1
            db.add(User(username=name, password_hash=hash_password(_ask_password(name))))
            db.commit()
            print(f"Benutzer {name} angelegt.")
            return 0
        if user is None:
            print("Benutzer nicht gefunden.")
            return 1
        if args.cmd == "reset-password":
            user.password_hash = hash_password(_ask_password(name))
            db.commit()
            revoke_user_sessions(db, user.id)
            print("Passwort geändert, alle Sitzungen beendet.")
        elif args.cmd == "disable-2fa":
            user.totp_enabled, user.totp_secret_enc, user.totp_pending_enc = False, None, None
            db.commit()
            revoke_user_sessions(db, user.id)
            print("Zwei-Faktor-Anmeldung deaktiviert, alle Sitzungen beendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
