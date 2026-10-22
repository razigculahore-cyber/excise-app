# Excise Fee Estimator

Existing Flask/Jinja vehicle fee calculator with session authentication, admin/staff accounts,
private saved estimates and audit history. The fee engine remains in frontend/static/js/estimator.js.
Persistence now supports Supabase PostgreSQL through the server-side psycopg driver.

See [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for environment variables, dashboard actions,
uv installation, reviewed schema migration and SQLite import commands, testing and deployment.

```powershell
uv venv .venv
uv pip sync --python .venv/Scripts/python.exe requirements.lock
Copy-Item .env.example .env
# Configure DATABASE_URL and SECRET_KEY privately, review/apply migrations as documented.
uv run --no-project --python .venv/Scripts/python.exe run.py
```

Open http://127.0.0.1:5000. Existing python app.py compatibility is retained.
New databases use /setup for the initial administrator; restrict deployment access during setup.
No account or schema is created automatically in PostgreSQL. Signup defaults off.

Staff can calculate fees, manage their own saved estimates and change their password.
Admins additionally manage accounts and view activity. Passwords use Werkzeug hashes;
five invalid attempts lock a username/IP pair for fifteen minutes.

Terminal account creation (authorized operators only, prompts for password):

```powershell
uv run --no-project --python .venv/Scripts/python.exe flask --app run create-user USERNAME --name "Full Name"
```

Add --admin only when creation is approved. Never delete the database to recover access.
The existing instance/users.db and secret_key remain private and excluded from Git.

```powershell
uv run --no-project --python .venv/Scripts/python.exe pytest
```

Tests use temporary data; real PostgreSQL validation requires a separate local test database.
See setup documentation for the opt-in --postgres mode and safety restrictions.
