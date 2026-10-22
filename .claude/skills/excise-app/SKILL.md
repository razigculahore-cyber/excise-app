---
name: excise-app
description: Run, test, and change the Excise Fee Estimator, a Flask + PostgreSQL (Neon) web app deployed on Vercel, with one Super Admin, admins and users, saved estimates, and a browser-side vehicle fee engine. Use when asked to start or run the app, create or reset a login, change roles or permissions, add a page, route or API endpoint, change a fee rule or tax slab, migrate data, or debug sign-in, CSRF or saved-estimate problems in this repository.
---

# Excise Fee Estimator

A login-protected web app that estimates vehicle registration, transfer and tax fees
(Excise & Taxation). Every person has their own account; estimates they save are private to them.
One Super Admin manages roles and can see everyone's data; admins manage normal users only.

## Architecture

```
app.py / run.py             entry points (Vercel loads app.py -> run.app -> backend.create_app())
backend/                    Flask, server side
  __init__.py               create_app(), ProxyFix, error pages, CLI: init-db, create-superadmin,
                            create-user, set-password, migrate-sqlite
  config.py                 settings from env vars; APP_ENV=production (auto on Vercel) requires
                            SECRET_KEY and never writes files
  db.py                     psycopg 3 connection per request (autocommit, PgBouncer-safe),
                            SCHEMA (Postgres), init_db(); rows come back as dicts with timestamps
                            converted to APP_TIMEZONE text 'YYYY-MM-DD HH:MM:SS'
  permissions.py            ROLES (user/admin/superadmin) and can(actor, action, target)
  security.py               CSRF, headers/CSP/HSTS, start_session(), session_version check,
                            login_required / admin_required / superadmin_required / api_login_required
  migrate.py                one-time SQLite -> Postgres copy (read-only source, one transaction)
  services/                 ALL SQL lives here
    users.py                accounts, roles, password hashing, lockout, create_superadmin()
    estimates.py            saved estimates: clean() + queries scoped by user_id; list_all/get_any
                            are Super Admin read-only
    audit.py                activity log, labels, filters
  routes/                   thin blueprints: parse request -> check -> call service -> render/JSON
    auth.py   /login /signup /logout /account          (no /setup: it was removed on purpose)
    main.py   /  (calculator)  /estimates  /estimates/<id>/delete
    admin.py  /admin/users  /admin/users/add  /admin/users/<id>/<action>          (admin+)
              /admin/users/<id>  /admin/estimates[/<id>]  /admin/activity           (Super Admin)
    api.py    /api/health  /api/me  /api/estimates [GET, POST]  /api/estimates/<id> [DELETE]
frontend/templates/         Jinja pages; admin/_actions.html renders buttons via can()
public/static/              css/app.css (design tokens light/dark) and js/ (app.js, estimator.js);
                            served at /static by Flask locally and by Vercel's CDN in production
tests/                      pytest against TEST_DATABASE_URL in a throwaway schema
```

## Run it (Windows)

```powershell
uv sync                                    # Python 3.12 + locked packages into .venv
uv run flask --app run init-db             # create tables (explicit; never at startup)
uv run python run.py                       # http://127.0.0.1:5000
```

Needs `.env` (copy `.env.example`) with the Neon **dev** branch strings. Never put the production
string in `.env`. Confirm the server with `GET /api/health` -> `{"status":"ok"}`.

## Logins and roles

- Super Admin: `uv run flask --app run create-superadmin USERNAME` (only when none exists) or the
  migration `migrate-sqlite --superadmin USERNAME`. The database enforces one Super Admin and blocks
  deleting, demoting or disabling it (unique partial index, trigger, CHECK).
- Other accounts: sign-up (always `user`), Admin -> Users, or `create-user USERNAME [--admin]`.
- Forgotten password, including the Super Admin: `uv run flask --app run set-password USERNAME`.
- Never put passwords on the command line or in files; the commands prompt for them.

## Test

```powershell
uv run pytest            # needs TEST_DATABASE_URL (direct, non-pooled dev branch string)
uv run ruff check .
```

`tests/test_calculator.py` runs the reference estimate through Node (`408190`) and checks the hash
of `estimator.js`. If you change a fee rule on purpose, update that hash in the same commit.
Fixtures: `boss` (Super Admin, password `adminpass1`), `make_user(name, role=...)`, `make_browser()`.

## How to change things

**Change a fee rule or tax slab**: edit the pure functions at the top of `public/static/js/estimator.js`
(`mvtRateForFY`, `registrationFee`, `transferFee`, ...). Keep them DOM-free. New line items need an entry
in `LABELS` and in `amounts` inside `compute()`.

**Add a page**: route in the right blueprint with `@login_required`, `@admin_required` or
`@superadmin_required`; for per-account actions also check `can()` in the route. Template extends
`app/base.html`; add a `navlink(...)` guarded by `is_admin(user)` / `is_superadmin(user)`.

**Add a permission**: add the action to `permissions.can()` first, use it in the route (403 when
false) and in the template, and add a test for every role in `tests/test_roles.py`.

**Change the schema**: edit `db.SCHEMA` with `IF NOT EXISTS` / guarded `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS`, bump `SCHEMA_VERSION`, and run `init-db` on dev, then production. Live data exists in Neon:
never drop or recreate tables.

## Rules that must hold

- Every state-changing request needs CSRF: the form field `csrf` or the header `X-CSRF-Token`.
- The CSP forbids inline scripts and `on*=` attributes. Use `data-*` hooks handled in `app.js`.
- Every estimate query for normal pages filters by `user_id = g.user["id"]`. Only the Super Admin
  pages use `estimates.list_all/get_any`, and they are read-only.
- Permissions are enforced on the server with `can()` / the guards; hiding a button is never enough.
- Nothing on the website may create a Super Admin or set a role from request data.
- SQL uses `%s` placeholders only; build identifiers with `psycopg.sql`, never f-strings of input.
- Never log or print passwords, hashes, `SECRET_KEY` or connection strings.
- Tests never point at production; `instance/`, `.env*`, `.venv/` and `*.db` stay out of Git.
