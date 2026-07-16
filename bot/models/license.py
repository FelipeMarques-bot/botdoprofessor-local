from datetime import datetime, timedelta
from bot.models.database import db


class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    days = db.Column(db.Integer, nullable=False)
    activated_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, default=True)
    machine_fingerprint = db.Column(db.String(256))

    user = db.relationship("User", backref="licenses")

    @property
    def is_valid(self) -> bool:
        return self.active and datetime.utcnow() < self.expires_at

    @property
    def days_remaining(self) -> int:
        if not self.is_valid:
            return 0
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)

    @classmethod
    def create(cls, user_id: int, plan: str, key: str, fingerprint: str = ""):
        from config.settings import PLANOS
        p = PLANOS.get(plan)
        if not p:
            raise ValueError(f"Plano desconhecido: {plan}")
        now = datetime.utcnow()
        lic = cls(
            license_key=key,
            user_id=user_id,
            plan=plan,
            days=p["dias"],
            activated_at=now,
            expires_at=now + timedelta(days=p["dias"]),
            machine_fingerprint=fingerprint,
        )
        return lic

    def to_dict(self):
        return {
            "id": self.id,
            "license_key": self.license_key[:8] + "...",
            "plan": self.plan,
            "days": self.days,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "active": self.active,
            "is_valid": self.is_valid,
            "days_remaining": self.days_remaining,
        }
