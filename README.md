# Excise Fee Estimator

Flask/Jinja vehicle fee calculator with private saved estimates, audit history and
Super Admin, Admin and User roles. Flask sessions, CSRF, Werkzeug hashes and session
invalidation are preserved. Supabase PostgreSQL is accessed server-side through psycopg.

See [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for configuration, safe migrations/imports,
local tests, deployment and troubleshooting.

```powershell
uv sync
Copy-Item .env.example .env
# Configure DATABASE_URL and SECRET_KEY privately; review migrations first.
uv run flask --app run db-migrate
# Only after approval of writes to this destination:
uv run flask --app run db-migrate --confirm-write
uv run python run.py
```

Requires Python 3.12 (see .python-version). Open http://127.0.0.1:5000.
`app.py` remains the Vercel entrypoint, and static assets are in `public/static/`.
Application startup never creates or upgrades PostgreSQL tables.

There is no public /setup page. After explicit approval, an operator can create the
single protected Super Admin with `uv run flask --app run create-superadmin USERNAME`.
It prompts for the password. Never run this against production without approval.
Signup defaults off; when enabled it creates a normal User only.
Admins manage normal users; only the Super Admin may manage admins, review all activity
and view other users' estimates read-only. Everyone can manage their own estimates.

Authorized terminal recovery: `uv run flask --app run set-password USERNAME`.
Never delete/reset databases for password recovery. Private instance/users.db and
secret_key are preserved. Existing SQLite imports preserve hashes, IDs and ownership.

```powershell
uv run pytest
# Optional: local disposable TEST_DATABASE_URL ending _test, never production:
uv run pytest --postgres
```

Default tests are offline and use temporary SQLite doubles. They do not verify actual
PostgreSQL SQL. Live migration/import checks are skipped until --postgres is configured.
The calculator's original fee engine and reference result 408190 are preserved.
