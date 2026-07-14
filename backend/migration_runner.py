"""Versioned database startup migration runner.

The legacy schema initializer remains the source of truth, but expensive schema
inspection now runs only when the migration version changes.
"""
from __future__ import annotations

from typing import Callable, Any


def run_versioned_migrations(
    connect: Callable[[], Any],
    initializer: Callable[[], None],
    logger: Any,
    version: int = 8,
) -> None:
    needs_migration = True
    try:
        with connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = db.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current = int(row["version"] if row else 0)
            db.commit()
            needs_migration = current < int(version)
    except Exception:
        logger.exception("failed to inspect schema migration version")
        needs_migration = True

    if not needs_migration:
        logger.info("database schema migration already current: v%s", version)
        return

    logger.info("applying database schema migration: v%s", version)
    initializer()
    with connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        db.execute("DELETE FROM schema_migrations")
        db.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, CURRENT_TIMESTAMP)",
            (int(version),),
        )
        db.commit()
    logger.info("database schema migration complete: v%s", version)
