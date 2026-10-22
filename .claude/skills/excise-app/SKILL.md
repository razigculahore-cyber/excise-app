---
name: excise-app
description: Maintain the Flask/Supabase PostgreSQL Excise Fee Estimator with Super Admin/Admin/User permissions, sessions, private estimates and the existing browser fee engine.
---

# Excise Fee Estimator

Read README.md and SUPABASE_SETUP.md. Use uv and preserve the existing application.
Python 3.12 is pinned; pyproject.toml and uv.lock are the dependency source of truth.

## Architecture

- run.py is the local entrypoint; app.py and vercel.json preserve Vercel deployment.
- backend/__init__.py creates Flask, ProxyFix, CLI, security guards and safe error handlers.
- config.py loads private .env without overriding environment; production requires a strong key.
- db.py owns request-scoped psycopg connections with mandatory TLS, UTC, timeouts and cleanup.
  Single statements autocommit; transaction() groups multi-statement work and owns rollback.
- permissions.py owns role/can checks. security.py owns CSRF, CSP and session-version checks.
- services/users.py preserves Werkzeug hashes, roles, account state and case-insensitive lockout.
- services/estimates.py uses JSONB and numeric totals; normal queries filter by owner ID.
- migrations.py and migrations/*.sql own explicit checksum/versioned transactional upgrades.
  Existing complete main-branch PostgreSQL schemas are adopted without replacing tables.
- migrate.py keeps the older migrate-sqlite command, delegating writes to the safe importer.
- routes are thin; templates use guards to show controls, but permissions are enforced server-side.
- frontend/templates are retained; public/static contains CSS, app.js and estimator.js for Vercel.
- tests use an offline SQLite double by default. --postgres requires an isolated LOCAL test DB.

## Commands

```powershell
uv sync
uv run python run.py
uv run pytest
uv run pytest --postgres
node --check public/static/js/estimator.js
```

Configure DATABASE_URL and SECRET_KEY privately. HTTPS=1 and APP_ENV=production for hosting;
ALLOW_SIGNUP defaults 0. DATABASE_URL_UNPOOLED optionally selects a direct migration connection.
No public /setup page exists. Only approved operators may run create-superadmin, create-user
or set-password; passwords are prompted. Never modify production users without approval.

`db-migrate` and `init-db` preview without writes; applying requires --confirm-write.
`db-import-sqlite SOURCE --source-timezone ZONE` defaults to source-only validation and never
contacts a destination without --confirm-write. --superadmin explicitly promotes a chosen
existing active source admin. The old migrate-sqlite command confirms the destination host.
Preserve all source files and require an empty migrated destination. Never reset databases.

## Invariants

- Preserve Flask sessions, Werkzeug hashes, CSRF, CSP, secure cookies and session invalidation.
- User and Admin access follow permissions.can(); only Super Admin can read others' estimates.
  Super Admin inspection pages are read-only. Ordinary queries always filter by user_id.
- Exactly one Super Admin at most, enforced by unique index; deletion/demotion/disable is blocked.
  No website or untrusted role field can create or grant Super Admin access.
- Signup creates User only and is disabled by default.
- Use bound values (%s) and psycopg.sql for identifiers. Never expose/log credentials or hashes.
- UTC storage, APP_TIMEZONE presentation. Keep existing timestamp string/API number contracts.
- Supabase anon/authenticated roles must not access these private application tables.
  Direct SQL access control is enforced by Flask, not assumed Supabase Auth/RLS policies.
- Add new migrations; never edit an already-applied migration or automatically migrate at startup.
- Keep .env, instance/, database files, virtual environments and secret keys out of Git.
- Never connect default tests to production. --postgres accepts local database names ending _test
  and drops only unique test schemas; never use a production tunnel as that localhost endpoint.
- Run tests and calculator checks after changes. Calculator reference remains 408190 and its
  original file hash is checked by tests/test_calculator.py. Change fee rules only when requested.
- No automatic commits or pushes. Production schema writes/account changes require approval.
