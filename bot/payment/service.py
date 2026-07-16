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
        access_token = os.environ.get("MP_ACCESS_TOKEN", "")
        if access_token and mercadopago:
            self._sdk = mercadopago.SDK(access_token)

    def create_preference(self, plan: str, name: str, email: str, cpf: str,
                          payment_method: str = "card") -> Dict:
        """Cria preferencia de pagamento no Mercado Pago."""
        plan_info = self.PLANS.get(plan)
        if not plan_info:
            return {"error": "Plano desconhecido"}

        if not self._sdk:
            return self._create_manual_payment(plan, name, email, cpf, payment_method)

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
                        "number": cpf.replace(".", "").replace("-", ""),
                    },
                },
                "payment_methods": {},
                "external_reference": self._generate_external_ref(plan, email, cpf),
                "notification_url": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/api/webhook/mercadopago",
                "back_urls": {
                    "success": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/success",
                    "pending": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/success",
                    "failure": f"{os.environ.get('APP_URL', 'http://localhost:5000')}/",
                },
                "auto_return": "approved",
            }

            if payment_method == "pix":
                preference_data["payment_methods"]["excluded_payment_types"] = [
                    {"id": "credit_card"},
                    {"id": "debit_card"},
                    {"id": "ticket"},
                ]
            elif payment_method == "card":
                preference_data["payment_methods"]["excluded_payment_types"] = [
                    {"id": "ticket"},
                ]

            result = self._sdk.preference().create(preference_data)
            init_point = result.get("response", {}).get("init_point", "")

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
        """Envia email com a chave de licenca."""
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
        msg["Subject"] = f"BotDoProfessor - Sua chave de licenca ({plan_info.get('label', plan)})"

        html = f"""
        <html>
        <body style="font-family:Arial,sans-serif;padding:20px">
            <h2 style="color:#0f3460">BotDoProfessor</h2>
            <p>Ola <b>{name}</b>,</p>
            <p>Seu pagamento foi confirmado! Aqui esta sua chave de licenca:</p>
            <div style="background:#f0f0f0;padding:16px;border-radius:8px;font-family:monospace;font-size:1.2em;text-align:center;margin:20px 0;border:2px dashed #ccc">
                {license_key}
            </div>
            <p><b>Como usar:</b></p>
            <ol>
                <li>Abra o BotDoProfessor</li>
                <li>Va em Configuracoes > Licenca</li>
                <li>Cole a chave acima</li>
                <li>Configure seu CPF e senha do SGE</li>
            </ol>
            <p style="color:#999;font-size:0.85em;margin-top:30px">
                Duvidas? Responda este email.<br>
                BotDoProfessor - Automatize suas notas
            </p>
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
