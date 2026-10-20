---
name: excise-app
description: Run, test, and change the Excise Fee Estimator, a Flask web app with per-user logins, an admin console, saved estimates, and a browser-side vehicle fee engine. Use when asked to start or run the app, create or reset a login, add a page, route or API endpoint, change a fee rule or tax slab, or debug sign-in, CSRF or saved-estimate problems in this repository.
---

# Excise Fee Estimator

A login-protected web app that estimates vehicle registration, transfer and tax fees
(Excise & Taxation). Every person has their own account; estimates they save are private to them.
Admins manage accounts and can see sign-in activity.

## Architecture

```
run.py                      entry point (python run.py); app.py is a thin compatibility shim
backend/                    Flask, server side
  __init__.py               create_app() factory, error pages, `flask create-user` command
  config.py                 settings from env vars (HOST, PORT, HTTPS, ALLOW_SIGNUP, SECRET_KEY)
  db.py                     SQLite connection per request + schema (CREATE TABLE IF NOT EXISTS)
  security.py               CSRF, security headers/CSP, login_required / admin_required / api_login_required
  services/                 ALL SQL lives here
    users.py                accounts, password hashing, failed-login lockout
    estimates.py            saved estimates: validation (clean) + queries scoped by user_id
    audit.py                activity log + human labels for events
  routes/                   thin blueprints: parse request -> call service -> render/redirect/JSON
    auth.py   /setup /login /signup /logout /account
    main.py   /  (calculator)  /estimates  /estimates/<id>/delete
    admin.py  /admin/users  /admin/users/add  /admin/users/<id>/<action>  /admin/activity
    api.py    /api/health  /api/me  /api/estimates [GET, POST]  /api/estimates/<id> [DELETE]
frontend/                   browser side
  templates/base.html       <head>, fonts, CSRF meta tag, app.js
  templates/auth/           split-screen sign-in pages (extend auth/base.html)
  templates/app/            signed-in pages (extend app/base.html, the shell with nav + user menu)
  templates/admin/          admin pages (also extend app/base.html)
  static/css/app.css        the single design system: tokens (light/dark) -> components -> pages
  static/js/app.js          shared UI: password toggles, data-confirm, toasts, ExciseUI.api()
  static/js/estimator.js    fee engine (pure functions, Node-testable) + calculator UI glue
tests/                      pytest; uses a temp instance dir, never the real database
instance/                   users.db and secret_key (created on first run; never commit or share)
```

Request flow: browser -> blueprint route -> guard (`login_required` etc.) -> service -> SQLite.
The fee calculation runs only in the browser (`estimator.js`); the server stores what the user saves.

## Run it (Windows)

```powershell
# one-time setup
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt

# start (http://127.0.0.1:5000)
.venv\Scripts\python run.py

# office network access
$env:HOST="0.0.0.0"; .venv\Scripts\python run.py
```

macOS/Linux: same commands with `.venv/bin/python`.
Run the server in the background and confirm it's up with `GET /api/health` -> `{"status":"ok"}`.
The first visit to a fresh database redirects to `/setup` to create the admin.

## Logins

- Create from the terminal (prompts for the password; never put passwords in the command line or files):
  `.venv\Scripts\flask --app run create-user USERNAME --name "Full Name" [--admin]`
- Or sign in as an admin and use **Users**: add, set a new password, disable/enable, delete.
- Sign-ups create **staff** accounts only. Set `ALLOW_SIGNUP=0` to make account creation admin-only.
- 5 wrong passwords from one IP lock that username for 15 minutes; an admin's Enable or Set password clears it.
- Locked out with no admin left: stop the app, back up then delete `instance/users.db`, restart, and run setup again.

## Test

```powershell
.venv\Scripts\python -m pytest              # backend: auth, CSRF, admin guards, estimate privacy
node --check frontend/static/js/estimator.js # JS syntax
node -e "console.log(require('./frontend/static/js/estimator.js').compute({txn:'nrt',vehicle:'car',cc:'1300',invoiceValue:'5200000',filer:true,invoiceDate:'2026-07-01',regDate:'2026-10-20'}).total)"
```

The last command prints `408190` for the default example; if a fee change alters it, that change was intended only if you meant to change the rules.
All tests must pass before you finish. Tests use the `Browser` helper in `tests/conftest.py`, which
sends the CSRF token the same way a real page does.

## How to change things

**Change a fee rule or tax slab**: edit the pure functions at the top of `estimator.js`
(`mvtRateForFY`, `registrationFee`, `transferFee`, and so on). Keep them DOM-free. New line items need an
entry in `LABELS` and in `amounts` inside `compute()`. Check with the `node -e` command above.

**Add a page**: add a route to the right blueprint with `@login_required` (or `@admin_required`),
create `frontend/templates/app/<page>.html` extending `app/base.html`, and add a `navlink(...)`
in `app/base.html` if it belongs in the nav. Put styles in `app.css` using the existing tokens.

**Add an API endpoint**: add it to `routes/api.py` with `@api_login_required`; keep SQL in a service.
From the browser call `ExciseUI.api(method, url, body)`, which sends the `X-CSRF-Token` header.

**Change the schema**: add `CREATE TABLE IF NOT EXISTS ...` to `db.SCHEMA`. For new columns on
existing tables, add a guarded `ALTER TABLE` in `init_db` (check `PRAGMA table_info` first), because
users already have a live `users.db`.

## Rules that must hold

- Every state-changing request needs CSRF: the form field `csrf` or the header `X-CSRF-Token`.
- The CSP forbids inline scripts and `on*=` attributes. Use `data-*` hooks handled in `app.js`.
  JSON data for a page goes in `<script type="application/json">` with `|tojson`.
- Every estimate query filters by `user_id = g.user["id"]`. Never look up an estimate by id alone.
- Keep at least one active admin. Users can't disable or delete their own account.
- Passwords are hashed with werkzeug only. Never log, print, or store a plain password.
- `instance/`, `.venv/`, `*.db` and `secret_key` stay out of version control (see `.gitignore`).
- Flask's built-in server is for office use. For internet hosting, put it behind HTTPS and set `HTTPS=1`.
