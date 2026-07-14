"""Runtime environment validation for BBLOTTO.

Production safeguards are enabled only when APP_ENV=production. Development
and test environments keep the existing convenient defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


@dataclass(frozen=True)
class RuntimeSettings:
    app_env: str
    is_production: bool
    secret_key: str
    admin_username: str
    admin_password: str
    database_url_present: bool
    db_dir_raw: str


def load_runtime_settings() -> RuntimeSettings:
    app_env = _env("APP_ENV", "development").lower()
    return RuntimeSettings(
        app_env=app_env,
        is_production=app_env in {"production", "prod"},
        secret_key=_env("BBLOTTO_SECRET_KEY"),
        admin_username=_env("BBLOTTO_ADMIN_USERNAME", "admin") or "admin",
        admin_password=_env("BBLOTTO_ADMIN_PASSWORD"),
        database_url_present=bool(
            _env("DATABASE_URL")
            or _env("POSTGRES_URL")
            or (_env("PGHOST") and (_env("PGUSER") or _env("POSTGRES_USER")) and (_env("PGDATABASE") or _env("POSTGRES_DB")))
        ),
        db_dir_raw=_env("BBLOTTO_DB_DIR"),
    )


def validate_startup_environment(settings: RuntimeSettings) -> None:
    """Fail fast on unsafe production configuration.

    Admin password is validated separately when the admins table is empty, so
    an existing production database does not require the old bootstrap password.
    """
    if not settings.is_production:
        return

    errors: list[str] = []
    if len(settings.secret_key) < 32:
        errors.append("BBLOTTO_SECRET_KEY must be at least 32 characters")
    if not settings.database_url_present and not settings.db_dir_raw:
        errors.append("set DATABASE_URL or BBLOTTO_DB_DIR to persistent storage")
    if settings.db_dir_raw:
        db_dir = Path(settings.db_dir_raw).expanduser()
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
            probe = db_dir / ".bblotto_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"BBLOTTO_DB_DIR is not writable: {db_dir} ({exc})")

    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"Unsafe production configuration: {joined}")


def require_bootstrap_admin_password(settings: RuntimeSettings) -> str:
    """Return a safe bootstrap password or fail in production."""
    password = settings.admin_password
    if settings.is_production:
        if len(password) < 10:
            raise RuntimeError(
                "BBLOTTO_ADMIN_PASSWORD is required (minimum 10 characters) "
                "when creating the first production administrator"
            )
        return password
    return password
