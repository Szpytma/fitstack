from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, status

from app import auth
from app.config import settings
from app.providers.base import FitnessProvider
from app.providers.garmin import GarminProvider
from app.routers.auth import current_user


@lru_cache(maxsize=32)
def _provider_for(tokenstore: str) -> GarminProvider:
    """One provider per token directory.

    Keyed by path rather than a single global: several accounts can be signed
    in at once, each reaching a different Garmin account, and they must never
    share a client.
    """
    return GarminProvider(tokenstore=tokenstore)


def reset_provider_cache() -> None:
    """Drop cached providers after tokens are uploaded or removed."""
    _provider_for.cache_clear()


def tokenstore_for(uid: str, user: dict) -> str | None:
    """Where this account's Garmin tokens live, or None if it has none.

    Per-account tokens win. The admin falls back to the original
    `~/.garminconnect` path so the pre-multi-user setup — and the MCP server,
    which still reads exactly that path — keeps working untouched.
    """
    own = auth.token_dir(uid)
    if (own / "garmin_tokens.json").exists():
        return str(own)
    if user.get("admin"):
        legacy = Path(settings.garmin_tokenstore)
        if (legacy / "garmin_tokens.json").exists():
            return str(legacy)
    return None


def get_garmin(who: tuple[str, dict] = Depends(current_user)) -> FitnessProvider:
    uid, user = who
    tokenstore = tokenstore_for(uid, user)
    if tokenstore is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "This account has no Garmin connection yet. Upload your "
                "garmin_tokens.json on the Account page."
            ),
        )

    prov = _provider_for(tokenstore)
    if not prov.is_available():
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "Garmin tokens were found but could not be used. Re-run the Garmin "
                "login and upload a fresh garmin_tokens.json."
            ),
        )
    return prov


# Alias for future multi-provider dispatch. Right now every route uses Garmin;
# once Strava lands, routers can accept a `provider` query param and use this
# resolver instead.
def get_provider(
    name: str = "garmin", who: tuple[str, dict] = Depends(current_user)
) -> FitnessProvider:
    if name == "garmin":
        return get_garmin(who)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Provider '{name}' is not registered.",
    )


ProviderDep = Depends(get_garmin)
