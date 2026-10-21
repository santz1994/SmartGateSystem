"""Autentikasi & otorisasi sesi untuk prototipe.

Identitas operator diambil dari sesi server — tidak pernah dari body request —
sehingga jejak audit (``override_by``) tidak dapat dipalsukan klien (C1, C2).
Password disimpan sebagai PBKDF2-HMAC-SHA256 (stdlib) di ``users.password_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import wraps
from typing import Any, Callable

from flask import abort, redirect, request, session, url_for

from . import db

_ITERATIONS = 200_000

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt}${digest.hex()}"

def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)

def login(username: str, password: str) -> None:
    """Buat sesi baru untuk user terdaftar. ValueError bila kredensial salah."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT username, role, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise ValueError("username atau password salah")
    session.clear()
    session["user"] = row["username"]
    session["role"] = row["role"]

def logout() -> None:
    session.clear()

def current_user() -> str | None:
    return session.get("user")

def current_role() -> str | None:
    return session.get("role")

def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            if request.path.startswith("/api/"):
                return {"error": "UNAUTHENTICATED"}, 401
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)

    return wrapper

def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_role() != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapper
