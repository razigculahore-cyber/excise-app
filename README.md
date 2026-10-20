# Excise Fee Estimator

A web app that estimates vehicle registration, transfer and tax fees. Everyone signs in with
their own account. Estimates you save are visible only to you. Admins manage accounts and can
see sign-in activity.

Passwords are stored hashed, never as plain text. An account locks for 15 minutes after
5 wrong attempts.

## Run it on your computer (Windows)

1. Install Python 3.10 or newer from python.org (tick "Add Python to PATH").
2. Open PowerShell in this folder and set up the app (one time only):

       python -m venv .venv
       .venv\Scripts\python -m pip install -r requirements.txt

3. Start the app:

       .venv\Scripts\python run.py

4. Open **http://127.0.0.1:5000** in your browser.
5. On a brand-new install you'll be asked to create the **admin** account first.

Keep the PowerShell window open while you use the app. Press `Ctrl + C` to stop it.
`python app.py` also still works.

## Accounts

| Who | What they can do |
|---|---|
| **Staff** | Use the calculator; save, reopen and delete their own estimates; change their password |
| **Admin** | All of the above, plus **Users** (add, reset password, disable, delete) and **Activity** (sign-in log) |

Ways to create an account:

- **Admin → Users → Add a user.** Give the person their password in person.
- **Sign-up page.** It always creates a staff account. To turn sign-up off, start the app with
  `$env:ALLOW_SIGNUP="0"; .venv\Scripts\python run.py`.
- **From the terminal.** This asks for the password:

      .venv\Scripts\flask --app run create-user USERNAME --name "Full Name"          # staff
      .venv\Scripts\flask --app run create-user USERNAME --name "Full Name" --admin  # admin

Every user can change their password under **Account & password** in the top-right menu.

## Letting other computers in the office use it

    $env:HOST="0.0.0.0"; .venv\Scripts\python run.py

Others on the same network then open `http://YOUR-PC-IP:5000` (find your IP with `ipconfig`).
Windows Firewall may ask for permission.

## Putting it online

Flask's built-in server is for office or personal use. To publish it on the internet, host it on a
service such as PythonAnywhere or Render, serve it over **https**, and set `HTTPS=1` so the login
cookie is only sent securely.

## Project layout

| Path | What it does |
|---|---|
| `run.py` | Starts the app |
| `backend/` | Server: settings, database, security, `services/` (all data access), `routes/` (pages and JSON API) |
| `frontend/templates/` | Pages: `auth/` (sign-in), `app/` (calculator, saved estimates), `admin/` |
| `frontend/static/css/app.css` | The one stylesheet (light and dark themes) |
| `frontend/static/js/estimator.js` | All the fee calculations, plus the calculator page |
| `tests/` | Automated tests: `.venv\Scripts\python -m pip install -r requirements-dev.txt`, then `.venv\Scripts\python -m pytest` |
| `.claude/skills/excise-app/SKILL.md` | Guide for AI coding assistants: architecture, commands and rules |
| `instance/` | The user database and secret key. Back it up; never share it. |

If you forget the admin password and no other admin exists, stop the app, back up and then delete
`instance/users.db`, and start again. You'll be asked to create a new admin. This removes all
accounts and saved estimates.
