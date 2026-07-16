import hashlib
import platform
import uuid
from datetime import datetime
from typing import Optional, Dict
from bot.models.license import License
from bot.models.database import db
from bot.security.auth import generate_token


class LicenseService:
    """Servico de validacao e gerenciamento de licencas."""

    PLANS = {
        "basico": {
            "dias": 30,
            "preco": 49.90,
            "portais": 1,
            "ai_assist": False,
            "multi_portal": False,
        },
        "profissional": {
            "dias": 30,
            "preco": 99.90,
            "portais": 3,
            "ai_assist": True,
            "multi_portal": True,
        },
        "premium": {
            "dias": 30,
            "preco": 199.90,
            "portais": -1,
            "ai_assist": True,
            "multi_portal": True,
        },
    }

    @classmethod
    def generate_key(cls) -> str:
        raw = f"{uuid.uuid4().hex}{datetime.utcnow().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()

    @classmethod
    def get_machine_fingerprint(cls) -> str:
        parts = [
            platform.node(),
            platform.machine(),
            str(uuid.getnode()),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:64]

    @classmethod
    def activate(cls, user_id: int, plan: str, key: str = "", fingerprint: str = "") -> Optional[License]:
        if plan not in cls.PLANS:
            return None

        if not key:
            key = cls.generate_key()

        if not fingerprint:
            fingerprint = cls.get_machine_fingerprint()

        lic = License.create(
            user_id=user_id,
            plan=plan,
            key=key,
            fingerprint=fingerprint,
        )
        db.session.add(lic)
        db.session.commit()
        return lic

    @classmethod
    def validate(cls, license_key: str, fingerprint: str = "") -> Dict:
        lic = License.query.filter_by(license_key=license_key).first()
        if not lic:
            return {"valid": False, "error": "Licenca nao encontrada"}

        if not lic.active:
            return {"valid": False, "error": "Licenca desativada"}

        if not lic.is_valid:
            return {"valid": False, "error": "Licenca expirada"}

        if fingerprint and lic.machine_fingerprint:
            if fingerprint != lic.machine_fingerprint:
                return {"valid": False, "error": "Licenca vinculada a outra maquina"}

        plan_info = cls.PLANS.get(lic.plan, {})
        return {
            "valid": True,
            "plan": lic.plan,
            "days_remaining": lic.days_remaining,
            "expires_at": lic.expires_at.isoformat(),
            "features": plan_info,
        }

    @classmethod
    def check_feature(cls, license_key: str, feature: str) -> bool:
        result = cls.validate(license_key)
        if not result["valid"]:
            return False
        features = result.get("features", {})
        if feature == "ai_assist":
            return features.get("ai_assist", False)
        if feature == "multi_portal":
            return features.get("multi_portal", False)
        return True

    @classmethod
    def deactivate(cls, license_key: str) -> bool:
        lic = License.query.filter_by(license_key=license_key).first()
        if not lic:
            return False
        lic.active = False
        db.session.commit()
        return True

    @classmethod
    def extend(cls, license_key: str, days: int) -> bool:
        lic = License.query.filter_by(license_key=license_key).first()
        if not lic or not lic.active:
            return False
        if lic.expires_at > datetime.utcnow():
            lic.expires_at = lic.expires_at + __import__("datetime").timedelta(days=days)
        else:
            lic.expires_at = datetime.utcnow() + __import__("datetime").timedelta(days=days)
        db.session.commit()
        return True

    @classmethod
    def get_user_licenses(cls, user_id: int):
        return License.query.filter_by(user_id=user_id).order_by(License.activated_at.desc()).all()

    @classmethod
    def list_active(cls):
        return License.query.filter_by(active=True).all()
