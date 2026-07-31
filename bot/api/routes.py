import time
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import OperationalError
from bot.models.database import db
from bot.models.user import User
from bot.models.license import License
from bot.models.audit import AuditLog
from bot.security.auth import (
    require_auth, require_permission, generate_token,
    check_license_valid,
)
from bot.security.rate_limit import rate_limit

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
license_bp = Blueprint("license", __name__, url_prefix="/api/license")
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")


def _find_license(key):
    """Busca licenca com retry para erros transitorios de conexao (Postgres/Neon)."""
    for attempt in range(3):
        try:
            return License.query.filter_by(license_key=key).first()
        except OperationalError:
            db.session.rollback()
            if attempt < 2:
                time.sleep(1.0)
    return None


@license_bp.route("/public-validate", methods=["POST"])
def public_validate_license():
    """Validacao publica de licenca (sem autenticacao).
    Usado pelo executavel .exe para validar a chave.
    """
    data = request.get_json() or {}
    key = data.get("license_key", "").strip()
    if not key:
        return jsonify({"valid": False, "error": "Chave obrigatoria"}), 400

    lic = _find_license(key)
    if not lic:
        return jsonify({"valid": False, "error": "Licenca nao encontrada"})

    if not lic.active:
        return jsonify({"valid": False, "error": "Licenca desativada"})

    if lic.expires_at and lic.expires_at < datetime.utcnow():
        return jsonify({"valid": False, "error": "Licenca expirada"})

    days_remaining = -1
    if lic.expires_at:
        delta = lic.expires_at - datetime.utcnow()
        days_remaining = max(0, delta.days)

    return jsonify({
        "valid": True,
        "plan": lic.plan,
        "days_remaining": days_remaining,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
    })


@auth_bp.route("/login", methods=["POST"])
@rate_limit(max_attempts=15, window=120)
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        AuditLog.log(None, "login_failed", target=username, status="denied",
                      ip=request.remote_addr)
        print(f"[LOGIN FAIL] user={username} ip={request.remote_addr}")
        return jsonify({"error": "Credenciais invalidas"}), 401

    if not user.active:
        return jsonify({"error": "Usuario inativo"}), 403

    user.last_login = datetime.utcnow()
    db.session.commit()

    token = generate_token(user)
    AuditLog.log(user.id, "login", status="success", ip=request.remote_addr)
    print(f"[LOGIN OK] user={username} id={user.id} token_version={user.token_version} ip={request.remote_addr}")
    return jsonify({"token": token, "user": user.to_dict()})


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    lic_status = check_license_valid()
    return jsonify({"user": g.current_user.to_dict(), "license": lic_status})


@auth_bp.route("/change-password", methods=["POST"])
@require_auth
@rate_limit(max_attempts=5, window=300)
def change_password():
    data = request.get_json() or {}
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")

    if not g.current_user.check_password(old_pw):
        AuditLog.log(g.current_user.id, "change_password", status="denied",
                      details="Senha atual incorreta", ip=request.remote_addr)
        return jsonify({"error": "Senha atual incorreta"}), 400

    if len(new_pw) < 6:
        return jsonify({"error": "Nova senha deve ter no minimo 6 caracteres"}), 400

    g.current_user.set_password(new_pw)
    g.current_user.invalidate_tokens()
    AuditLog.log(g.current_user.id, "change_password", status="success",
                  ip=request.remote_addr)

    new_token = generate_token(g.current_user)
    return jsonify({"message": "Senha alterada com sucesso", "token": new_token})


@auth_bp.route("/change-username", methods=["POST"])
@require_auth
@rate_limit(max_attempts=5, window=300)
def change_username():
    data = request.get_json() or {}
    password = data.get("password", "")
    new_username = data.get("new_username", "").strip()

    if not g.current_user.check_password(password):
        AuditLog.log(g.current_user.id, "change_username", status="denied",
                      details="Senha incorreta", ip=request.remote_addr)
        return jsonify({"error": "Senha incorreta"}), 400

    if not new_username or len(new_username) < 3:
        return jsonify({"error": "Username deve ter no minimo 3 caracteres"}), 400

    existing = User.query.filter_by(username=new_username).first()
    if existing and existing.id != g.current_user.id:
        return jsonify({"error": "Username ja existe"}), 400

    if g.current_user.is_protected and new_username in User.INITIAL_ADMIN_USERNAMES:
        return jsonify({"error": "Username de administrador principal nao pode ser alterado para este valor"}), 400

    old_username = g.current_user.username
    g.current_user.username = new_username
    g.current_user.invalidate_tokens()
    db.session.commit()
    AuditLog.log(g.current_user.id, "change_username", target=old_username,
                  details=f"Novo username: {new_username}", status="success",
                  ip=request.remote_addr)

    new_token = generate_token(g.current_user)
    return jsonify({"message": "Username alterado com sucesso", "new_username": new_username, "token": new_token})


@license_bp.route("/validate", methods=["GET"])
@require_auth
def validate_license():
    result = check_license_valid()
    return jsonify(result)


@license_bp.route("/activate", methods=["POST"])
@require_auth
@require_permission("execute")
def activate_license():
    data = request.get_json() or {}
    key = data.get("license_key", "")
    plan = data.get("plan", "")

    if not key or not plan:
        return jsonify({"error": "license_key e plan obrigatorios"}), 400

    existing = License.query.filter_by(license_key=key).first()
    if existing:
        return jsonify({"error": "Licenca ja utilizada"}), 400

    try:
        lic = License.create(
            user_id=g.current_user.id,
            plan=plan,
            key=key,
            fingerprint=data.get("fingerprint", ""),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db.session.add(lic)
    db.session.commit()

    AuditLog.log(g.current_user.id, "license_activate", target=plan, status="success")
    return jsonify({"message": "Licenca ativada", "license": lic.to_dict()})


@admin_bp.route("/users", methods=["GET"])
@require_auth
@require_permission("admin")
def list_users():
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])


@admin_bp.route("/users", methods=["POST"])
@require_auth
@require_permission("admin")
def create_user():
    data = request.get_json() or {}
    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")
    profile = data.get("profile", "operador")

    if not username or not email or not password:
        return jsonify({"error": "username, email e password obrigatorios"}), 400

    if profile not in User.PROFILES:
        return jsonify({"error": f"Perfil invalido. Opcoes: {User.PROFILES}"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username ja existe"}), 400

    user = User(username=username, email=email, profile=profile)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    AuditLog.log(g.current_user.id, "create_user", target=username, status="success")
    return jsonify({"user": user.to_dict()}), 201


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@require_auth
@require_permission("admin")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_protected:
        AuditLog.log(g.current_user.id, "delete_user", target=user.username,
                      status="denied", details="Tentativa de excluir admin principal",
                      ip=request.remote_addr)
        return jsonify({"error": "Nao e possivel excluir o administrador principal"}), 400
    user.active = False
    db.session.commit()
    AuditLog.log(g.current_user.id, "deactivate_user", target=user.username, status="success")
    return jsonify({"message": f"Usuario {user.username} desativado"})


@audit_bp.route("/logs", methods=["GET"])
@require_auth
@require_permission("view_logs")
def list_logs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "logs": [l.to_dict() for l in logs.items],
        "total": logs.total,
        "pages": logs.pages,
    })


@admin_bp.route("/payments/pending", methods=["GET"])
@require_auth
@require_permission("admin")
def list_pending_payments():
    from bot.payment.service import PaymentService
    svc = PaymentService()
    pending = svc.list_pending_payments()
    return jsonify({"payments": pending})


@admin_bp.route("/payments/<reference>/approve", methods=["POST"])
@require_auth
@require_permission("admin")
def approve_payment(reference):
    from bot.payment.service import PaymentService
    svc = PaymentService()
    result = svc.approve_manual_payment(reference)
    if "error" in result:
        return jsonify(result), 400
    AuditLog.log(g.current_user.id, "approve_payment", target=reference, status="success")
    return jsonify(result)
