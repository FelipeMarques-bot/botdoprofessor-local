from datetime import datetime
from bot.models.database import db


class PaymentRequest(db.Model):
    __tablename__ = "payment_requests"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    cpf = db.Column(db.String(20), nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default="pix")
    status = db.Column(db.String(20), nullable=False, default="pending")
    license_key = db.Column(db.String(64))
    reference = db.Column(db.String(64), unique=True)
    admin_notes = db.Column(db.Text)
    contacted_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "cpf": self.cpf,
            "plan": self.plan,
            "amount": self.amount,
            "payment_method": self.payment_method,
            "status": self.status,
            "license_key": self.license_key,
            "reference": self.reference,
            "admin_notes": self.admin_notes,
            "contacted_at": self.contacted_at.isoformat() if self.contacted_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
