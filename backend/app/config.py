from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    garmintokens: str = "~/.garminconnect"
    fitstack_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Where the active rolling plan is pinned. The only thing FitStack persists —
    # see active_plan.py for why a rolling plan cannot be stateless.
    fitstack_state_dir: str = "~/.fitstack"

    # Whether callers must sign in. Defaults to on, because the safe default for
    # something that might be network-exposed is "locked". Turn it off for a
    # single-user instance on a trusted network: every request is then treated
    # as the owner and served from `garmintokens`. The multi-user code stays
    # intact either way — this only decides whether it is consulted.
    fitstack_require_auth: bool = True

    strava_client_id: str = ""
    strava_client_secret: str = ""

    @property
    def garmin_tokenstore(self) -> str:
        return str(Path(self.garmintokens).expanduser())

    @property
    def state_dir(self) -> Path:
        return Path(self.fitstack_state_dir).expanduser()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.fitstack_cors_origins.split(",") if o.strip()]

    @property
    def strava_configured(self) -> bool:
        return bool(self.strava_client_id and self.strava_client_secret)


settings = Settings()
