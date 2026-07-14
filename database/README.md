# Production database

`bblotto_v34.db` is intentionally excluded to prevent overwriting live member and administrator data.

Set `BBLOTTO_DB_DIR` to the existing persistent disk directory in production.
For a new installation, the application can initialize a new database in the configured directory.

## Production safety

The upload package intentionally contains no database file. In production set
`APP_ENV=production` and configure either `DATABASE_URL` or a writable persistent
`BBLOTTO_DB_DIR`. Startup stops with a clear error when persistent storage or
`BBLOTTO_SECRET_KEY` is missing.
