from __future__ import annotations

import json as _json
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, status
from pydantic import BaseModel, Field

from app import auth
from app.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Token files are a couple of kB; anything larger is not one.
MAX_TOKEN_BYTES = 64 * 1024


class Credentials(BaseModel):
    username: str = Field(..., min_length=2, max_length=31)
    # Long enough to resist guessing over a LAN; no complexity theatre.
    password: str = Field(..., min_length=8, max_length=200)


class NewUser(Credentials):
    admin: bool = False


class UserOut(BaseModel):
    id: str
    username: str
    admin: bool
    garmin_connected: bool


class AuthStatus(BaseModel):
    configured: bool
    authenticated: bool
    user: UserOut | None = None


def _garmin_connected(uid: str, is_admin: bool) -> bool:
    if (auth.token_dir(uid) / "garmin_tokens.json").exists():
        return True
    # The admin inherits the pre-multi-user token file so nothing breaks.
    return is_admin and (Path(settings.garmin_tokenstore) / "garmin_tokens.json").exists()


def _user_out(uid: str, u: dict) -> UserOut:
    admin = bool(u.get("admin"))
    return UserOut(
        id=uid,
        username=u.get("username", "?"),
        admin=admin,
        garmin_connected=_garmin_connected(uid, admin),
    )


# The identity every request runs as when logins are switched off. Marked admin
# so it resolves to the legacy `garmintokens` path — i.e. plain single-user
# behaviour, exactly as before accounts existed.
LOCAL_USER = ("local", {"username": "local", "admin": True})


def current_user(request: Request) -> tuple[str, dict]:
    """Gate every data route.

    401 rather than 403 so the frontend can tell "sign in" apart from the 412
    it already handles for missing Garmin tokens.
    """
    if not settings.fitstack_require_auth:
        return LOCAL_USER
    if not auth.is_configured():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="FitStack has no accounts yet. Open the app to create the first one.",
        )
    uid = auth.session_user(request.cookies.get(auth.COOKIE_NAME))
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in."
        )
    user = auth.get_user(uid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return uid, user


def require_admin(who: tuple[str, dict] = Depends(current_user)) -> tuple[str, dict]:
    if not who[1].get("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admins only."
        )
    return who


AuthDep = Depends(current_user)


def _set_cookie(response: Response, uid: str) -> None:
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_session(uid),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        # `secure` is deliberately off: FitStack runs over plain HTTP on a LAN,
        # and a Secure cookie would simply never be sent.
        secure=False,
        path="/",
    )


@router.get("/status", response_model=AuthStatus, summary="Whether an account exists and who is signed in")
def status_(request: Request) -> AuthStatus:
    if not settings.fitstack_require_auth:
        uid, u = LOCAL_USER
        return AuthStatus(configured=True, authenticated=True, user=_user_out(uid, u))
    configured = auth.is_configured()
    uid = auth.session_user(request.cookies.get(auth.COOKIE_NAME)) if configured else None
    user = auth.get_user(uid) if uid else None
    return AuthStatus(
        configured=configured,
        authenticated=bool(user),
        user=_user_out(uid, user) if uid and user else None,
    )


@router.post("/setup", response_model=AuthStatus, summary="Create the first account")
def setup(body: Credentials, response: Response) -> AuthStatus:
    """Only available while there are no accounts, so it cannot be used to take over.

    Whoever reaches an unconfigured instance first claims it — do this
    immediately after exposing the app to a network.
    """
    if auth.is_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already exists. Sign in instead.",
        )
    try:
        uid = auth.create_user(body.username, body.password, admin=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _set_cookie(response, uid)
    log.info("auth: first account created")
    return AuthStatus(configured=True, authenticated=True, user=_user_out(uid, auth.get_user(uid)))


@router.post("/login", response_model=AuthStatus, summary="Sign in")
def login(body: Credentials, response: Response) -> AuthStatus:
    found = auth.user_by_name(body.username)
    # Same error whether the user is unknown or the password is wrong, so this
    # cannot be used to enumerate who has an account.
    if not found or not auth.verify_password(body.password, found[1].get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password."
        )
    uid, user = found
    _set_cookie(response, uid)
    return AuthStatus(configured=True, authenticated=True, user=_user_out(uid, user))


@router.post("/logout", response_model=AuthStatus, summary="Sign out on this device")
def logout(response: Response) -> AuthStatus:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return AuthStatus(configured=auth.is_configured(), authenticated=False)


# ---------- accounts (admin) ----------

@router.get("/users", response_model=list[UserOut], summary="List accounts")
def list_users(who: tuple[str, dict] = Depends(require_admin)) -> list[UserOut]:
    return [_user_out(uid, u) for uid, u in auth.users().items()]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Create an account")
def add_user(body: NewUser, who: tuple[str, dict] = Depends(require_admin)) -> UserOut:
    try:
        uid = auth.create_user(body.username, body.password, admin=body.admin)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _user_out(uid, auth.get_user(uid))


@router.delete("/users/{uid}", summary="Delete an account and its stored tokens")
def remove_user(uid: str, who: tuple[str, dict] = Depends(require_admin)) -> dict:
    if uid == who[0]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account."
        )
    if not auth.get_user(uid):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such account.")
    auth.delete_user(uid)
    # Their Garmin tokens go with them — leaving credentials behind for a
    # deleted account would be worse than useless.
    shutil.rmtree(auth.token_dir(uid), ignore_errors=True)
    return {"deleted": uid}


# ---------- Garmin connection ----------

@router.post("/garmin", summary="Upload this account's Garmin token file")
async def connect_garmin(
    file: UploadFile = File(...),
    who: tuple[str, dict] = Depends(current_user),
) -> dict:
    """Accepts the `garmin_tokens.json` produced by python-garminconnect.

    Deliberately a file, not credentials: FitStack never asks for a Garmin
    password. The user runs the interactive login on their own machine and
    hands over only the resulting tokens.
    """
    uid, _user = who
    raw = await file.read()
    if len(raw) > MAX_TOKEN_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="That file is far too large to be a token file.",
        )

    try:
        parsed = _json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"That is not valid JSON ({exc}).",
        ) from exc

    # Cheap shape check so an unrelated JSON file fails here rather than as a
    # confusing Garmin error later.
    if not isinstance(parsed, dict) or not any(
        k in parsed for k in ("oauth1_token", "oauth2_token", "access_token", "refresh_token")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That JSON does not look like a Garmin token file.",
        )

    target = auth.token_dir(uid)
    target.mkdir(parents=True, exist_ok=True)
    dest = target / "garmin_tokens.json"
    dest.write_bytes(raw)
    try:
        os.chmod(dest, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass

    # A newly connected account must not keep serving from a cached provider.
    from app.deps import reset_provider_cache

    reset_provider_cache()
    log.info("auth: garmin tokens stored for user %s", uid)
    return {"connected": True}


@router.delete("/garmin", summary="Forget this account's Garmin tokens")
def disconnect_garmin(who: tuple[str, dict] = Depends(current_user)) -> dict:
    uid, _user = who
    shutil.rmtree(auth.token_dir(uid), ignore_errors=True)

    from app.deps import reset_provider_cache

    reset_provider_cache()
    return {"connected": False}
