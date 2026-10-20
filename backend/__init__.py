"""
Excise Fee Estimator: Flask application factory.

    backend/
      config.py      settings from environment
      db.py          PostgreSQL connection + schema
      security.py    CSRF, headers, login/admin guards
      services/      users, estimates, audit log (all SQL lives here)
      routes/        auth, main (calculator), admin, api blueprints
    frontend/
      templates/     Jinja pages (auth/, app/, admin/)
      static/        css/ and js/ (the fee engine runs in the browser)
"""
import os

from flask import Flask, g, render_template, request

from . import config as cfg
from .db import close_db, init_db
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

    app.teardown_appcontext(close_db)
    app.before_request(check_csrf)
    app.after_request(security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token

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

    from .services import users

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create the database tables (safe to re-run; never deletes data)."""
        init_db(app.config["DATABASE_URL"])
        click.echo("Database tables are ready.")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--name", default="", help="Full name shown in the app.")
    @click.option("--admin", is_flag=True, help="Give the account admin rights.")
    @click.password_option()
    def create_user(username: str, name: str, admin: bool, password: str) -> None:
        """Create a login from the terminal (prompts for the password)."""
        problem = users.username_problem(username) or users.password_problem(password)
        if problem:
            raise click.ClickException(problem)
        try:
            users.create(username, name, password, is_admin=admin)
        except users.UsernameTaken:
            raise click.ClickException(f"The username {username} is already taken.") from None
        click.echo(f"Created {'admin' if admin else 'staff'} account '{username}'.")


def _register_errors(app: Flask) -> None:
    def page(code: int, title: str, text: str):
        if request.path.startswith("/api/"):
            return {"error": text}, code
        return render_template("message.html", title=title, text=text), code

    app.register_error_handler(400, lambda e: page(400, "Please try again", e.description))
    app.register_error_handler(403, lambda e: page(403, "Admins only", "Only an admin can open this page."))
    app.register_error_handler(404, lambda e: page(404, "Not found", "That page or record doesn't exist."))
    app.register_error_handler(405, lambda e: page(405, "Not allowed", "That action isn't allowed here."))
