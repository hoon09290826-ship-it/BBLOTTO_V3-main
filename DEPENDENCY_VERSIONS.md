# Dependency version policy

Production packages are pinned in `requirements.txt` so Render, Railway, Docker,
and local installations resolve the same direct dependency versions.

Update procedure:
1. Create a test branch.
2. Change one package version at a time.
3. Install with `pip install -r requirements.txt`.
4. Run syntax, import, login, member, recommendation, and export checks.
5. Deploy to a staging service before production.

The production SQLite database is intentionally not included in this package.
Configure `BBLOTTO_DB_DIR` to point to the existing persistent disk directory.
