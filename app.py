import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=False)

from flask import Flask, jsonify, request, send_from_directory
from config.settings import SQLALCHEMY_DATABASE_URI, SECRET_KEY, DATA_DIR, LOGS_DIR
from bot.models.database import db, init_db
from bot.models.user import User
from bot.api.routes import auth_bp, license_bp, admin_bp, audit_bp
from bot.payment.routes import payment_bp, webhook_bp
from bot.api.lesson_plan_routes import lesson_plan_bp
from bot.api.admin_payments import admin_payments_bp
from bot.api.image_grades_routes import image_grades_bp
from bot.security.auth import require_auth, require_permission
from bot.security.errors import register_error_handlers
from bot.ops.monitoring import BackupManager, HealthChecker

LANDING_DIR = os.path.join(os.path.dirname(__file__), "landing")


def create_app():
    app = Flask(__name__, static_folder=LANDING_DIR, static_url_path="")
    app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    init_db(app)
    register_error_handlers(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(license_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(lesson_plan_bp)
    app.register_blueprint(admin_payments_bp)
    app.register_blueprint(image_grades_bp)

    @app.route("/api/health")
    def health():
        checker = HealthChecker()
        return jsonify(checker.full_check())

    @app.route("/")
    def index():
        return send_from_directory(LANDING_DIR, "index.html")

    @app.route("/checkout")
    def checkout():
        return send_from_directory(LANDING_DIR, "checkout.html")

    @app.route("/success")
    def success():
        return send_from_directory(LANDING_DIR, "success.html")

    @app.route("/admin")
    def admin_portal():
        return send_from_directory(LANDING_DIR, "admin.html")

    @app.route("/api/portals")
    @require_auth
    def list_portals():
        from bot.core.portal_factory import list_portals
        return jsonify({"portals": list_portals()})

    @app.route("/api/portals/discover", methods=["POST"])
    @require_auth
    @require_permission("admin")
    def discover_portal():
        data = request.get_json() or {}
        url = data.get("url", "")
        if not url:
            return jsonify({"error": "url obrigatoria"}), 400
        from bot.core.portal_factory import discover_portal
        from config.settings import AI_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY
        config = discover_portal(
            url,
            ai_provider=AI_PROVIDER,
            ai_config={"api_key": GEMINI_API_KEY or OPENAI_API_KEY},
        )
        if config:
            return jsonify({"config": config})
        return jsonify({"error": "Descoberta falhou"}), 400

    @app.route("/api/backup", methods=["POST"])
    @require_auth
    @require_permission("admin")
    def create_backup():
        data = request.get_json() or {}
        label = data.get("label", "") if isinstance(data, dict) else ""
        mgr = BackupManager()
        path = mgr.create_backup(label=label)
        return jsonify({"message": "Backup criado", "path": path})

    @app.route("/api/backup", methods=["GET"])
    @require_auth
    @require_permission("admin")
    def list_backups():
        mgr = BackupManager()
        return jsonify({"backups": mgr.list_backups()})

    return app


def _seed_initial_admin(app):
    """Cria admin inicial apenas se nao houver nenhum usuario no banco."""
    with app.app_context():
        if User.query.count() == 0:
            admin_user = os.environ.get("ADMIN_USER", "admin")
            admin_pass = os.environ.get("ADMIN_PASS", "admin123")
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@botlocal.com")

            admin = User(username=admin_user, email=admin_email, profile="admin")
            admin.set_password(admin_pass)
            db.session.add(admin)
            db.session.commit()
            print(f"[SEED] Admin criado: {admin_user} / {admin_pass}")


if __name__ == "__main__":
    app = create_app()
    _seed_initial_admin(app)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
