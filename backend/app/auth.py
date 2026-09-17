"""FitStack's own accounts — entirely separate from Garmin.

FitStack never sees a Garmin password. This module decides *who is asking*;
which Garmin account they then reach is resolved separately in `deps.py` from
the token file belonging to that user.

No new dependencies. `hashlib.scrypt` is a proper memory-hard KDF in the
standard library, and the session cookie is signed with `hmac`, so there is no
server-side session store to lose when the reloader restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

AUTH_DIR = Path.home() / ".fitstack"
AUTH_FILE = AUTH_DIR / "auth.json"
USERS_DIR = AUTH_DIR / "users"

COOKIE_NAME = "fitstack_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # a month; this is a personal tool, not a bank

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 32

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}$")


# ---------- storage ----------

def _read() -> dict[str, Any]:
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - corrupt file
        log.warning("auth: could not read %s (%s)", AUTH_FILE, exc)
        return {}


def _write(data: dict[str, Any]) -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(AUTH_FILE, 0o600)  # no-op on Windows ACLs, correct elsewhere
    except OSError:  # pragma: no cover - platform dependent
        pass


def _load() -> dict[str, Any]:
    """Read state, upgrading the old single-password file on the way through.

    v1 stored one `password_hash` at the top level. That becomes the first admin
    user, so an existing install keeps working without anyone re-registering.
    """
    data = _read()
    if data.get("password_hash") and "users" not in data:
        uid = secrets.token_hex(8)
        data = {
            "secret": data.get("secret") or secrets.token_hex(32),
            "users": {
                uid: {
                    "username": "owner",
                    "password_hash": data["password_hash"],
                    "admin": True,
                    "created": int(time.time()),
                }
            },
        }
        _write(data)
        log.info("auth: migrated the single password to user 'owner'")
    data.setdefault("users", {})
    return data


def users() -> dict[str, dict[str, Any]]:
    return _load().get("users", {})


def is_configured() -> bool:
    return bool(users())


def user_by_name(username: str) -> tuple[str, dict[str, Any]] | None:
    for uid, u in users().items():
        if u.get("username") == username.lower().strip():
            return uid, u
    return None


def get_user(uid: str) -> dict[str, Any] | None:
    return users().get(uid)


def token_dir(uid: str) -> Path:
    """Where this user's Garmin tokens live. Ids are hex, so path-safe."""
    return USERS_DIR / uid


# ---------- passwords ----------

def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DK_LEN
    )
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(dk_b64)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=len(expected)
    )
    # Constant time: a timing difference would leak how much of the hash matched.
    return hmac.compare_digest(dk, expected)


def create_user(username: str, password: str, admin: bool = False) -> str:
    username = username.lower().strip()
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 2-31 characters: lowercase letters, digits, dot, dash or underscore."
        )
    if user_by_name(username):
        raise ValueError("That username is taken.")

    data = _load()
    uid = secrets.token_hex(8)
    data["users"][uid] = {
        "username": username,
        "password_hash": hash_password(password),
        "admin": admin,
        "created": int(time.time()),
    }
    data.setdefault("secret", secrets.token_hex(32))
    _write(data)
    return uid


def set_password(uid: str, password: str) -> None:
    data = _load()
    if uid not in data["users"]:
        raise ValueError("No such user.")
    data["users"][uid]["password_hash"] = hash_password(password)
    _write(data)


def delete_user(uid: str) -> None:
    data = _load()
    data["users"].pop(uid, None)
    _write(data)


# ---------- sessions ----------

def _secret() -> bytes:
    data = _load()
    secret = data.get("secret")
    if not secret:
        secret = secrets.token_hex(32)
        data["secret"] = secret
        _write(data)
    return secret.encode("utf-8")


def issue_session(uid: str) -> str:
    """`<expiry>.<uid>.<hmac>` — stateless, so a restart doesn't sign anyone out."""
    expires = int(time.time()) + SESSION_MAX_AGE
    payload = f"{expires}.{uid}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def session_user(token: str | None) -> str | None:
    """The user id a cookie proves, or None if absent, expired or forged."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    expires_s, uid, sig = parts
    try:
        if int(expires_s) < time.time():
            return None
    except ValueError:
        return None
    good = hmac.new(
        _secret(), f"{expires_s}.{uid}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    # A deleted user's cookie must stop working immediately.
    return uid if uid in users() else None


def revoke_sessions() -> None:
    """Roll the signing secret, invalidating every cookie for every user."""
    data = _load()
    data["secret"] = secrets.token_hex(32)
    _write(data)
