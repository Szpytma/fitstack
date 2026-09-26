"""Convenience launcher for local development.

Usage:
    python run.py

Set FITSTACK_RELOAD=true in backend/.env to hot-reload on file changes. It is
off by default: see `Settings.fitstack_reload` for the failure it avoids.
"""

import uvicorn

from app.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.fitstack_reload,
        log_level="info",
    )
