from datetime import datetime
from bot.models.database import db
import bcrypt


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    profile = db.Column(db.String(20), nullable=False, default="operador")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    PROFILES = ("admin", "operador", "auditor")

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            self.password_hash.encode("utf-8"),
        )

    def has_permission(self, action: str) -> bool:
        perms = {
            "admin": ["*"],
            "operador": ["execute", "view_logs", "view_dashboard"],
            "auditor": ["view_logs", "view_dashboard", "view_reports"],
        }
        allowed = perms.get(self.profile, [])
        return "*" in allowed or action in allowed

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "profile": self.profile,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
