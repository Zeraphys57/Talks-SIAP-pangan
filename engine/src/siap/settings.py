"""Environment settings.

Loads `.env` from the repository root once, then exposes the values as typed
accessors that raise a specific, actionable error when something is missing —
rather than returning None and failing three call frames later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

from .paths import repo_root


class MissingSetting(RuntimeError):
    """Raised when a required environment variable is absent or blank."""

    def __init__(self, name: str, hint: str) -> None:
        super().__init__(
            f"Environment variable {name} is not set.\n"
            f"  {hint}\n"
            f"  Copy .env.example to .env at the repository root and fill it in."
        )
        self.name = name


@lru_cache(maxsize=1)
def _load_env() -> None:
    load_dotenv(repo_root() / ".env", override=False)


def _get(name: str) -> str | None:
    _load_env()
    value = os.environ.get(name, "").strip()
    return value or None


def _require(name: str, hint: str) -> str:
    value = _get(name)
    if value is None:
        raise MissingSetting(name, hint)
    return value


def database_url() -> str:
    """Direct Postgres DSN. Used for migrations and all engine writes."""
    return _require(
        "DATABASE_URL",
        "Supabase: Project Settings -> Database -> Connection string -> URI. "
        "Use the session pooler on port 5432; the transaction pooler on 6543 "
        "cannot run DDL.",
    )


def supabase_url() -> str:
    """Supabase REST endpoint, e.g. https://<ref>.supabase.co."""
    return _require("SUPABASE_URL", "Supabase: Project Settings -> API -> Project URL.")


def supabase_anon_key() -> str:
    """Public anon key. Browser-safe; every request it makes is subject to RLS."""
    value = _get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or _get("SUPABASE_ANON_KEY")
    if value is None:
        raise MissingSetting(
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "Supabase: Project Settings -> API -> anon/public key.",
        )
    return value


def contact_email() -> str:
    """Contact address advertised in the User-Agent of every outbound request."""
    return _require(
        "SIAP_CONTACT_EMAIL",
        "A real address a portal operator can reach the team at. Scraping "
        "conduct requires an identifying User-Agent (config/sources.yaml).",
    )


def has(name: str) -> bool:
    """True when `name` is set and non-blank. For optional / test-skip checks."""
    return _get(name) is not None


@dataclass(frozen=True)
class Redacted:
    """A secret that refuses to print itself.

    Connection strings carry the database password. They end up in log lines and
    exception messages by accident far too easily, so anything that might be
    echoed is wrapped here first.
    """

    value: str

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "<redacted>"


def redact_dsn(dsn: str) -> str:
    """Render a DSN safe to log: keep host, port and database, drop credentials."""
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(dsn)
        host = parts.hostname or "?"
        port = parts.port or 5432
        name = (parts.path or "/?").lstrip("/") or "?"
        user = parts.username or "?"
        return f"postgresql://{user}:<redacted>@{host}:{port}/{name}"
    except Exception:  # pragma: no cover - never let redaction itself raise
        return "<unparseable dsn>"
