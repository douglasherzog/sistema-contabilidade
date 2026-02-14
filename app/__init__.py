import os

from flask import Flask, send_from_directory

from .extensions import db, login_manager, migrate
from .main import main_bp
from .auth import auth_bp
from .payroll import payroll_bp
from .tax_sync import register_commands


def create_app() -> Flask:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    templates_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")
    app = Flask(__name__, template_folder=templates_dir, static_folder=static_dir)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL não está configurada")

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(payroll_bp)

    register_commands(app)

    media_guides_dir = os.path.join(app.instance_path, "media", "guides")
    os.makedirs(media_guides_dir, exist_ok=True)

    @app.route("/media/guides/<path:filename>")
    def media_guides(filename: str):
        resp = send_from_directory(media_guides_dir, filename)
        try:
            resp.headers["Cache-Control"] = "no-store, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        except Exception:
            pass
        return resp

    return app
