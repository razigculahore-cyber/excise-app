"""
Excise Fee Estimator: Flask application factory.

    backend/
      config.py      settings from environment
      db.py          PostgreSQL connection + schema
      security.py    CSRF, headers, login/admin/Super Admin guards
      permissions.py roles and can(): who may do what
      migrate.py     one-time copy of the old SQLite database into PostgreSQL
      services/      users, estimates, audit log (all SQL lives here)
      routes/        auth, main (calculator), admin, api blueprints
    frontend/
      templates/     Jinja pages (auth/, app/, admin/)
      static/        css/ and js/ (the fee engine runs in the browser)
"""
import os

from flask import Flask, g, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config as cfg
from .db import close_db, init_db
from .permissions import ROLE_LABELS, can, is_admin, is_superadmin
from .security import check_csrf, csrf_token, security_headers


def create_app(overrides: dict | None = None, instance_dir: str | None = None) -> Flask:
    instance_dir = instance_dir or cfg.INSTANCE_DIR
    app = Flask(
        __name__,
        instance_path=instance_dir,
        template_folder=os.path.join(cfg.FRONTEND_DIR, "templates"),
        static_folder=os.path.join(cfg.FRONTEND_DIR, "static"),
    )
    app.config.update(cfg.build_config(instance_dir))
    if overrides:
        app.config.update(overrides)
    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DATABASE_URL is not set. Put it in .env (see .env.example) or in the Vercel settings.")
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.teardown_appcontext(close_db)
    app.before_request(check_csrf)
    app.after_request(security_headers)
    app.jinja_env.globals.update(csrf_token=csrf_token, can=can, is_admin=is_admin,
                                 is_superadmin=is_superadmin, role_labels=ROLE_LABELS)

    @app.context_processor
    def inject_user():
        return {"user": g.get("user"), "allow_signup": app.config["ALLOW_SIGNUP"]}

    from .routes import admin, api, auth, main
    for module in (auth, main, admin, api):
        app.register_blueprint(module.bp)

    _register_errors(app)
    _register_commands(app)
    return app


def _register_commands(app: Flask) -> None:
    import click

    from . import migrate
    from .services import audit, users

    def admin_url() -> str:
        # Table changes go over Neon's direct (unpooled) connection when one is configured
        return app.config.get("DATABASE_URL_UNPOOLED") or app.config["DATABASE_URL"]

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create the database tables (safe to re-run; never deletes data)."""
        init_db(admin_url())
        click.echo("Database tables are ready.")

    def check_new_account(username: str, password: str) -> None:
        problem = users.username_problem(username) or users.password_problem(password)
        if problem:
            raise click.ClickException(problem)

    @app.cli.command("create-superadmin")
    @click.argument("username")
    @click.option("--name", default="", help="Full name shown in the app.")
    @click.password_option()
    def create_superadmin(username: str, name: str, password: str) -> None:
        """Create the one Super Admin (prompts for the password). Refuses if one already exists."""
        check_new_account(username, password)
        try:
            uid = users.create_superadmin(username, name, password)
        except users.SuperAdminExists:
            raise click.ClickException("A Super Admin already exists. There can only be one.") from None
        except users.UsernameTaken:
            raise click.ClickException(f"The username {username} is already taken.") from None
        audit.log("setup", users.get(uid), ip="terminal")
        click.echo(f"Created Super Admin '{username}'.")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--name", default="", help="Full name shown in the app.")
    @click.option("--admin", is_flag=True, help="Give the account admin rights.")
    @click.password_option()
    def create_user(username: str, name: str, admin: bool, password: str) -> None:
        """Create a login from the terminal (prompts for the password)."""
        check_new_account(username, password)
        try:
            users.create(username, name, password, role="admin" if admin else "user")
        except users.UsernameTaken:
            raise click.ClickException(f"The username {username} is already taken.") from None
        click.echo(f"Created {'admin' if admin else 'user'} account '{username}'.")

    @app.cli.command("set-password")
    @click.argument("username")
    @click.password_option()
    def set_password(username: str, password: str) -> None:
        """Set a new password for any account, including the Super Admin (signs it out everywhere)."""
        user = users.get_by_username(username)
        if user is None:
            raise click.ClickException(f"There is no account called {username}.")
        problem = users.password_problem(password)
        if problem:
            raise click.ClickException(problem)
        users.set_password(user["id"], password)
        users.clear_failures(user["username"])
        audit.log("password_reset", username="terminal", detail=user["username"], ip="terminal")
        click.echo(f"New password set for '{user['username']}'.")

    app.cli.add_command(migrate.command)


def _register_errors(app: Flask) -> None:
    def page(code: int, title: str, text: str):
        if request.path.startswith("/api/"):
            return {"error": text}, code
        return render_template("message.html", title=title, text=text), code

    app.register_error_handler(400, lambda e: page(400, "Please try again", e.description))
    app.register_error_handler(403, lambda e: page(403, "Not allowed", "You don't have permission to open this page."))
    app.register_error_handler(404, lambda e: page(404, "Not found", "That page or record doesn't exist."))
    app.register_error_handler(405, lambda e: page(405, "Not allowed", "That action isn't allowed here."))
    app.register_error_handler(413, lambda e: page(413, "Too large", "That request was too large."))
    # Flask logs the full error for the server logs; the visitor only sees this plain message
    app.register_error_handler(500, lambda e: page(500, "Something went wrong",
                                                   "The server hit a problem. Please try again in a moment."))
