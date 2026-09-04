import threading
import time
from datetime import datetime, timedelta


REMINDER_DAYS_BEFORE = 3
CHECK_INTERVAL = 3600  # 1 hora


def _build_reminder_email(name, plan, days_remaining, expires_at, checkout_url):
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif">
<div style="max-width:560px;margin:30px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">
    <div style="background:linear-gradient(135deg,#0f3460,#16213e);padding:28px 32px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:1.6rem">BotDoProfessor</h1>
        <p style="color:#94a3b8;margin:6px 0 0;font-size:.95rem">Sua assinatura esta acabando</p>
    </div>
    <div style="padding:28px 32px">
        <p>Ola <strong>{name}</strong>,</p>
        <p>Sua assinatura do plano <strong>{plan}</strong> expira em <strong>{days_remaining} dia(s)</strong> ({expires_at}).</p>
        <p>Para continuar usando o BotDoProfessor sem interrupcoes, renove sua assinatura agora.</p>
        <div style="text-align:center;margin:24px 0">
            <a href="{checkout_url}" style="display:inline-block;padding:14px 32px;background:#e94560;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:1em">Renovar assinatura</a>
        </div>
        <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;border-radius:0 8px 8px 0;margin:18px 0;font-size:.88em;color:#92400e">
            <strong>Importante:</strong> apos a expiracao, o acesso ao programa sera bloqueado. Renove antes para nao perder o acesso.
        </div>
        <p style="color:#64748b;font-size:.88em">Se ja renovou, ignore este email.</p>
    </div>
    <div style="padding:18px 24px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;font-size:.85em;color:#94a3b8">
        BotDoProfessor — Lançamento de notas automatizado
    </div>
</div>
</body>
</html>"""


def _send_reminders(app):
    with app.app_context():
        from bot.models.database import db
        from bot.models.license import License
        from bot.models.user import User
        from bot.utils.email_sender import send_email

        now = datetime.utcnow()
        cutoff = now + timedelta(days=REMINDER_DAYS_BEFORE)

        licenses = License.query.filter(
            License.active == True,
            License.reminder_sent == False,
            License.expires_at <= cutoff,
            License.expires_at > now,
        ).all()

        if not licenses:
            return

        checkout_url = "https://botdoprofessor.onrender.com/checkout"
        sent = 0

        for lic in licenses:
            user = lic.user if lic.user else None
            if not user or not user.email:
                continue

            days_remaining = max(0, (lic.expires_at - now).days)
            expires_str = lic.expires_at.strftime("%d/%m/%Y")
            plan_label = lic.plan

            html = _build_reminder_email(
                name=user.username.split("@")[0] if "@" in user.username else user.username,
                plan=plan_label,
                days_remaining=days_remaining,
                expires_at=expires_str,
                checkout_url=checkout_url,
            )

            ok = send_email(
                to_email=user.email,
                subject=f"BotDoProfessor — Sua assinatura expira em {days_remaining} dia(s)",
                html_content=html,
            )

            if ok:
                lic.reminder_sent = True
                sent += 1

        if sent:
            db.session.commit()
            print(f"[REMINDER] {sent} lembrete(s) enviado(s)", flush=True)


def start_reminder_scheduler(app):
    def _loop():
        while True:
            try:
                _send_reminders(app)
            except Exception as e:
                print(f"[REMINDER ERROR] {e}", flush=True)
            time.sleep(CHECK_INTERVAL)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("[REMINDER] Scheduler de lembretes iniciado (verifica a cada 1h)", flush=True)
