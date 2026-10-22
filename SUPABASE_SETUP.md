# Supabase PostgreSQL setup

The existing Flask sessions, Werkzeug hashes, CSRF checks, admin/staff authorization,
saved-estimate ownership and browser fee engine are preserved. Supabase Auth is not used.
The backend connects with psycopg; no database credentials reach the browser.

## Install and configure

Use Python 3.10+ and uv. From the repository root:

```powershell
uv venv .venv
uv pip sync --python .venv/Scripts/python.exe requirements.lock
Copy-Item .env.example .env
```

Edit `.env` privately:

- `DATABASE_URL`: PostgreSQL URI from Supabase **Connect**. Choose **Session pooler**
  (port 5432) for persistent IPv4-only hosting, or Direct connection when IPv6 is available.
  Percent-encode password characters in the URI. Include `sslmode=require`, or preferably
  `sslmode=verify-full&sslrootcert=PATH` with the downloaded CA certificate.
- `SECRET_KEY`: stable random deployment secret. To retain current sessions, use the existing
  `instance/secret_key` value privately. Otherwise set a new cryptographically random secret.
  Local development retains the existing generated secret-file fallback.
- `HTTPS=0` locally; `HTTPS=1` behind production HTTPS.
- `ALLOW_SIGNUP=0` unless public staff registration is intended.
- `APP_TIMEZONE=Asia/Karachi`: presentation timezone. PostgreSQL stores UTC instants.

Environment variables override `.env`. Missing DATABASE_URL fails explicitly rather than
silently opening SQLite. For intentional legacy local operation only, set DATABASE_BACKEND=sqlite
and leave DATABASE_URL empty. Existing instance/users.db is never automatically imported or deleted.

## Dashboard and deployment actions

1. Obtain the correct Session Pooler or Direct URI from your own project's Connect panel.
2. Review `migrations/001_initial.sql` and authorize schema writes before applying.
3. Enforce SSL and limit network access to your backend where practical.
4. Use a dedicated least-privilege backend login for runtime; use an owner/migration login
   only for migrations/imports. Runtime needs schema USAGE, SELECT/INSERT/UPDATE/DELETE
   on the four application tables, and USAGE/SELECT on their identity sequences. It does
   not need schema CREATE, Supabase API keys, or service-role keys.
5. The migration revokes table and identity-sequence access from Supabase anon/authenticated
   roles. Do not grant those roles access to password hashes or these private tables.
   Flask enforces ownership for direct SQL connections; privileged SQL roles bypass RLS.
   RLS policies tied to Supabase Auth are not introduced because this app uses Flask sessions.
6. Protect initial `/setup` with private deployment access until the owner creates the first
   administrator. Setup serializes database access and closes once any user exists.
7. Run behind a production WSGI server and HTTPS proxy; limit worker concurrency to your
   database connection capacity. Each Flask request holds at most one connection, which is
   rolled back and closed at teardown. Queries have a 15-second statement timeout and
   connections a 10-second timeout. No application connection pool is added.

## Schema migrations

App startup never applies PostgreSQL DDL. Versioned migrations are atomic, advisory-locked,
checksum-verified and skipped on rerun. They add only the four application tables plus
`excise_schema_migrations` metadata. Existing incompatible PostgreSQL tables cause rollback;
they are never replaced. Identity IDs, case-insensitive username index, JSONB estimate fields,
unconstrained NUMERIC totals and TIMESTAMPTZ timestamps preserve application behavior.
The audit user ID intentionally has no foreign key so history survives account deletion.
Failed login timestamps remain Unix epoch seconds for the existing lockout rules.

```powershell
# Review files without contacting a database:
uv run --no-project --python .venv/Scripts/python.exe flask --app run db-migrate
# Only after approving writes to the configured destination:
uv run --no-project --python .venv/Scripts/python.exe flask --app run db-migrate --confirm-write
uv run --no-project --python .venv/Scripts/python.exe run.py
```

`GET /api/health` returns the existing {"status":"ok"} after a SELECT 1, or sanitized
HTTP 503 on failure. Readiness does not check every table: apply migrations before serving traffic.

## Existing SQLite data

Stop application writers and retain a backup of the original database (including a consistent
SQLite backup if WAL is in use). The importer opens a read-only transaction and never changes
SQLite. Specify the timezone of the old server because its timestamps used local wall time.

```powershell
uv run --no-project --python .venv/Scripts/python.exe flask --app run db-import-sqlite instance/users.db --source-timezone Asia/Karachi --dry-run
# Requires explicit approval, including approval to import preserved production accounts:
uv run --no-project --python .venv/Scripts/python.exe flask --app run db-import-sqlite instance/users.db --source-timezone Asia/Karachi --confirm-write
```

Import defaults to dry run; no destination connection is made. Writing requires an empty,
already-migrated destination. IDs, hashes, ownership, logs and lockout rows are preserved.
JSON and timestamps are converted, foreign keys and counts checked, and identity sequences
restarted transactionally. A populated destination or conflict aborts the whole import;
repeating a successful import fails safely rather than duplicating rows. No merge/overwrite
mode exists. Reconcile an occupied destination separately with approval. Keep the source
backup after migration. Never delete databases to recover passwords; use an authorized
administrator's reset action or the existing terminal account-management workflow.

## Testing

```powershell
uv run --no-project --python .venv/Scripts/python.exe pytest
node --check frontend/static/js/estimator.js
```

Default tests always use temporary SQLite, even if DATABASE_URL points at production. Offline
adapter tests exercise binding, TLS configuration, sanitized failures, rollback and conversion.
They cannot prove live PostgreSQL connectivity or SQL execution. For full backend tests on a
separate disposable LOCAL PostgreSQL database (name must end `_test`), privately configure
TEST_DATABASE_URL, then:

```powershell
uv run --no-project --python .venv/Scripts/python.exe pytest --postgres
```

This mode refuses remote hosts and creates a unique schema per fixture, applies migrations
twice, runs application behavior through psycopg, then drops only that isolated test schema.
The local test connection can omit TLS; production connections always require TLS.
Never point tests at production. A localhost SSH tunnel to production is also prohibited.

## Troubleshooting

- Missing DATABASE_URL: edit private .env or deployment environment; no SQLite fallback occurs.
- DNS/IPv6 failures: use the dashboard's IPv4 Session Pooler URI.
- Authentication failures: verify database password, pooler username including project suffix,
  and URI encoding. Do not paste secrets into logs or support reports.
- TLS failures: verify CA path/hostname for verify-full; do not disable SSL.
- Missing tables: run the reviewed migration with the migration owner credentials.
- Occupied destination: importer deliberately refuses to overwrite or merge data.
- Password recovery: ask an existing authorized admin to reset the password. Preserve all data.

References: [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
