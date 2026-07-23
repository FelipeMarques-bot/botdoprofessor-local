from functools import wraps
from datetime import datetime, timedelta
import jwt
from flask import request, jsonify, g
from config.settings import SECRET_KEY
from bot.models.user import User
from bot.models.license import License
from bot.models.audit import AuditLog


def generate_token(user: User) -> str:
    payload = {
        "user_id": user.id,
        "username": user.username,
        "profile": user.profile,
        "token_version": getattr(user, "token_version", 0),
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"error": "Token ausente"}), 401
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            print(f"[AUTH FAIL] Token expirado path={request.path} ip={request.remote_addr}")
            return jsonify({"error": "Token expirado"}), 401
        except jwt.InvalidTokenError as e:
            print(f"[AUTH FAIL] Token invalido: {e} path={request.path} ip={request.remote_addr}")
            return jsonify({"error": "Token invalido"}), 401

        user = User.query.get(payload["user_id"])
        if not user or not user.active:
            print(f"[AUTH FAIL] Usuario inativo ou nao encontrado: {payload.get('user_id')} path={request.path}")
            return jsonify({"error": "Usuario inativo"}), 401

        stored_version = getattr(user, "token_version", 0)
        token_version = payload.get("token_version", 0)
        if stored_version != token_version:
            print(f"[AUTH FAIL] Token version mismatch: stored={stored_version} token={token_version} user={user.username} path={request.path}")
            AuditLog.log(user.id, "token_reused_after_invalidation",
                         status="denied", ip=request.remote_addr)
            return jsonify({"error": "Sessao invalidada. Faca login novamente."}), 401

        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def require_permission(action: str):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user or not user.has_permission(action):
                AuditLog.log(
                    user_id=user.id if user else None,
                    action=f"permission_denied:{action}",
                    status="denied",
                    ip=request.remote_addr,
                )
                return jsonify({"error": "Permissao negada"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def check_license_valid() -> dict:
    user = getattr(g, "current_user", None)
    if not user:
        return {"valid": False, "error": "Usuario nao autenticado"}

    lic = License.query.filter_by(user_id=user.id, active=True)\
        .order_by(License.expires_at.desc()).first()

    if not lic:
        return {"valid": False, "error": "Nenhuma licenca ativa"}

    if not lic.is_valid:
        lic.active = False
        from bot.models.database import db
        db.session.commit()
        return {"valid": False, "error": "Licenca expirada"}

    return {"valid": True, "days_remaining": lic.days_remaining, "plan": lic.plan}
