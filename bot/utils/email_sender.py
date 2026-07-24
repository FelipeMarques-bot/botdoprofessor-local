import os
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests


def send_email(to_email, subject, html_content):
    """Envia email tentando Brevo API primeiro, depois SMTP como fallback.

    Retorna True se enviou com sucesso, False caso contrario.
    """
    result = _send_via_brevo(to_email, subject, html_content)
    if result is not None:
        return result

    return _send_via_smtp(to_email, subject, html_content)


def _send_via_brevo(to_email, subject, html_content):
    """Tenta enviar via Brevo API. Retorna True/False ou None se nao configurado."""
    api_key = os.environ.get("BREVO_API_KEY", "")
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "")
    sender_name = os.environ.get("BREVO_SENDER_NAME", "BotDoProfessor")

    if not api_key or not sender_email:
        return None

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            print(f"[EMAIL OK] Enviado para {to_email} via Brevo", flush=True)
            return True
        else:
            print(f"[EMAIL WARN] Brevo retornou {resp.status_code}: {resp.text[:200]}. Tentando SMTP...", flush=True)
            return None
    except Exception as e:
        print(f"[EMAIL WARN] Brevo falhou: {e}. Tentando SMTP...", flush=True)
        return None


def _send_via_smtp(to_email, subject, html_content):
    """Envia via SMTP (Gmail, etc). Funciona apos upgrade do Render."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_user or not smtp_pass:
        print(f"[EMAIL SKIP] SMTP nao configurado (USER={'ok' if smtp_user else 'vazio'}, PASS={'ok' if smtp_pass else 'vazio'})", flush=True)
        return False

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html"))

    try:
        socket.setdefaulttimeout(15)
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        print(f"[EMAIL OK] Enviado para {to_email} via SMTP ({smtp_host})", flush=True)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] SMTP falhou para {to_email}: {e}", flush=True)
        return False
