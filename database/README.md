# Database directory

The application creates `bblotto_v34.db` automatically when SQLite is used.
The database file is intentionally excluded from this package and from Git.

For Render/Railway production, set `BBLOTTO_DB_DIR` to the mounted persistent
volume directory, or configure `DATABASE_URL` for PostgreSQL.
