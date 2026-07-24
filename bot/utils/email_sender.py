import os
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(to_email, subject, html_content):
    """Envia email via SMTP. Retorna True se enviou com sucesso, False caso contrario."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not smtp_user or not smtp_pass:
        print(f"[EMAIL SKIP] SMTP nao configurado (USER={'ok' if smtp_user else 'vazio'}, PASS={'ok' if smtp_pass else 'vazio'}). Chave para {to_email}", flush=True)
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
        print(f"[EMAIL ERROR] Falha ao enviar para {to_email}: {e}", flush=True)
        return False
