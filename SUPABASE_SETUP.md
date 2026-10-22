# Supabase setup and operation

## Environment and uv

Python 3.12 is pinned by .python-version. Use `uv sync` for development and `uv sync --no-dev`
for runtime dependencies. pyproject.toml and uv.lock are the source of truth; requirements
files remain compatibility exports. Copy .env.example to .env privately. Environment values
have priority over dotenv. Configure:

- DATABASE_URL: server-only Supabase PostgreSQL URI, using Session pooler port 5432 for
  persistent IPv4 backends or Direct where networking supports it. Percent-encode passwords.
- DATABASE_URL_UNPOOLED: optional direct migration/import URI; defaults to DATABASE_URL.
- SECRET_KEY: stable random secret; mandatory 32+ characters in production. Preserve the old
  private instance/secret_key value if session continuity is intended.
- HTTPS=0 locally; HTTPS=1 in production. APP_ENV=production (automatic on Vercel) enables
  strong-key validation, secure __Host-session cookies, HSTS and proxy handling defaults.
- ALLOW_SIGNUP=0 unless public User registration is intended.
- APP_TIMEZONE=Asia/Karachi for timestamp presentation; storage is UTC.
- TEST_DATABASE_URL: local disposable PostgreSQL with name ending _test, only for opt-in tests.

Runtime always requires PostgreSQL DATABASE_URL. SQLite is retained only for legacy source
reading and offline test doubles. No production SQLite fallback is selected. All PostgreSQL
runtime connections require sslmode=require, verify-ca or verify-full; weaker modes are refused.
For verify-full obtain the CA certificate from Supabase and configure sslrootcert and hostname.
No browser database connection, Supabase Auth change or service-role key is needed.

## Migrations and existing main-branch databases

```powershell
uv run flask --app run db-migrate
# Review migrations/*.sql and approve the destination before this write command:
uv run flask --app run db-migrate --confirm-write
```

The first command is a file preview with no database connection. `init-db` remains as an alias
with a no-write preview by default and --confirm-write required to apply.
Application startup never applies DDL. Migrations are checksum-versioned, advisory-locked
and atomic. 001_initial.sql creates a fresh legacy-compatible base. 002 adds current roles,
session versions, protected Super Admin, JSONB, numeric totals, indexes and role access controls.
An existing complete main-branch PostgreSQL schema is adopted by recording 001 as a baseline
instead of recreating its tables, then applying 002. A partial/incompatible schema or invalid
JSON fails and rolls back. Existing roles, password hashes, IDs and estimates are retained.
Legacy is_admin administrators map to Admin; no existing user is automatically promoted to
Super Admin. Old is_admin columns are retained. Existing schema_version metadata is retained.

Make a backup and rehearse on a copy before approving production migration. Do not run these
commands against production until authorized. No remote schema migration was run by this task.

## Account access and deployment

Keep the newer main-branch permission model: User, Admin and one protected Super Admin.
Session versions invalidate logins after password/status/role changes. There is no web /setup.
An authorized operator, with separate production approval, may run:

```powershell
uv run flask --app run create-superadmin USERNAME
uv run flask --app run create-user USERNAME
uv run flask --app run set-password USERNAME
```

Passwords are prompted, never command arguments. Existing protected Super Admin accounts
survive migration. Signup can create normal Users only. Super Admin read-only access to other
users' estimates remains guarded server-side; normal estimate queries retain owner filters.

Vercel entrypoint/configuration and public/static assets from main are preserved. Configure
production environment secrets in the hosting dashboard. Limit workers/concurrency to database
capacity. Request-scoped connections close at teardown; single writes use autocommit and
multi-statement estimate/import/migration operations use explicit transactions. Connection
timeout is 10 seconds and query timeout 15 seconds. Session pooler suits persistent backends;
review pooler capacity when using serverless hosting. Trust proxy headers only behind your
configured trusted proxy. Test deployment readiness and authenticated flows before switching users.

In Supabase, enforce SSL and appropriate network restrictions. Use a separate migration owner
and least-privilege runtime login (schema USAGE, table DML, identity sequence USAGE/SELECT).
Runtime needs no schema CREATE privileges or API service-role key. Migrations revoke private
application table/sequence access from anon/authenticated roles. Direct SQL privileges can
bypass RLS: Flask owns authorization; Supabase Auth-based RLS policies were not introduced.
Keep these private tables unavailable to unauthenticated Data API clients.

## SQLite import

Retain a consistent backup and stop source writers during cutover. Source reads use a read-only
SQLite transaction. The target must already be migrated and all four application tables empty.

```powershell
uv run flask --app run db-import-sqlite instance/users.db --source-timezone Asia/Karachi --dry-run
# Only after approving preserved production-account import:
uv run flask --app run db-import-sqlite instance/users.db --source-timezone Asia/Karachi --confirm-write
```

Default behavior is dry-run source validation without contacting a destination. --superadmin
USERNAME explicitly promotes a selected existing active source admin during import; use it only
with approval. Otherwise legacy admins remain Admin and staff become User. Existing IDs, hashes,
logs, ownership, JSON and timestamps are preserved. Counts, foreign keys, and identity restart
are verified in one atomic transaction. Occupied targets, conflicts and reruns fail safely;
no merge, overwrite or deletion mode exists. Sequence restart is transactional.

The old migrate-sqlite command is retained. It requires --superadmin and asks for the destination
hostname before writing. Its --dry-run now validates the source only, without destination writes.
It delegates actual copying to the same empty-destination importer. Schema creation is separate.
Never delete databases for password recovery.

## Tests and limitations

```powershell
uv run pytest
node --check public/static/js/estimator.js
# After configuring a local disposable TEST_DATABASE_URL whose database ends _test:
uv run pytest --postgres
```

Default tests use a SQLite DB-API double to exercise Flask roles, sessions, CSRF, account actions,
estimate privacy, production configuration and failure handling. They never use production
DATABASE_URL. PostgreSQL-specific checks skip by default; the doubles cannot verify PostgreSQL
SQL, JSONB constraints, concurrency or actual connectivity. Opt-in mode refuses remote hosts,
creates a unique local schema per fixture, applies migrations twice, and drops only that schema
at teardown. Never tunnel this localhost endpoint to production. Local test servers may omit TLS;
production runtime code cannot. No production users are created by tests.

GET /api/health executes SELECT 1, preserving {"status":"ok"}; failures yield sanitized 503.
It does not validate all tables: apply migrations before serving traffic.

Missing URL: set private environment variables. IPv6/DNS failure: use dashboard Session pooler.
Authentication error: verify username/project suffix, password encoding and destination privately.
TLS error: fix CA/hostname, never disable TLS. Missing tables: review/apply migrations with owner
credentials. Populated import destination: reconcile separately with approval, never overwrite.

References: [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
and [psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
