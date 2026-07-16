from datetime import datetime
from bot.models.database import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    action = db.Column(db.String(100), nullable=False)
    target = db.Column(db.String(200))
    status = db.Column(db.String(20), nullable=False, default="success")
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))

    user = db.relationship("User", backref="audit_logs")

    @classmethod
    def log(cls, user_id, action, target="", status="success", details="", ip=""):
        entry = cls(
            user_id=user_id,
            action=action,
            target=target,
            status=status,
            details=details,
            ip_address=ip,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "target": self.target,
            "status": self.status,
            "details": self.details,
        }
