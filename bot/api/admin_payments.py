import os
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bot.models.database import db
from bot.models.payment_request import PaymentRequest
from bot.models.license import License
from bot.models.audit import AuditLog
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

    lic = License.create(
        user_id=g.current_user.id,
        plan=payment.plan,
        key=license_key,
    )
    db.session.add(lic)

    payment.status = "approved"
    payment.license_key = license_key
    payment.approved_at = datetime.utcnow()
    payment.admin_notes = data.get("notes", payment.admin_notes)
    db.session.commit()

    AuditLog.log(g.current_user.id, "approve_payment",
                  target=f"Payment #{payment_id} ({payment.name})",
                  details=f"Plano: {payment.plan}, Chave: {license_key[:16]}...",
                  status="success", ip=request.remote_addr)

    email_sent = _send_license_email(
        email=payment.email,
        name=payment.name,
        license_key=license_key,
        plan=payment.plan,
    )

    return jsonify({
        "message": "Pagamento aprovado e email enviado",
        "license_key": license_key,
        "email_sent": email_sent,
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

    AuditLog.log(g.current_user.id, "reject_payment",
                  target=f"Payment #{payment_id} ({payment.name})",
                  status="success", ip=request.remote_addr)

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

    lic = License.create(
        user_id=g.current_user.id,
        plan=plan,
        key=license_key,
    )
    db.session.add(lic)

    plan_amount = PLANOS[plan].get("preco", 0)

    payment = PaymentRequest(
        name=name,
        email=email,
        cpf=cpf,
        plan=plan,
        amount=float(plan_amount),
        payment_method="manual",
        status="approved",
        license_key=license_key,
        reference=reference,
        admin_notes=notes,
        approved_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()

    AuditLog.log(g.current_user.id, "create_manual_subscription",
                  target=f"{name} ({email})", details=f"Plano: {plan}",
                  status="success", ip=request.remote_addr)

    email_sent = _send_license_email(email, name, license_key, plan)

    return jsonify({
        "message": "Assinatura criada com sucesso",
        "license_key": license_key,
        "email_sent": email_sent,
        "payment": payment.to_dict(),
    }), 201


@admin_payments_bp.route("/<int:payment_id>/revoke", methods=["POST"])
@require_auth
@require_permission("admin")
def revoke_subscription(payment_id):
    """Revoga/exclui uma assinatura. Desativa a licenca associada e notifica o usuario."""
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

    AuditLog.log(g.current_user.id, "revoke_subscription",
                  target=f"Payment #{payment_id} ({payment.name})",
                  details=f"Motivo: {reason}", status="success",
                  ip=request.remote_addr)

    email_sent = False
    if payment.email:
        email_sent = _send_revocation_email(payment.email, payment.name, reason, payment.plan)

    return jsonify({
        "message": "Assinatura revogada",
        "email_sent": email_sent,
        "payment": payment.to_dict(),
    })


def _send_revocation_email(email, name, reason, plan="basico"):
    """Envia email avisando que a assinatura foi finalizada/cancelada, com motivo e link."""
    from config.settings import PLANOS
    plan_info = PLANOS.get(plan, {})
    plan_label = plan_info.get("label", plan)

    landing_url = "https://botdoprofessor.onrender.com"
    checkout_url = f"{landing_url}/checkout"

    html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.7; padding: 20px; max-width: 640px; margin: 0 auto; }}
        .header {{ background: #0f3460; color: white; padding: 28px; border-radius: 10px 10px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 1.5em; }}
        .header p {{ margin: 6px 0 0; font-size: 0.9em; opacity: 0.85; }}
        .content {{ padding: 28px; background: #ffffff; border: 1px solid #e2e8f0; }}
        .warn {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 14px 18px; border-radius: 0 8px 8px 0; margin: 18px 0; font-size: 0.95em; color: #92400e; }}
        .warn strong {{ display: block; margin-bottom: 4px; color: #92400e; }}
        .btn {{ display: inline-block; padding: 14px 32px; background: #e94560; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 16px 0; }}
        .section {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 18px 0; }}
        .section h3 {{ margin: 0 0 10px; color: #0f3460; font-size: 1em; }}
        .footer {{ padding: 18px 24px; background: #f8fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 10px 10px; text-align: center; font-size: 0.85em; color: #94a3b8; }}
        .footer a {{ color: #e94560; text-decoration: none; }}
    </style>
    </head>
    <body>
    <div class="header">
        <h1>BotDoProfessor</h1>
        <p>Sua assinatura foi finalizada</p>
    </div>
    <div class="content">
        <p>Ola <strong>{name}</strong>,</p>
        <p>Sua assinatura do plano <strong>{plan_label}</strong> foi <strong>finalizada ou cancelada</strong> e o acesso ao programa foi bloqueado.</p>

        <div class="warn">
            <strong>Motivo:</strong>
            {reason}
        </div>

        <p style="text-align:center">
            <a href="{checkout_url}" class="btn">Corrigir pagamento / Assinar / Reassinar</a>
        </p>

        <div class="section">
            <h3>O QUE FAZER?</h3>
            <p style="color:#475569;font-size:0.92em">
                Para continuar usando o BotDoProfessor, acesse a pagina de assinatura e <strong>corrija o pagamento, assine ou reassine</strong> seu plano:
            </p>
            <p style="color:#475569;font-size:0.92em">
                <a href="{landing_url}">{landing_url}</a>
            </p>
            <p style="color:#475569;font-size:0.92em">
                Assim que o novo pagamento for confirmado, uma nova chave de licenca sera enviada para este email.
            </p>
        </div>

        <p style="color:#475569;font-size:0.92em">
            Se voce acredita que isso foi um engano, responda este email ou envie uma mensagem para
            <a href="mailto:labintelligenceappoiments@gmail.com">labintelligenceappoiments@gmail.com</a>.
        </p>
    </div>
    <div class="footer">
        Duvidas? Responda este email ou envie para <a href="mailto:labintelligenceappoiments@gmail.com">labintelligenceappoiments@gmail.com</a><br>
        BotDoProfessor — Automatize suas notas
    </div>
    </body>
    </html>
    """

    subject = "BotDoProfessor — Assinatura finalizada/cancelada"

    from bot.utils.email_sender import send_email
    return send_email(email, subject, html)


def _send_license_email(email, name, license_key, plan):
    from config.settings import PLANOS
    plan_info = PLANOS.get(plan, {})
    plan_label = plan_info.get("label", plan)

    download_url = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"

    html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.7; padding: 20px; max-width: 640px; margin: 0 auto; }}
        .header {{ background: #0f3460; color: white; padding: 28px; border-radius: 10px 10px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 1.5em; }}
        .header p {{ margin: 6px 0 0; font-size: 0.9em; opacity: 0.85; }}
        .content {{ padding: 28px; background: #ffffff; border: 1px solid #e2e8f0; }}
        .key-box {{ background: #f0f9ff; border: 2px dashed #93c5fd; padding: 18px; border-radius: 8px; text-align: center; margin: 22px 0; }}
        .key-box .label {{ font-size: 0.78em; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .key-box .key {{ font-family: monospace; font-size: 1.3em; color: #1e40af; font-weight: bold; word-break: break-all; }}
        .key-box .hint {{ font-size: 0.82em; color: #94a3b8; margin-top: 8px; }}
        .btn {{ display: inline-block; padding: 14px 32px; background: #e94560; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 16px 0; }}
        .section {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin: 18px 0; }}
        .section h3 {{ margin: 0 0 10px; color: #0f3460; font-size: 1em; }}
        .step {{ display: flex; gap: 12px; margin-bottom: 14px; align-items: flex-start; }}
        .step-num {{ background: #0f3460; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 0.8em; flex-shrink: 0; }}
        .step-text {{ flex: 1; color: #475569; font-size: 0.92em; }}
        .step-text strong {{ color: #0c1b33; }}
        .warn {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 14px 0; font-size: 0.88em; color: #92400e; }}
        .tip {{ background: #ecfdf5; border-left: 4px solid #10b981; padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 14px 0; font-size: 0.88em; color: #065f46; }}
        .csv-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 14px 0; font-size: 0.88em; color: #475569; }}
        .csv-box code {{ background: #e2e8f0; padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }}
        .footer {{ padding: 18px 24px; background: #f8fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 10px 10px; text-align: center; font-size: 0.85em; color: #94a3b8; }}
        .footer a {{ color: #e94560; text-decoration: none; }}
        ul {{ margin: 8px 0; padding-left: 20px; }}
        li {{ margin-bottom: 4px; }}
    </style>
    </head>
    <body>
    <div class="header">
        <h1>BotDoProfessor</h1>
        <p>Seu acesso foi liberado!</p>
    </div>
    <div class="content">
        <p>Ola <strong>{name}</strong>,</p>
        <p>Seu pagamento foi confirmado! Abaixo esta tudo que voce precisa para comecar a usar. <strong>Leia com calma</strong> — e bem simples!</p>

        <div class="key-box">
            <div class="label">Sua chave de licenca</div>
            <div class="key">{license_key}</div>
            <div class="hint">Esta chave e pessoal e intransferivel. Guarde este email.</div>
        </div>

        <h3 style="color:#0c1b33;margin-top:28px">Como usar — passo a passo</h3>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-text">
                <strong>Baixe o programa</strong><br>
                Clique no link abaixo para baixar o BotDoProfessor.exe (arquivo unico, sem necessidade de instalacao adicional):<br>
                <a href="https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest" class="btn">Baixar BotDoProfessor.exe</a>
            </div>
        </div>

        <div class="step">
            <div class="step-num">2</div>
            <div class="step-text">
                <strong>Execute o programa</strong><br>
                Duplo-clique no arquivo <strong>BotDoProfessor.exe</strong> que voce baixou. Na primeira vez, o Windows pode mostrar um aviso de seguranca — clique em <strong>"Mais informacoes"</strong> e depois em <strong>"Executar mesmo assim"</strong>. Isso e normal.
            </div>
        </div>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-text">
                <strong>Aguarde a configuracao inicial</strong><br>
                Na primeira execucao, o programa configura tudo automaticamente (navegador, dependencias e IA local). Isso demora cerca de <strong>2 a 3 minutos</strong> e so acontece uma vez. <strong>Nao feche a janela</strong> enquanto estiver instalando.
            </div>
        </div>

        <div class="step">
            <div class="step-num">4</div>
            <div class="step-text">
                <strong>Cole sua chave de licenca</strong><br>
                Quando o programa pedir, cole a chave que aparece acima. Ela e salva automaticamente — nas proximas vezes nao precisa colar de novo.
            </div>
        </div>

        <div class="step">
            <div class="step-num">5</div>
            <div class="step-text">
                <strong>Informe seu CPF</strong><br>
                Digite o CPF que voce usa para acessar o SGE (so numeros, sem pontos). O programa salva automaticamente.
            </div>
        </div>

        <div class="step">
            <div class="step-num">6</div>
            <div class="step-text">
                <strong>Configure escola, turma e trimestre</strong><br>
                O programa vai perguntar qual escola, turno, turma e trimestre. Voce pode apertar Enter para usar os valores padrao, ou digitar os dados corretos. Essas configuracoes sao salvas para as proximas vezes.
            </div>
        </div>

        <div class="step">
            <div class="step-num">7</div>
            <div class="step-text">
                <strong>Escolha o tipo de lancamento</strong><br>
                Digite <code>1</code> para lancar <strong>Notas</strong> ou <code>2</code> para <strong>Plano de Aula</strong>. Para notas, voce pode importar de uma planilha Excel, CSV, Google Sheets, Notion, ou ate uma foto da lista de notas.
            </div>
        </div>

        <div class="tip">
            <strong>Nas proximas vezes:</strong> basta clicar em <strong>BotDoProfessor.exe</strong> de novo — ja fica instantaneo, com todas as configuracoes salvas!
        </div>

        <div class="section">
            <h3>COMO PREPARAR SUAS NOTAS</h3>
            <p style="color:#475569;font-size:0.92em;margin-bottom:12px">
                Para lancar notas, voce tem quatro opcoes:
            </p>

            <div class="csv-box">
                <p><strong>Opcao 1 — Notion:</strong></p>
                <p>Se voce ja usa o Notion para registrar notas, basta colar a URL da sua base de Notion quando o programa pedir. O programa extrai os dados automaticamente.</p>
            </div>

            <div class="csv-box">
                <p><strong>Opcao 2 — Planilha Excel ou CSV (.xlsx / .csv):</strong></p>
                <p>Crie uma planilha com duas colunas:</p>
                <p>
                    <code>Aluno</code> — nome completo do aluno (como aparece no SGE)<br>
                    <code>Nota</code> — valor numerico (ex: 8.5, 7.0, 9.2)
                </p>
                <p style="margin-top:10px"><strong>Exemplo:</strong></p>
                <p>
                    <code>Aluno;Nota</code><br>
                    <code>Maria Silva;8.5</code><br>
                    <code>Joao Santos;7.0</code><br>
                    <code>Ana Oliveira;9.2</code><br>
                    <code>Pedro Costa;6.0</code>
                </p>
                <p style="margin-top:10px">
                    Salve como <code>.xlsx</code> ou <code>.csv</code> e informe o caminho do arquivo quando o programa pedir.
                </p>
            </div>

            <div class="csv-box">
                <p><strong>Opcao 3 — Google Sheets (online):</strong></p>
                <p>1. Acesse <a href="https://sheets.google.com">sheets.google.com</a></p>
                <p>2. Crie uma nova planilha com colunas <code>Aluno</code> e <code>Nota</code></p>
                <p>3. Clique em <strong>"Compartilhar"</strong> (canto superior direito)</p>
                <p>4. Em "Quem tem acesso", clique em <strong>"Qualquer pessoa com o link"</strong></p>
                <p>5. Clique em <strong>"Copiar link"</strong></p>
                <p>6. Cole o link quando o programa pedir o caminho do arquivo</p>
            </div>

            <div class="csv-box">
                <p><strong>Opcao 4 — Imagem / Foto:</strong></p>
                <p>Se voce tiver uma foto ou print das notas (caderno, quadro, planilha impressa), o programa le a imagem automaticamente e extrai as notas usando inteligencia artificial. Basta informar o caminho da imagem quando o programa pedir.</p>
            </div>
        </div>

        <div class="section">
            <h3>PERGUNTAS FREQUENTES</h3>

            <p style="color:#475569;font-size:0.92em">
                <strong>O programa e seguro?</strong><br>
                Sim. Suas credenciais (CPF) ficam criptografadas no seu computador. Nenhum dado e enviado para servidores externos. O pagamento e processado pelo Mercado Pago, plataforma segura e certificada.
            </p>

            <p style="color:#475569;font-size:0.92em;margin-top:12px">
                <strong>Preciso de internet?</strong><br>
                Sim. O programa precisa de internet para conectar no SGE e lancar as notas. Mantenha a conexao ativa durante o lancamento.
            </p>

            <p style="color:#475569;font-size:0.92em;margin-top:12px">
                <strong>Funciona em qualquer escola?</strong><br>
                Funciona em escolas que usam o sistema <strong>SGE</strong>. Se a sua escola usa outro sistema, entre em contato conosco.
            </p>

            <p style="color:#475569;font-size:0.92em;margin-top:12px">
                <strong>Posso usar em mais de um computador?</strong><br>
                Sim, mas a chave de licenca esta vinculada a um numero limitado de maquinas. Se precisar trocar de computador, entre em contato.
            </p>

            <p style="color:#475569;font-size:0.92em;margin-top:12px">
                <strong>O programa lembra minhas configuracoes?</strong><br>
                Sim! Na segunda vez que voce usar, basta abrir o programa novamente — ele ja sabe a escola, turma, trimestre e CPF.
            </p>

            <p style="color:#475569;font-size:0.92em;margin-top:12px">
                <strong>Deu erro! O que faco?</strong><br>
                Verifique se:<br>
                - A chave foi colada corretamente (sem espacos extras)<br>
                - O CPF esta correto (11 numeros, sem pontos)<br>
                - A planilha tem as colunas "Aluno" e "Nota"<br>
                - Os nomes dos alunos estao iguais aos do SGE<br><br>
                Se nao resolver, responda este email ou envie para <a href="mailto:labintelligenceappoiments@gmail.com">labintelligenceappoiments@gmail.com</a>
            </p>
        </div>

        <div class="tip">
            <strong>Salve este email!</strong> Ele contem sua chave de licenca e todas as instrucoes. Voce pode precisar dele novamente.
        </div>
    </div>
    <div class="footer">
        Duvidas? Responda este email ou envie para <a href="mailto:labintelligenceappoiments@gmail.com">labintelligenceappoiments@gmail.com</a><br>
        BotDoProfessor — Automatize suas notas
    </div>
    </body>
    </html>
    """

    subject = f"BotDoProfessor — Sua chave de licenca ({plan_label})"

    from bot.utils.email_sender import send_email
    return send_email(email, subject, html)
