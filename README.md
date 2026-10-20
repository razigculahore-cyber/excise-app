# Excise Fee Estimator

A web app that estimates vehicle registration, transfer and tax fees. Everyone signs in with
their own account, and the estimates they save are private to them. One **Super Admin** runs the
site: they manage accounts, decide who is an admin, and can see everyone's estimates and activity.

- **Stack:** Flask and Jinja templates. The fee calculations run in the browser (`estimator.js`).
- **Data:** stored in PostgreSQL on [Neon](https://neon.tech).
- **Hosting:** built to run on [Vercel](https://vercel.com).
- **Tooling:** [uv](https://docs.astral.sh/uv/) manages Python and the packages.

Passwords are stored hashed, never as plain text. An account locks for 15 minutes after 5 wrong
attempts. Changing a password, role or account status signs that account out everywhere.

## Who can do what

| | User | Admin | Super Admin |
|---|---|---|---|
| Calculator; save, open and delete **own** estimates; change own password | ✅ | ✅ | ✅ |
| See the list of users | | ✅ | ✅ |
| Add a normal user; set a password for, disable or enable a **normal user** | | ✅ | ✅ |
| Add an admin; manage admins; delete accounts | | | ✅ |
| Make someone an admin, or remove admin rights | | | ✅ |
| See **everyone's** estimates (view only), user profiles, activity and sign-in history | | | ✅ |

- **Registration:** anyone with the link can sign up. They get a normal **User** account and are
  signed in straight away. Nothing in the sign-up form or the API can choose a role.
- **Admins** never see sign-in history, IP addresses, the activity log or other people's estimates.
- **There is exactly one Super Admin.** The database itself refuses a second one, and refuses to
  delete, demote or disable it.
- **The Super Admin can't be created from the website.** It comes only from the migration or the
  terminal command below.
- The Super Admin can **view** other users' estimates but not delete them. Only the owner can.

## Set up on your computer (Windows)

1. Install uv (one time): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. In this folder, install Python 3.12 and every package (one time, and after each `git pull`):

       uv sync

3. Create the Neon database (see the next section) and copy `.env.example` to `.env`. Fill in the
   **dev** branch connection strings. `.env` is never committed.
4. Create the tables, then start the app:

       uv run flask --app run init-db
       uv run python run.py

5. Open **http://127.0.0.1:5000**.

To let other computers in the office use it: `$env:HOST="0.0.0.0"; uv run python run.py`

## Neon (the database)

1. At **console.neon.tech**, create a project called `excise-app` in the **AWS Asia Pacific
   (Singapore)** region. Vercel's function region in `vercel.json` (`sin1`) is the same, which keeps
   pages fast.
2. The project's default branch (`production` or `main`) is the **live database**. Its
   connection string goes only into Vercel.
3. Create a second branch called `dev`. Your computer and the automated tests use this one.
4. On the project page, click **Connect**, choose a branch, and copy:
   - with **Connection pooling on**: the pooled string → `DATABASE_URL`
   - with **Connection pooling off**: the direct string → `DATABASE_URL_UNPOOLED`, and for `dev`
     also `TEST_DATABASE_URL`

Tables are created **only** by `uv run flask --app run init-db`, never when the app starts.
Running it again is safe: it only adds what's missing and never deletes data.

## The Super Admin

**Moving from the old version (the SQLite file `instance/users.db`):**

The migration copies all accounts, password hashes, estimates and activity, keeping their IDs.
Your existing admin becomes the Super Admin, and everyone keeps their current password.

    # 1. Rehearse against the dev branch: does the whole copy and every check, then undoes it
    uv run flask --app run migrate-sqlite --superadmin YOUR_USERNAME --dry-run

    # 2. Copy for real (asks you to type the target host to confirm)
    uv run flask --app run migrate-sqlite --superadmin YOUR_USERNAME --check-login

- `--check-login` asks for your password and confirms it still works on the copied account.
- To copy into the production branch, put its direct connection string in a temporary variable
  and pass the variable's **name** with `--target PRODUCTION_DATABASE_URL`. Never paste the string
  itself into the command.
- The migration opens `instance/users.db` read-only and never changes it. It refuses to write to a
  database that already has accounts, estimates or activity. Everything is copied in one step: it
  all lands, or none of it does.

**Starting fresh instead** (prompts for the password; works only while no Super Admin exists):

    uv run flask --app run create-superadmin YOUR_USERNAME --name "Your Name"

**Other terminal commands:**

    uv run flask --app run create-user USERNAME --name "Full Name" [--admin]
    uv run flask --app run set-password USERNAME     # e.g. if the Super Admin forgets their password

To point any of these at the production database, run them with `DATABASE_URL` set to the
production connection string in that terminal only.

## Tests

    uv sync
    uv run pytest
    uv run ruff check .

- The tests need `TEST_DATABASE_URL`: the direct (non-pooled) string of the Neon `dev` branch.
- Each run creates its own throwaway schema there and drops it at the end, so dev data is never
  touched.
- The tests refuse to run if `TEST_DATABASE_URL` matches `PRODUCTION_DATABASE_URL`.
- They cover registration, every role permission, attempts to get admin rights, session sign-out,
  privacy between users, the migration, production settings, and the calculator. The calculator
  test checks the reference estimate still totals Rs 408,190.

## Deploying on Vercel

The repository is ready for Vercel's zero-configuration Flask support:

- **Packages:** Vercel reads `pyproject.toml` and `uv.lock`.
- **Python version:** comes from `.python-version` (3.12).
- **Entry point:** the app loads from `app.py`.
- **Static files:** `public/` is served from Vercel's CDN.
- **`vercel.json`:** sets the Singapore region and keeps tests and static files out of the function
  bundle.

In **Project → Settings → Environment Variables**, set these for the **Production** environment:

| Name | Value |
|---|---|
| `DATABASE_URL` | Neon **production** branch, pooled connection string |
| `SECRET_KEY` | A long random value: `uv run python -c "import secrets; print(secrets.token_hex(32))"` |
| `APP_ENV` | `production` |
| `HTTPS` | `1` |
| `TRUST_PROXY` | `1` |
| `ALLOW_SIGNUP` | `1` |
| `APP_TIMEZONE` | `Asia/Karachi` |

- For the **Preview** environment, use the Neon **dev** branch's `DATABASE_URL` and a *different*
  `SECRET_KEY`, so test deployments never touch live data.
- `TEST_DATABASE_URL` and `DATABASE_URL_UNPOOLED` are not needed on Vercel.
- If `SECRET_KEY` is missing, the app refuses to start in production. The same goes for
  `DATABASE_URL`.

**Order of work:**

1. Create the Neon project.
2. Run `init-db` and the migration (or `create-superadmin`) against the production branch from
   your computer.
3. Set the variables above.
4. Deploy.

## Project layout

| Path | What it does |
|---|---|
| `app.py`, `run.py` | Entry points (Vercel loads `app.py`; locally `uv run python run.py`) |
| `backend/permissions.py` | The roles and `can()`: the single place that decides who may do what |
| `backend/` | Settings, database (`db.py`), security, migration, `services/` (all SQL), `routes/` (pages and JSON API) |
| `frontend/templates/` | Pages: `auth/` (sign-in), `app/` (calculator, saved estimates), `admin/` |
| `public/static/css/app.css` | The one stylesheet (light and dark themes) |
| `public/static/js/estimator.js` | All the fee calculations, plus the calculator page |
| `tests/` | Automated tests (`uv run pytest`) |
| `pyproject.toml`, `uv.lock` | Python version and packages, pinned for repeatable installs |
| `vercel.json` | Vercel region and bundle settings |
| `.claude/skills/excise-app/SKILL.md` | Guide for AI coding assistants: architecture, commands and rules |
| `instance/` | Only the old SQLite database and the local secret key. Keep it safe; never share it. |
