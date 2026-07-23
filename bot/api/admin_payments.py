import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, request, jsonify, g
from bot.models.database import db
from bot.models.payment_request import PaymentRequest
from bot.models.license import License
from bot.security.auth import require_auth, require_permission

admin_payments_bp = Blueprint("admin_payments", __name__, url_prefix="/api/admin/payments")


@admin_payments_bp.route("", methods=["GET"])
@require_auth
@require_permission("admin")
def list_payment_requests():
    status = request.args.get("status", "")
    plan = request.args.get("plan", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    query = PaymentRequest.query

    if status:
        query = query.filter_by(status=status)
    if plan:
        query = query.filter_by(plan=plan)

    query = query.order_by(PaymentRequest.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "payments": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page,
    })


@admin_payments_bp.route("/stats", methods=["GET"])
@require_auth
@require_permission("admin")
def payment_stats():
    total = PaymentRequest.query.count()
    pending = PaymentRequest.query.filter_by(status="pending").count()
    contacted = PaymentRequest.query.filter_by(status="contacted").count()
    approved = PaymentRequest.query.filter_by(status="approved").count()
    rejected = PaymentRequest.query.filter_by(status="rejected").count()

    pending_amount = db.session.query(db.func.sum(PaymentRequest.amount))\
        .filter_by(status="pending").scalar() or 0
    approved_amount = db.session.query(db.func.sum(PaymentRequest.amount))\
        .filter_by(status="approved").scalar() or 0

    return jsonify({
        "total": total,
        "pending": pending,
        "contacted": contacted,
        "approved": approved,
        "rejected": rejected,
        "pending_amount": round(pending_amount, 2),
        "approved_amount": round(approved_amount, 2),
    })


@admin_payments_bp.route("/<int:payment_id>", methods=["GET"])
@require_auth
@require_permission("admin")
def get_payment(payment_id):
    payment = PaymentRequest.query.get_or_404(payment_id)
    return jsonify(payment.to_dict())


@admin_payments_bp.route("/<int:payment_id>/contact", methods=["POST"])
@require_auth
@require_permission("admin")
def mark_contacted(payment_id):
    payment = PaymentRequest.query.get_or_404(payment_id)
    data = request.get_json() or {}

    payment.status = "contacted"
    payment.contacted_at = datetime.utcnow()
    payment.admin_notes = data.get("notes", payment.admin_notes)
    db.session.commit()

    return jsonify({"message": "Marcado como contatado", "payment": payment.to_dict()})


@admin_payments_bp.route("/<int:payment_id>/approve", methods=["POST"])
@require_auth
@require_permission("admin")
def approve_payment(payment_id):
    payment = PaymentRequest.query.get_or_404(payment_id)
    data = request.get_json() or {}

    if payment.status == "approved" and payment.license_key:
        return jsonify({"error": "Pagamento ja aprovado", "license_key": payment.license_key}), 400

    from bot.core.license_service import LicenseService
    license_key = data.get("license_key", LicenseService.generate_key())

    payment.status = "approved"
    payment.license_key = license_key
    payment.approved_at = datetime.utcnow()
    payment.admin_notes = data.get("notes", payment.admin_notes)
    db.session.commit()

    _send_license_email(
        email=payment.email,
        name=payment.name,
        license_key=license_key,
        plan=payment.plan,
    )

    return jsonify({
        "message": "Pagamento aprovado e email enviado",
        "license_key": license_key,
        "payment": payment.to_dict(),
    })


@admin_payments_bp.route("/<int:payment_id>/reject", methods=["POST"])
@require_auth
@require_permission("admin")
def reject_payment(payment_id):
    payment = PaymentRequest.query.get_or_404(payment_id)
    data = request.get_json() or {}

    payment.status = "rejected"
    payment.admin_notes = data.get("notes", payment.admin_notes)
    db.session.commit()

    return jsonify({"message": "Pagamento rejeitado", "payment": payment.to_dict()})


@admin_payments_bp.route("/<int:payment_id>/notes", methods=["PUT"])
@require_auth
@require_permission("admin")
def update_notes(payment_id):
    payment = PaymentRequest.query.get_or_404(payment_id)
    data = request.get_json() or {}

    payment.admin_notes = data.get("notes", "")
    db.session.commit()

    return jsonify({"message": "Notas atualizadas", "payment": payment.to_dict()})


@admin_payments_bp.route("/create", methods=["POST"])
@require_auth
@require_permission("admin")
def create_payment_request():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    cpf = data.get("cpf", "").strip()
    plan = data.get("plan", "")
    amount = data.get("amount", 0)
    payment_method = data.get("payment_method", "pix")
    notes = data.get("notes", "")

    if not all([name, email, cpf, plan]):
        return jsonify({"error": "name, email, cpf e plan sao obrigatorios"}), 400

    import hashlib
    reference = hashlib.sha256(f"{email}_{cpf}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]

    payment = PaymentRequest(
        name=name,
        email=email,
        cpf=cpf,
        plan=plan,
        amount=float(amount),
        payment_method=payment_method,
        reference=reference,
        admin_notes=notes,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({"message": "Pagamento criado", "payment": payment.to_dict()}), 201


@admin_payments_bp.route("/create-manual", methods=["POST"])
@require_auth
@require_permission("admin")
def create_manual_subscription():
    """Cria assinatura manual sem pagamento. Gera chave e envia email."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    cpf = data.get("cpf", "").strip()
    plan = data.get("plan", "")
    notes = data.get("notes", "Assinatura manual criada pelo admin")

    if not all([name, email, cpf, plan]):
        return jsonify({"error": "name, email, cpf e plan sao obrigatorios"}), 400

    from config.settings import PLANOS
    if plan not in PLANOS:
        return jsonify({"error": f"Plano invalido. Opcoes: {list(PLANOS.keys())}"}), 400

    import hashlib
    from bot.core.license_service import LicenseService
    reference = hashlib.sha256(f"manual_{email}_{cpf}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
    license_key = LicenseService.generate_key()

    payment = PaymentRequest(
        name=name,
        email=email,
        cpf=cpf,
        plan=plan,
        amount=0,
        payment_method="manual",
        status="approved",
        license_key=license_key,
        reference=reference,
        admin_notes=notes,
        approved_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()

    _send_license_email(email, name, license_key, plan)

    return jsonify({
        "message": "Assinatura criada com sucesso",
        "license_key": license_key,
        "payment": payment.to_dict(),
    }), 201


@admin_payments_bp.route("/<int:payment_id>/revoke", methods=["POST"])
@require_auth
@require_permission("admin")
def revoke_subscription(payment_id):
    """Revoga/exclui uma assinatura. Desativa a licenca associada."""
    payment = PaymentRequest.query.get_or_404(payment_id)
    data = request.get_json() or {}
    reason = data.get("reason", "Revogado pelo admin")

    if payment.status == "rejected":
        return jsonify({"error": "Assinatura ja esta revogada"}), 400

    payment.status = "rejected"
    payment.admin_notes = f"{payment.admin_notes or ''}\n[REVOGADO] {reason}".strip()
    db.session.commit()

    if payment.license_key:
        lic = License.query.filter_by(license_key=payment.license_key).first()
        if lic:
            lic.active = False
            db.session.commit()

    return jsonify({
        "message": "Assinatura revogada",
        "payment": payment.to_dict(),
    })


def _send_license_email(email, name, license_key, plan):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_user:
        print(f"[EMAIL SKIP] Chave para {email}: {license_key}")
        return

    from config.settings import PLANOS
    plan_info = PLANOS.get(plan, {})
    plan_label = plan_info.get("label", plan)

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = email
    msg["Subject"] = f"BotDoProfessor — Sua chave de licenca ({plan_label})"

    download_url = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"

    html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 20px; max-width: 600px; margin: 0 auto; }}
        .header {{ background: #0f3460; color: white; padding: 24px; border-radius: 10px 10px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 1.4em; }}
        .content {{ padding: 24px; background: #ffffff; border: 1px solid #e2e8f0; }}
        .key-box {{ background: #f0f9ff; border: 2px dashed #93c5fd; padding: 16px; border-radius: 8px; text-align: center; margin: 20px 0; }}
        .key-box .label {{ font-size: 0.8em; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .key-box .key {{ font-family: monospace; font-size: 1.3em; color: #1e40af; font-weight: bold; word-break: break-all; }}
        .btn {{ display: inline-block; padding: 14px 32px; background: #e94560; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 16px 0; }}
        .step {{ display: flex; gap: 12px; margin-bottom: 16px; align-items: flex-start; }}
        .step-num {{ background: #0f3460; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 0.8em; flex-shrink: 0; }}
        .step-text {{ flex: 1; color: #475569; font-size: 0.92em; }}
        .step-text strong {{ color: #0c1b33; }}
        .footer {{ padding: 16px 24px; background: #f8fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 10px 10px; text-align: center; font-size: 0.85em; color: #94a3b8; }}
        .footer a {{ color: #e94560; text-decoration: none; }}
    </style>
    </head>
    <body>
    <div class="header">
        <h1>BotDoProfessor</h1>
    </div>
    <div class="content">
        <p>Ola <strong>{name}</strong>,</p>
        <p>Seu pagamento foi confirmado! Aqui esta tudo que voce precisa para comecar:</p>

        <div class="key-box">
            <div class="label">Sua chave de licenca</div>
            <div class="key">{license_key}</div>
        </div>

        <p style="text-align:center">
            <a href="{download_url}" class="btn">Baixar o programa</a>
        </p>

        <h3 style="color:#0c1b33;margin-top:24px">Como usar — passo a passo</h3>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-text">
                <strong>Baixe o programa</strong><br>
                Clique no botao acima ou acesse: <a href="{download_url}">{download_url}</a><br>
                O arquivo BotDoProfessor.exe tem cerca de 140MB.
            </div>
        </div>

        <div class="step">
            <div class="step-num">2</div>
            <div class="step-text">
                <strong>Execute o arquivo</strong><br>
                Duplo-clique no BotDoProfessor.exe. O Windows pode mostrar um aviso de seguranca — clique em "Mais informacoes" e depois em "Executar mesmo assim".
            </div>
        </div>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-text">
                <strong>Aguarde a primeira configuracao</strong><br>
                Na primeira vez, o programa instala o navegador Chromium automaticamente (cerca de 180MB). Isso demora aproximadamente 2 minutos e so acontece uma vez.
            </div>
        </div>

        <div class="step">
            <div class="step-num">4</div>
            <div class="step-text">
                <strong>Cole a chave de licenca</strong><br>
                Quando o programa pedir, cole a chave que aparece acima. Ela e salva automaticamente — nas proximas vezes nao precisa colar de novo.
            </div>
        </div>

        <div class="step">
            <div class="step-num">5</div>
            <div class="step-text">
                <strong>Informe seu CPF</strong><br>
                Digite o CPF que voce usa para acessar o SGE (so numeros, sem pontos ou traco).
            </div>
        </div>

        <div class="step">
            <div class="step-num">6</div>
            <div class="step-text">
                <strong>Configure escola, turma e trimestre</strong><br>
                O programa vai perguntar qual escola, turno, turma e trimestre.
            </div>
        </div>

        <div class="step">
            <div class="step-num">7</div>
            <div class="step-text">
                <strong>Escolha o tipo de lancamento</strong><br>
                Digite <code>1</code> para <strong>Notas</strong> ou <code>2</code> para <strong>Plano de Aula</strong>.
            </div>
        </div>
    </div>
    <div class="footer">
        Duvidas? Responda este email ou envie para <a href="mailto:labintelligenceappoiments@gmail.com">labintelligenceappoiments@gmail.com</a><br>
        BotDoProfessor — Automatize suas notas
    </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, email, msg.as_string())
        server.quit()
        print(f"[EMAIL OK] Chave enviada para {email}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
