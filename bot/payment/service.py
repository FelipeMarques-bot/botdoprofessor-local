import os
import json
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

try:
    import mercadopago
except ImportError:
    mercadopago = None


DATA_DIR = Path.home() / ".bot_local" / "payments"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class PaymentService:
    """Servico de pagamentos via Mercado Pago + fallback Pix manual."""

    PLANS = {
        "1ano": {"dias": 365, "preco": 99.90, "label": "1 Ano"},
        "2anos": {"dias": 730, "preco": 169.83, "label": "2 Anos"},
        "3anos": {"dias": 1095, "preco": 224.78, "label": "3 Anos"},
    }

    PIX_KEY = os.environ.get("PIX_KEY", "")
    PIX_NAME = os.environ.get("PIX_NAME", "BotDoProfessor")
    PIX_CITY = os.environ.get("PIX_CITY", "Sao Paulo")

    def __init__(self):
        self._sdk = None
        self._access_token = ""
        access_token = os.environ.get("MP_ACCESS_TOKEN", "")
        self._access_token = access_token
        if access_token and mercadopago:
            self._sdk = mercadopago.SDK(access_token)

    def create_preference(self, plan: str, name: str, email: str, cpf: str,
                          payment_method: str = "card") -> Dict:
        """Cria pagamento via Mercado Pago."""
        plan_info = self.PLANS.get(plan)
        if not plan_info:
            return {"error": "Plano desconhecido"}

        if not self._sdk:
            return self._create_manual_payment(plan, name, email, cpf, payment_method)

        cpf_clean = cpf.replace(".", "").replace("-", "")
        ext_ref = self._generate_external_ref(plan, email, cpf)

        if payment_method == "pix":
            return self._create_pix_payment(plan_info, name, email, cpf_clean, ext_ref)

        return self._create_checkout_preference(plan, plan_info, name, email, cpf_clean, ext_ref)

    def _create_pix_payment(self, plan_info, name, email, cpf, ext_ref):
        """Cria pagamento Pix direto via API (sem checkout redirect)."""
        try:
            payment_data = {
                "transaction_amount": plan_info["preco"],
                "description": f"BotDoProfessor - Plano {plan_info['label']}",
                "payment_method_id": "pix",
                "payer": {
                    "first_name": name.split()[0] if name else "Cliente",
                    "last_name": " ".join(name.split()[1:]) if name and len(name.split()) > 1 else "BotDoProfessor",
                    "email": email,
                    "identification": {
                        "type": "CPF",
                        "number": cpf,
                    },
                },
                "external_reference": ext_ref,
            }

            result = self._sdk.payment().create(payment_data)
            response = result.get("response", {})
            point_of_interaction = response.get("point_of_interaction", {})
            transaction_data = point_of_interaction.get("transaction_data", {})
            qr_code_base64 = transaction_data.get("qr_code_base64", "")
            qr_code = transaction_data.get("ticket_url", "")
            payment_id = response.get("id")

            if not qr_code_base64 and not qr_code:
                return {"error": "Nao foi possivel gerar QR Code Pix"}

            self._save_payment_by_id(plan_info, name, email, cpf, ext_ref, "mercadopago_pix", payment_id)

            self._create_db_payment_request(ext_ref, name, email, cpf, plan_info["preco"], "pix")

            return {
                "qr_code_base64": qr_code_base64,
                "qr_code": qr_code,
                "payment_id": payment_id,
                "amount": plan_info["preco"],
            }

        except Exception as e:
            return {"error": f"Erro ao criar pagamento Pix: {str(e)}"}

    def _create_checkout_preference(self, plan, plan_info, name, email, cpf, ext_ref):
        """Cria preferencia de checkout (cartao/redirect)."""
        try:
            preference_data = {
                "items": [{
                    "id": f"bot_{plan}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    "title": f"BotDoProfessor - Plano {plan_info['label']}",
                    "quantity": 1,
                    "unit_price": plan_info["preco"],
                    "currency_id": "BRL",
                }],
                "payer": {
                    "name": name,
                    "email": email,
                    "identification": {
                        "type": "CPF",
                        "number": cpf,
                    },
                },
                "payment_methods": {
                    "excluded_payment_types": [
                        {"id": "ticket"},
                    ],
                },
                "external_reference": ext_ref,
                "notification_url": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/api/webhook/mercadopago",
                "back_urls": {
                    "success": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/success",
                    "pending": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/success",
                    "failure": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/",
                },
                "auto_return": "approved",
            }

            result = self._sdk.preference().create(preference_data)
            response = result.get("response", {})
            is_test = self._access_token.startswith("TEST-")
            if is_test:
                init_point = response.get("sandbox_init_point") or response.get("init_point", "")
            else:
                init_point = response.get("init_point", "")

            self._save_payment(plan, email, cpf, name, "mercadopago", init_point)

            return {"checkout_url": init_point}

        except Exception as e:
            return {"error": f"Erro ao criar pagamento: {str(e)}"}

    def _create_manual_payment(self, plan: str, name: str, email: str, cpf: str,
                                payment_method: str) -> Dict:
        """Fallback: gera dados para pagamento manual via Pix."""
        plan_info = self.PLANS[plan]

        pix_payload = self._generate_pix_payload(plan_info["preco"])

        ref = self._generate_external_ref(plan, email, cpf)
        self._save_payment(plan, email, cpf, name, "manual_pix", ref, status="pending")

        self._create_db_payment_request(plan, name, email, cpf, plan_info["preco"], "pix")

        return {
            "qr_code": pix_payload,
            "qr_code_base64": "",
            "amount": plan_info["preco"],
            "reference": ref,
            "message": f"Pague R$ {plan_info['preco']:.2f} via Pix e envie o comprovante para {os.environ.get('CONTACT_EMAIL', 'contato@botdoprofessor.com.br')}",
        }

    def handle_webhook(self, data: Dict) -> Dict:
        """Processa notificacao do Mercado Pago."""
        if not self._sdk:
            return {"status": "ignored", "reason": "SDK nao configurado"}

        payment_id = data.get("data", {}).get("id")
        if not payment_id:
            return {"status": "ignored", "reason": "no_payment_id"}

        try:
            payment = self._sdk.payment().get(payment_id)
            p = payment.get("response", {})

            status = p.get("status")
            ext_ref = p.get("external_reference", "")

            if status == "approved":
                self._process_approved_payment(ext_ref, p)
                return {"status": "approved", "payment_id": payment_id}
            elif status == "pending":
                return {"status": "pending", "payment_id": payment_id}
            else:
                return {"status": status, "payment_id": payment_id}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _process_approved_payment(self, external_ref: str, payment_data: Dict):
        """Processa pagamento aprovado: gera licenca e envia email."""
        payment_file = DATA_DIR / f"{external_ref}.json"
        if not payment_file.exists():
            return

        with open(payment_file, "r", encoding="utf-8") as f:
            payment_info = json.load(f)

        if payment_info.get("license_key"):
            return

        from bot.core.license_service import LicenseService
        license_key = LicenseService.generate_key()

        payment_info["license_key"] = license_key
        payment_info["status"] = "approved"
        payment_info["mp_payment_id"] = payment_data.get("id")
        payment_info["approved_at"] = datetime.utcnow().isoformat()

        with open(payment_file, "w", encoding="utf-8") as f:
            json.dump(payment_info, f, indent=2, ensure_ascii=False)

        self._send_license_email(
            email=payment_info["email"],
            name=payment_info["name"],
            license_key=license_key,
            plan=payment_info["plan"],
        )

    def _send_license_email(self, email: str, name: str, license_key: str, plan: str):
        """Envia email com a chave de licenca e instrucoes completas."""
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")

        if not smtp_user:
            print(f"[EMAIL SKIP] Chave para {email}: {license_key}")
            return

        plan_info = self.PLANS.get(plan, {})
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = email
        msg["Subject"] = f"BotDoProfessor — Sua chave de licenca ({plan_info.get('label', plan)})"

        download_url = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"
        success_url = "https://botdoprofessor.onrender.com/success?key=" + license_key

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
            .step-text {{ flex: 1; }}
            .step-text strong {{ color: #0c1b33; }}
            .step-text {{ color: #475569; font-size: 0.92em; }}
            .alert {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 0.88em; color: #92400e; }}
            .csv-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin: 16px 0; font-size: 0.88em; }}
            .csv-box code {{ background: #e2e8f0; padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }}
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
                <a href="{success_url}" class="btn">Ver instrucoes completas</a>
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
                    Duplo-clique no BotDoProfessor.exe. O Windows pode mostrar um aviso de seguranca — clique em "Mais informacoes" e depois em "Executar mesmo assim". Isso e normal para programas baixados da internet.
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
                    Digite o CPF que voce usa para acessar o SGE (so numeros, sem pontos ou traco). O programa tambem salva isso automaticamente.
                </div>
            </div>

            <div class="step">
                <div class="step-num">6</div>
                <div class="step-text">
                    <strong>Configure escola, turma e trimestre</strong><br>
                    O programa vai perguntar qual escola, turno, turma e trimestre. Voce pode apertar Enter para usar os valores padrao, ou digitar os dados corretos.
                </div>
            </div>

            <div class="step">
                <div class="step-num">7</div>
                <div class="step-text">
                    <strong>Escolha o tipo de lancamento</strong><br>
                    Digite <code>1</code> para <strong>Notas</strong> ou <code>2</code> para <strong>Plano de Aula</strong>. Para notas, voce pode importar de uma planilha CSV/Excel ou colar o link do Google Sheets.
                </div>
            </div>

            <h3 style="color:#0c1b33;margin-top:24px">Como preparar suas notas</h3>

            <div class="csv-box">
                <p><strong>Opcao 1 — Planilha CSV ou Excel:</strong></p>
                <p>Crie uma planilha com duas colunas:</p>
                <p>
                    <code>Aluno</code> — nome completo do aluno (como aparece no SGE)<br>
                    <code>Nota</code> — valor numerico (ex: 8.5, 7.0, 9.2)
                </p>
                <p style="margin-top:8px">
                    <strong>Exemplo:</strong><br>
                    <code>Aluno;Nota</code><br>
                    <code>Maria Silva;8.5</code><br>
                    <code>Joao Santos;7.0</code><br>
                    <code>Ana Oliveira;9.2</code>
                </p>
                <p style="margin-top:8px">
                    Salve como <code>.csv</code> (separado por virgula ou ponto-e-virgula) ou <code>.xlsx</code>.
                </p>
            </div>

            <div class="csv-box">
                <p><strong>Opcao 2 — Google Sheets:</strong></p>
                <p>
                    1. Crie uma planilha no Google Sheets com as colunas "Aluno" e "Nota"<br>
                    2. Clique em "Compartilhar" no canto superior direito<br>
                    3. Em "Quem tem acesso", selecione "Qualquer pessoa com o link"<br>
                    4. Copie o link da planilha<br>
                    5. Cole o link quando o programa pedir o caminho do arquivo
                </p>
            </div>

            <div class="alert">
                <strong>Dica:</strong> O programa lembra suas configuracoes. Na segunda vez que voce usar, basta digitar <code>1</code> ou <code>2</code> e ele ja sabe tudo.
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
        except Exception as e:
            print(f"[EMAIL ERROR] {e}")

    def verify_manual_payment(self, reference: str) -> Dict:
        """Verifica se pagamento manual foi confirmado."""
        payment_file = DATA_DIR / f"{reference}.json"
        if not payment_file.exists():
            return {"status": "not_found"}

        with open(payment_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {
            "status": data.get("status", "pending"),
            "license_key": data.get("license_key"),
            "plan": data.get("plan"),
        }

    def approve_manual_payment(self, reference: str) -> Dict:
        """Admin aprova pagamento manual (Pix)."""
        payment_file = DATA_DIR / f"{reference}.json"
        if not payment_file.exists():
            return {"error": "Pagamento nao encontrado"}

        with open(payment_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("license_key"):
            return {"license_key": data["license_key"], "status": "already_approved"}

        from bot.core.license_service import LicenseService
        license_key = LicenseService.generate_key()

        data["license_key"] = license_key
        data["status"] = "approved"
        data["approved_at"] = datetime.utcnow().isoformat()

        with open(payment_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._send_license_email(
            email=data["email"],
            name=data["name"],
            license_key=license_key,
            plan=data["plan"],
        )

        return {"license_key": license_key, "status": "approved"}

    def list_pending_payments(self):
        """Lista pagamentos manuais pendentes."""
        pending = []
        for f in DATA_DIR.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if data.get("status") == "pending":
                    data["file"] = f.name
                    pending.append(data)
        return pending

    @staticmethod
    def _generate_external_ref(plan: str, email: str, cpf: str) -> str:
        raw = f"{plan}_{email}_{cpf}_{datetime.utcnow().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _generate_pix_payload(amount: float) -> str:
        return f"Chave Pix: {os.environ.get('PIX_KEY', 'informar PIX_KEY no .env')}\nValor: R$ {amount:.2f}\nNome: {os.environ.get('PIX_NAME', 'BotDoProfessor')}"

    def _save_payment(self, plan, email, cpf, name, method, reference, status="created"):
        info = {
            "plan": plan,
            "email": email,
            "cpf": cpf,
            "name": name,
            "method": method,
            "reference": reference,
            "status": status,
            "created_at": datetime.utcnow().isoformat(),
        }
        ref = hashlib.sha256(f"{email}_{cpf}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:16]
        with open(DATA_DIR / f"{ref}.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

    def _save_payment_by_id(self, plan_info, name, email, cpf, ext_ref, method, mp_payment_id):
        info = {
            "plan": plan_info.get("label", ""),
            "email": email,
            "cpf": cpf,
            "name": name,
            "method": method,
            "reference": ext_ref,
            "mp_payment_id": mp_payment_id,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        with open(DATA_DIR / f"{ext_ref}.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _create_db_payment_request(plan, name, email, cpf, amount, payment_method):
        try:
            from flask import current_app
            from bot.models.database import db
            from bot.models.payment_request import PaymentRequest
            if not current_app:
                return
            reference = hashlib.sha256(
                f"{email}_{cpf}_{datetime.utcnow().isoformat()}".encode()
            ).hexdigest()[:16]
            pr = PaymentRequest(
                name=name, email=email, cpf=cpf, plan=plan,
                amount=float(amount), payment_method=payment_method,
                reference=reference, status="pending",
            )
            db.session.add(pr)
            db.session.commit()
        except Exception as e:
            print(f"[DB WARN] Falha ao criar PaymentRequest: {e}")
