"""Settings, path resolution and secret handling."""

from __future__ import annotations

import pytest

from siap.paths import config_dir, migrations_dir, repo_root
from siap.settings import MissingSetting, Redacted, redact_dsn


def test_repo_root_is_found_from_the_package() -> None:
    root = repo_root()
    assert (root / "supabase" / "migrations").is_dir()
    assert (root / "engine" / "config").is_dir()


def test_paths_resolve_under_the_repo_root() -> None:
    assert config_dir().is_dir()
    assert migrations_dir().is_dir()
    assert config_dir().parent.parent == repo_root()


def test_redact_dsn_hides_the_password_but_keeps_the_target_identifiable() -> None:
    dsn = "postgresql://postgres.abcdef:sup3r-s3cret@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"
    redacted = redact_dsn(dsn)
    assert "sup3r-s3cret" not in redacted
    assert "<redacted>" in redacted
    assert "pooler.supabase.com" in redacted
    assert "5432" in redacted
    assert "postgres.abcdef" in redacted


def test_redact_dsn_never_raises_on_garbage() -> None:
    assert isinstance(redact_dsn("not a url at all"), str)
    assert isinstance(redact_dsn(""), str)


def test_redacted_refuses_to_print_itself() -> None:
    secret = Redacted("hunter2")
    assert "hunter2" not in str(secret)
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in f"{secret}"
    assert secret.value == "hunter2"


def test_missing_setting_names_the_variable_and_offers_a_fix() -> None:
    exc = MissingSetting("DATABASE_URL", "Supabase: Settings -> Database.")
    message = str(exc)
    assert "DATABASE_URL" in message
    assert ".env.example" in message
    assert exc.name == "DATABASE_URL"


def test_required_setting_raises_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    import siap.settings as settings_module

    monkeypatch.setenv("DATABASE_URL", "   ")
    settings_module._load_env.cache_clear()
    with pytest.raises(MissingSetting):
        settings_module.database_url()
