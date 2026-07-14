# Render production environment

Set these variables in Render **Environment** before deploying with `APP_ENV=production`.

```text
APP_ENV=production
BBLOTTO_SECRET_KEY=<random value of at least 32 characters>
DATABASE_URL=<Render PostgreSQL internal URL>
```

When using a Render persistent disk with SQLite instead of PostgreSQL:

```text
APP_ENV=production
BBLOTTO_SECRET_KEY=<random value of at least 32 characters>
BBLOTTO_DB_DIR=/var/data/bblotto_database
```

`BBLOTTO_ADMIN_PASSWORD` is required only when the selected database has no
administrator yet. Existing databases continue to use the password hash already
stored in the database.

```text
BBLOTTO_ADMIN_USERNAME=admin
BBLOTTO_ADMIN_PASSWORD=<minimum 10 characters>
```

Do not commit real secrets to GitHub. The `.env.example` file contains examples
only and `.env` is ignored.
