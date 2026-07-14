"""Session queries kept outside HTTP/router code.

The helpers accept the application's connection factory so they work with both
SQLite and the PostgreSQL compatibility connection without importing the app.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable


def get_active_admin_by_token(connect: Callable[[], Any], token: str):
    with connect() as conn:
        return conn.execute(
            "SELECT s.token,s.expires_at,s.last_seen_at,a.* "
            "FROM sessions s JOIN admins a ON a.id=s.admin_id "
            "WHERE s.token=? AND a.is_active=1",
            (token,),
        ).fetchone()


def delete_session(connect: Callable[[], Any], token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()


def touch_session_if_due(
    connect: Callable[[], Any],
    token: str,
    last_seen_at: str | None,
    now_text: str,
    interval_seconds: int = 60,
) -> bool:
    """Update last_seen_at at most once per interval.

    A dashboard can make many authenticated API calls at once. Updating and
    committing the same session row for every call creates avoidable locking on
    SQLite and round trips on PostgreSQL.
    """
    due = True
    try:
        previous = _dt.datetime.strptime(str(last_seen_at or ""), "%Y-%m-%d %H:%M:%S")
        current = _dt.datetime.strptime(now_text, "%Y-%m-%d %H:%M:%S")
        due = (current - previous).total_seconds() >= max(10, int(interval_seconds))
    except (TypeError, ValueError):
        due = True
    if not due:
        return False
    with connect() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token=?", (now_text, token))
        conn.commit()
    return True
