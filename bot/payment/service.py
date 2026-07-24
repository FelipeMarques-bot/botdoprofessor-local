import os
import json
import hashlib
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

        from bot.models.license import License
        from bot.models.database import db
        plan = payment_info.get("plan", "")
        if plan:
            lic = License.create(user_id=None, plan=plan, key=license_key)
            db.session.add(lic)
            db.session.commit()

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
        """Envia email com a chave de licenca via Brevo API (fallback SMTP)."""
        from config.settings import PLANOS
        plan_info = PLANOS.get(plan, self.PLANS.get(plan, {}))
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

            <p style="text-align:center">
                <a href="{download_url}" class="btn">Baixar o programa</a>
            </p>

            <div class="section">
                <h3>PRIMEIRO: O que e o BotDoProfessor?</h3>
                <p style="color:#475569;font-size:0.92em">
                    E um programa que automatiza o lancamento de <strong>notas</strong> e <strong>planos de aula</strong> no sistema SGE da sua escola. Ele abre o navegador, entra no SGE com seus dados e faz o lancamento automaticamente — voce so precisa preparar uma planilha com as notas.
                </p>
            </div>

            <h3 style="color:#0c1b33;margin-top:28px">Como instalar e usar — passo a passo</h3>

            <div class="step">
                <div class="step-num">1</div>
                <div class="step-text">
                    <strong>Baixe o programa</strong><br>
                    Clique no botao acima ou copie e cole este link no seu navegador:<br>
                    <a href="{download_url}">{download_url}</a><br><br>
                    O arquivo <strong>BotDoProfessor.exe</strong> tem cerca de 140MB. Ele sera salvo na pasta <strong>Downloads</strong> do seu computador.
                </div>
            </div>

            <div class="step">
                <div class="step-num">2</div>
                <div class="step-text">
                    <strong>Encontre o arquivo baixado</strong><br>
                    Abra a pasta <strong>Downloads</strong> (ou a pasta onde o navegador salvou). Procure por um arquivo chamado <strong>BotDoProfessor.exe</strong> com um icone de robo.
                </div>
            </div>

            <div class="step">
                <div class="step-num">3</div>
                <div class="step-text">
                    <strong>Execute o programa</strong><br>
                    Duplo-clique (clique duas vezes rapido) no arquivo <strong>BotDoProfessor.exe</strong>.
                </div>
            </div>

            <div class="warn">
                <strong>Aviso de seguranca do Windows:</strong> O Windows pode mostrar uma tela dizendo "O Windows protegeu seu computador". Isso e <strong>normal</strong> para programas baixados da internet. Para continuar:<br><br>
                1. Clique em <strong>"Mais informacoes"</strong> (embaixo)<br>
                2. Clique em <strong>"Executar mesmo assim"</strong><br><br>
                <em>O programa e seguro — nao contem virus.</em>
            </div>

            <div class="step">
                <div class="step-num">4</div>
                <div class="step-text">
                    <strong>Aguarde a primeira configuracao</strong><br>
                    Na primeira vez que voce abre o programa, ele instala automaticamente o navegador Chromium (cerca de 180MB). Isso demora <strong>aproximadamente 2 minutos</strong> e so acontece <strong>uma unica vez</strong>. Voce vera mensagens como:<br><br>
                    <code>[i] Baixando navegador Chromium (~180MB, primeira vez)...</code><br>
                    <code>[OK] Navegador instalado com sucesso!</code><br><br>
                    <strong>Nao feche a janela</strong> enquanto estiver baixando. Aguarde ate ver a mensagem de sucesso.
                </div>
            </div>

            <div class="step">
                <div class="step-num">5</div>
                <div class="step-text">
                    <strong>Cole a chave de licenca</strong><br>
                    O programa vai pedir sua chave de licenca. <strong>Volte para este email</strong>, selecione a chave que aparece la em cima (clique e arraste o mouse sobre ela), copie (pressione <code>Ctrl+C</code> ou clique com o botao direito e escolha "Copiar"), e cole no programa (pressione <code>Ctrl+V</code> ou clique com o botao direito e escolha "Colar").<br><br>
                    A chave e salva automaticamente — <strong>nas proximas vezes nao precisa colar de novo</strong>.
                </div>
            </div>

            <div class="tip">
                <strong>Dica:</strong> Se voce copiar a chave e o programa nao aceitar, verifique se nao copiou espacos extras antes ou depois da chave. A chave deve ser colada exatamente como aparece no email.
            </div>

            <div class="step">
                <div class="step-num">6</div>
                <div class="step-text">
                    <strong>Informe seu CPF</strong><br>
                    Digite o CPF que voce usa para acessar o SGE. Digite <strong>so numeros</strong>, sem pontos, sem traco, sem espacos. Exemplo:<br><br>
                    <code>12345678901</code> (11 numeros)<br><br>
                    O CPF tambem e salvo automaticamente.
                </div>
            </div>

            <div class="step">
                <div class="step-num">7</div>
                <div class="step-text">
                    <strong>Configure escola, turma e trimestre</strong><br>
                    O programa vai perguntar:<br>
                    <ul>
                        <li><strong>Escola:</strong> Digite o nome da escola como aparece no SGE</li>
                        <li><strong>Turno:</strong> Manha, Tarde ou Noite</li>
                        <li><strong>Turma:</strong> Ex: "5o Ano A", "9o Ano B"</li>
                        <li><strong>Trimestre:</strong> Ex: "1o Trimestre", "2o Trimestre"</li>
                    </ul>
                    Se nao souber, pressione <strong>Enter</strong> para usar o valor padrao. Essas configuracoes sao salvas — na proxima vez nao precisa digitar tudo de novo.
                </div>
            </div>

            <div class="step">
                <div class="step-num">8</div>
                <div class="step-text">
                    <strong>Escolha o tipo de lancamento</strong><br>
                    O programa vai perguntar o que voce quer lancar:<br>
                    <ul>
                        <li>Digite <code>1</code> para <strong>Lancar Notas</strong></li>
                        <li>Digite <code>2</code> para <strong>Lancar Plano de Aula</strong></li>
                    </ul>
                </div>
            </div>

            <div class="section">
                <h3>COMO PREPARAR SUAS NOTAS</h3>
                <p style="color:#475569;font-size:0.92em;margin-bottom:12px">
                    Para lancar notas, voce precisa de uma planilha com os nomes dos alunos e as notas. Existem tres opcoes:
                </p>

                <div class="csv-box">
                    <p><strong>Opcao 1 — Planilha Excel (.xlsx):</strong></p>
                    <p>Abra o Excel e crie uma planilha com duas colunas:</p>
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
                        Salve como <code>.xlsx</code> ou <code>.csv</code>. Coloque o arquivo na pasta <strong>Documents</strong> ou na <strong>Area de Trabalho</strong> para encontrar facilmente.
                    </p>
                </div>

                <div class="csv-box">
                    <p><strong>Opcao 2 — Google Sheets (online):</strong></p>
                    <p>1. Acesse <a href="https://sheets.google.com">sheets.google.com</a></p>
                    <p>2. Crie uma nova planilha</p>
                    <p>3. Na primeira linha, digite: <code>Aluno</code> na coluna A e <code>Nota</code> na coluna B</p>
                    <p>4. Preencha com os nomes e notas dos alunos</p>
                    <p>5. Clique em <strong>"Compartilhar"</strong> (canto superior direito)</p>
                    <p>6. Em "Quem tem acesso", clique em <strong>"Qualquer pessoa com o link"</strong></p>
                    <p>7. Clique em <strong>"Copiar link"</strong></p>
                    <p>8. Cole o link quando o programa pedir o caminho do arquivo</p>
                </div>

                <div class="csv-box">
                    <p><strong>Opcao 3 — Imagem / Foto:</strong></p>
                    <p>Se voce tiver uma foto ou print das notas (por exemplo, uma foto de um caderno ou tela), o programa pode ler a imagem automaticamente e extrair as notas. Basta informar o caminho da imagem quando o programa pedir.</p>
                    <p style="margin-top:8px"><em>Nota: esta funcionalidade requer configuracao de IA (Gemini, GPT-4o ou Ollama).</em></p>
                </div>
            </div>

            <div class="section">
                <h3>PERGUNTAS FREQUENTES</h3>

                <p style="color:#475569;font-size:0.92em">
                    <strong>O programa e seguro?</strong><br>
                    Sim. O BotDoProfessor roda apenas no seu computador, nao envia seus dados para terceiros, e o codigo e aberto (pode ser verificado).
                </p>

                <p style="color:#475569;font-size:0.92em;margin-top:12px">
                    <strong>Precisa de internet?</strong><br>
                    Sim. O programa precisa de internet para conectar no SGE e lancar as notas.
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
                    Sim! Na segunda vez que voce usar, basta digitar <code>1</code> ou <code>2</code> e ele ja sabe a escola, turma, trimestre e CPF.
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

        from bot.models.license import License
        from bot.models.database import db
        plan = data.get("plan", "")
        if plan:
            lic = License.create(user_id=None, plan=plan, key=license_key)
            db.session.add(lic)
            db.session.commit()

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
