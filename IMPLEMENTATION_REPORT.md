# Implementation and PR conflict-resolution report

## Current result

Merged origin/main (13901da) into feature/supabase-postgres locally, without creating a merge
commit or pushing. All twelve conflicts were reconciled. The PR can be updated by committing
and pushing this prepared merge. Main's newer application behavior is preserved alongside the
Supabase persistence work. No production database/schema/users were accessed or changed.

## Preserved from main

- Super Admin/Admin/User permissions, server-side can() checks and Super Admin read-only dashboard.
- Protected single Super Admin and terminal-only creation; no public /setup is reintroduced.
- Password hashing, CSRF, session-version invalidation, lockout, secure cookie/HSTS settings,
  production strong-key checks, request size limits and trusted-proxy configuration.
- Vercel entrypoint/configuration and public/static assets, with the original calculator engine.
- Python 3.12 project metadata and uv.lock environment management.

## Supabase reconciliation

- Mandatory TLS, timeouts, UTC storage and timezone/string/API conversion remain.
- Runtime psycopg connections retain main's autocommit behavior for single statements;
  explicit transaction() groups estimate-limit checks/saves, imports and schema changes.
- Health checks query the database and return sanitized 503 errors on failure.
- Signup defaults off. No browser database credentials or Supabase Auth replacement.
- Explicit migrations with checksum/version metadata and advisory locking; no startup DDL.
- New 002_roles_and_existing_postgres.sql upgrades the initial legacy-compatible schema and
  adopts complete existing main-branch PostgreSQL databases without recreating their tables.
  Existing roles, hashes and IDs remain; legacy admins map to Admin with no automatic Super
  Admin promotion. Existing old columns/metadata are retained. JSON/NUMERIC conversion failures
  roll back. Supabase anonymous/authenticated API roles lose access to private tables/sequences.
- db-import-sqlite and existing migrate-sqlite share one atomic importer. Source-only dry runs
  never connect to a destination. Writing requires explicit CLI confirmation, a migrated empty
  destination, row/account verification and transactional identity restart. No overwrite mode.

## Main files changed during conflict resolution

backend/__init__.py, config.py, db.py, migrate.py, migrations.py, routes/auth.py,
routes/admin.py, services/users.py, services/estimates.py; migrations/002_roles_and_existing_postgres.sql;
tests/conftest.py, offline_db.py, test_database.py, test_db.py, test_migration.py;
pyproject.toml, uv.lock, requirements.txt, requirements.lock; .env.example, .gitignore,
README.md, SUPABASE_SETUP.md and the repository SKILL.md.
Main's other templates, role services, tests, public assets and Vercel files are included by merge.

## Verification

- Full offline suite: 115 passed, 5 skipped.
- Skips require real PostgreSQL: schema execution/idempotency, full imports and checksum checks.
- Existing calculator tests verify original engine hash and reference result 408190.
- node --check public/static/js/estimator.js passed.
- Ruff undefined-name/unused-import checks (select F) passed.
- Both SQL migrations parsed with PostgreSQL's grammar through pglast; this validates syntax,
  not live execution, PL/pgSQL behavior, data conversion or permissions.
- No PostgreSQL service is available locally; no live Supabase connection was claimed.

Tests used an isolated uv-managed .venv-merge on Python 3.12 because the original .venv uses
Python 3.13 and was locked when uv tried to align it with main's Python 3.12 pin. Original
interpreter dependencies were restored with uv pip sync. .venv-merge is ignored by Git.
To reproduce with that environment in PowerShell:

    $env:UV_PROJECT_ENVIRONMENT="$PWD\.venv-merge"
    uv run pytest

Or close processes locking the old environment and use uv sync to align the normal .venv
with the project's pinned Python. Neither environment is committed.

## Initial data preservation and remaining steps

The initial read-only SQLite audit found users=0, estimates=0, audit_log=0, failed_logins=0.
The original instance/users.db and secret_key remain untouched; no real data import is needed
for that inspected empty source. No secrets are staged. All tests use temporary data.

Configure DATABASE_URL, SECRET_KEY, HTTPS=1 in production, ALLOW_SIGNUP=0 and optional
DATABASE_URL_UNPOOLED/APP_TIMEZONE privately. Obtain the URI from Supabase Connect, enforce
SSL/network restrictions and use separate least-privilege runtime and migration roles.
Rehearse schema upgrades and imports against a local disposable PostgreSQL database before
approving production writes. pytest --postgres refuses remote hosts and requires the local
database name to end _test, using only unique disposable schemas. Do not tunnel production.

Review SUPABASE_SETUP.md for exact uv, migration, import, account and deployment commands.
Production schema changes and user/import actions still require separate approval.

Suggested merge commit:

    git commit -m "Merge main and reconcile Supabase integration with roles"
    git push origin feature/supabase-postgres

No commit, push, GitHub PR edit, remote merge or production action was executed by the agent.
