# Implementation report: Supabase PostgreSQL integration

## Outcome and repository audit

Work is on `feature/supabase-postgres`, created before file edits. The initial working tree
was clean. No commits or pushes were made. Existing Flask architecture and fee calculator
were retained; no frontend files changed.

Inspected the repository skill, routes, authentication/session/CSRF guards, service queries,
schema, configuration, tests and frontend persistence contracts. SQLite-specific behavior
included question-mark placeholders, sqlite3.Row and IntegrityError, lastrowid, NOCASE,
local datetime defaults, text JSON, PRAGMA and startup schema creation.

Read the existing instance/users.db in SQLite read-only mode before changing application
files. All four tables existed with these counts: users 0, estimates 0, audit_log 0,
failed_logins 0. The original database and secret_key were preserved. No production
connection, schema changes, imports or user creation were attempted.

## Created files

- `.env.example`: private environment configuration template.
- `backend/migrations.py`: explicit migration and safe SQLite import CLI commands.
- `migrations/001_initial.sql`: four PostgreSQL tables, identity keys, constraints,
  indexes, JSONB, numeric totals, UTC timestamps and Supabase API-role access revocation.
- `requirements.lock`: dependency versions compiled with uv.
- `tests/test_database.py`: adapter, configuration, security/failure and migration/import checks.
- `SUPABASE_SETUP.md`: full setup, approval boundaries, operation and troubleshooting guide.
- `IMPLEMENTATION_REPORT.md`: this report.

## Modified files

- `backend/db.py`: request-scoped psycopg adapter; TLS required, 10-second connection timeout,
  15-second statement timeout, UTC session, bound parameters, explicit commit/rollback,
  cleanup, safe connection errors; retained explicit local SQLite support.
- `backend/config.py`: DATABASE_URL, explicit local backend selection, APP_TIMEZONE,
  dotenv support, signup off by default; existing persistent secret fallback preserved.
- `backend/__init__.py`: no automatic PostgreSQL schema writes, missing-URL validation,
  isolated testing defaults, CLI registration and sanitized HTTP 503 responses.
- `backend/services/users.py`: PostgreSQL insert IDs and duplicate handling, case-insensitive
  lookups/lockout and serialized first-admin initialization.
- `backend/services/estimates.py`: JSONB adaptation, numeric/API compatibility and owner-row
  locking to serialize per-user save-limit enforcement.
- `backend/routes/auth.py`: first-admin atomic recheck.
- `backend/routes/admin.py`: serialize account mutation checks to retain an active admin.
- `backend/routes/api.py`: database-backed health check while preserving success JSON.
- `tests/conftest.py`: isolated defaults and opt-in local PostgreSQL test schemas.
- `requirements.txt`, `.gitignore`, `README.md`, `.claude/skills/excise-app/SKILL.md`:
  dependencies, secret exclusions and actual operational instructions.

## Dependencies and verification

Used uv with the existing virtual environment. New runtime dependencies: psycopg[binary]
3.3.6, python-dotenv 1.2.4, tzdata 2026.5. Installed pytest 9.1.1 and its support packages.
Existing Flask/Werkzeug authentication remains in use; no SQLAlchemy, Alembic or Supabase SDK.

Offline pytest suite: **37 passed, 2 skipped**. Skips explicitly require local PostgreSQL
for actual import/identity integrity and migration checksum validation. Existing auth,
CSRF, role checks, private estimates and frontend/API tests pass. Additional checks cover
TLS configuration, bound values, credential-safe failures, rollback, case-insensitive lockout,
duplicate recovery, setup recheck, timestamp/JSON conversion, read-only source handling,
CLI no-write defaults, password reset and activation.

JavaScript syntax check passed. The unchanged calculator reference result is **408190**.
Git diff whitespace check passed. No frontend diff exists.

Actual PostgreSQL migrations, live transactions/imports and Supabase connectivity remain
unverified. PostgreSQL binaries are absent and Docker's engine is not running. The opt-in
`pytest --postgres` suite applies migrations twice in unique test schemas and runs backend
behavior against psycopg. It requires a local disposable TEST_DATABASE_URL ending `_test`;
it rejects remote hosts. See setup guide. Offline mocks do not substitute for these checks.

## Schema, import and security review

Version/checksum metadata is stored in excise_schema_migrations. Migrations are transactional,
serialized by advisory lock and non-destructive. Existing incompatible tables fail closed.
Application startup does not migrate PostgreSQL. Import opens SQLite read-only, requires an
explicit source timezone, validates relationships, preserves IDs/hashes/data/logs, checks row
counts and restarts identity sequences transactionally. It only writes to an empty migrated
destination after --confirm-write. Conflicts/reruns abort without duplicates or overwrites.

No credentials were printed or written to tracked files. DATABASE_URL is server-only; TLS
cannot be disabled on runtime PostgreSQL connections. Flask authorization, Werkzeug hashing,
CSRF, cookie configuration, ownership filtering and audit retention remain. No Supabase Auth
or service-role API access was added. SQL API roles are denied application-table access;
use a dedicated least-privilege runtime role and a separate owner for migrations. Direct SQL
access is governed by Flask, not implicit Supabase RLS. Limit worker concurrency to database
capacity. Protect /setup until the owner initializes the first admin.

## Remaining setup and approval boundaries

Configure privately: DATABASE_URL, SECRET_KEY, HTTPS (1 for production), ALLOW_SIGNUP
(normally 0); APP_TIMEZONE defaults to Asia/Karachi. No Supabase credentials were available
in the environment, and no remote connection was attempted.

In Supabase Connect, obtain the Session Pooler URI for IPv4 (port 5432), or direct URI for
supported networking. Configure TLS, network restrictions and dedicated runtime credentials.
Review SQL and approve production schema writes before running db-migrate --confirm-write.
Approve any production account import or first-admin creation separately. An import is not
needed for the inspected empty database. Run live tests against a separate local PostgreSQL
test database before deployment, then verify authorized deployment health/login/estimates.

Local commands, migration previews, import dry runs and deployment details are in
SUPABASE_SETUP.md. Missing credentials do not prevent reviewing the completed code and SQL.
All changes remain uncommitted. Suggested commit message:
`Add Supabase PostgreSQL persistence and safe SQLite migration tooling`.
