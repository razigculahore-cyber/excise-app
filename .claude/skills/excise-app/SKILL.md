---
name: excise-app
description: Maintain the existing Flask Excise Fee Estimator, its session authentication, admin console, private estimates and browser fee engine.
---

# Excise Fee Estimator

Read README.md and SUPABASE_SETUP.md for commands and deployment details.
Use uv for environment and dependency management; preserve the existing application structure.

## Architecture

- run.py starts the app; app.py is a compatibility shim.
- backend/__init__.py builds the Flask app, registers security guards, CLI and safe errors.
- backend/config.py loads .env without overriding environment values.
- backend/db.py provides request-scoped psycopg connections with TLS, UTC, timeout,
  bound values, rollback/cleanup and a small DB-API compatibility adapter.
- PostgreSQL is selected by DATABASE_URL. Missing URL fails unless local DATABASE_BACKEND=sqlite
  is explicitly selected. TESTING mode always isolates from production URLs.
- backend/services contains user/password/lockout, estimate ownership and audit SQL.
- backend/routes contains thin auth/main/admin/api blueprints.
- backend/migrations.py owns explicit db-migrate and read-only-source db-import-sqlite commands.
- migrations/*.sql are versioned, checksum-verified and applied in one advisory-locked transaction.
- frontend/templates and static/css retain the current interface.
- frontend/static/js/estimator.js is the unchanged browser fee engine.
- tests use temporary SQLite by default; --postgres requires local TEST_DATABASE_URL ending _test.

## Commands

```powershell
uv venv .venv
uv pip sync --python .venv/Scripts/python.exe requirements.lock
uv run --no-project --python .venv/Scripts/python.exe pytest
uv run --no-project --python .venv/Scripts/python.exe run.py
node --check frontend/static/js/estimator.js
```

Copy .env.example privately to .env and configure DATABASE_URL, SECRET_KEY, HTTPS and ALLOW_SIGNUP.
Never print credentials or put them in command-line arguments. See SUPABASE_SETUP.md for migration
and import commands. Neither app startup nor migration previews write PostgreSQL schema.
Write commands require --confirm-write and production approval. Never modify production users
without approval. Do not commit or push automatically.

## Invariants

- Preserve Flask session auth and Werkzeug password hashes; do not switch to Supabase Auth.
- Every state change requires CSRF. Keep CSP, secure-cookie options and server authorization.
- Every estimate lookup/deletion filters by authenticated user_id.
- Keep one active admin and disallow self-disable/delete. PostgreSQL account mutations lock
  users to serialize last-admin checks; initial setup locks and rechecks before creating an admin.
- Signup creates staff only and defaults off. Protect first-run setup until the owner completes it.
- PostgreSQL uses identity IDs, case-insensitive username indexes, JSONB and UTC TIMESTAMPTZ.
  Presentation uses APP_TIMEZONE and maintains the existing timestamp string contract.
- failed_logins.at remains epoch seconds. Audit history intentionally survives deleted users.
- PostgreSQL API roles anon/authenticated must not access private application tables.
  Direct SQL authorization is enforced by Flask; do not assume Supabase RLS handles these sessions.
- Keep .env, instance/, databases, secret_key and .venv out of Git.
- Never delete/reset databases for password recovery. Preserve SQLite sources and import into
  an empty PostgreSQL destination only after approval. Source timezone must be explicit.
- Add new SQL as a new migration; never edit an already-applied migration.
- Run backend tests and JS checks after changes. Calculator reference example remains 408190.
