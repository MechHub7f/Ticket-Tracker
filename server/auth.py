"""Authentication and staff accounts (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from .db import Database

COOKIE_NAME = "tt_session"
SESSION_HOURS = 12
PBKDF2_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def user_count(db: Database) -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM users")
    return int(row["n"]) if row else 0


def create_user(
    db: Database, username: str, password: str, display_name: str = "", role: str = "staff"
) -> int:
    username = (username or "").strip().lower()
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    if role not in ("admin", "staff"):
        raise ValueError("Role must be admin or staff")
    if db.query_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise ValueError("That username is already taken")
    return db.insert(
        "users",
        {
            "username": username,
            "display_name": (display_name or username).strip(),
            "password_hash": hash_password(password),
            "role": role,
            "created_at": _now(),
        },
    )


def list_users(db: Database) -> list[dict]:
    return db.query(
        "SELECT id, username, display_name, role, created_at FROM users ORDER BY username"
    )


def delete_user(db: Database, user_id: int) -> None:
    if user_count(db) <= 1:
        raise ValueError("You cannot delete the last account")
    db.delete("users", user_id)


def set_password(db: Database, user_id: int, password: str) -> None:
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    db.update("users", user_id, {"password_hash": hash_password(password)})


def login(db: Database, username: str, password: str) -> tuple[str, dict]:
    user = db.query_one(
        "SELECT * FROM users WHERE username = ?", ((username or "").strip().lower(),)
    )
    if not user or not verify_password(password or "", user["password_hash"]):
        raise ValueError("Incorrect username or password")

    token = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    expires = created + timedelta(hours=SESSION_HOURS)
    db.insert(
        "sessions",
        {
            "token": token,
            "user_id": user["id"],
            "created_at": created.isoformat(timespec="seconds"),
            "expires_at": expires.isoformat(timespec="seconds"),
        },
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
    return token, public_user(user)


def get_session_user(db: Database, token: str | None) -> dict | None:
    if not token:
        return None
    row = db.query_one(
        """
        SELECT u.id, u.username, u.display_name, u.role, s.expires_at
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    )
    if not row:
        return None
    if row["expires_at"] < _now():
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def logout(db: Database, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
