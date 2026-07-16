#!/usr/bin/env python3
"""BotDoProfessor-Local — CLI principal."""

import os
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FORMAT, level=level)
    log_file = Path.home() / ".bot_local" / "logs" / "bot.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(fh)


def cmd_serve(args):
    from app import create_app
    setup_logging(args.verbose)
    app = create_app()
    print(f"BotDoProfessor-Local API rodando em http://0.0.0.0:{args.port}")
    app.run(debug=args.debug, host="0.0.0.0", port=args.port)


def cmd_health(args):
    from app import create_app
    setup_logging(args.verbose)
    app = create_app()
    with app.app_context():
        from bot.ops.monitoring import HealthChecker
        checker = HealthChecker()
        result = checker.full_check()
        for key, val in result.items():
            if isinstance(val, dict):
                status = val.get("status", "unknown")
                msg = val.get("message", val)
                print(f"  {key}: {status} — {msg}")
            else:
                print(f"  {key}: {val}")


def cmd_backup(args):
    from app import create_app
    setup_logging(args.verbose)
    app = create_app()
    with app.app_context():
        from bot.ops.monitoring import BackupManager
        mgr = BackupManager()
        path = mgr.create_backup(label=args.label or "")
        print(f"Backup criado: {path}")


def cmd_discover(args):
    from app import create_app
    setup_logging(args.verbose)
    app = create_app()
    with app.app_context():
        from bot.core.portal_factory import discover_portal
        from config.settings import AI_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY
        config = discover_portal(
            args.url,
            ai_provider=AI_PROVIDER,
            ai_config={"api_key": GEMINI_API_KEY or OPENAI_API_KEY},
        )
        if config:
            import json
            print(json.dumps(config, indent=2, ensure_ascii=False))
        else:
            print("Descoberta falhou. Verifique a URL e as chaves de IA.")


def cmd_seed(args):
    from app import create_app
    setup_logging(args.verbose)
    app = create_app()
    with app.app_context():
        from bot.models.database import db
        from bot.models.user import User
        from bot.core.license_service import LicenseService
        if not User.query.filter_by(username=args.username).first():
            user = User(username=args.username, email=args.email, profile=args.profile)
            user.set_password(args.password)
            db.session.add(user)
            db.session.commit()
            print(f"Usuario '{args.username}' criado (perfil: {args.profile})")
            if args.activate_license:
                lic = LicenseService.activate(user.id, args.activate_license)
                print(f"Licenca ativada: {lic.license_key}")
        else:
            print(f"Usuario '{args.username}' ja existe")


def main():
    parser = argparse.ArgumentParser(description="BotDoProfessor-Local")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Iniciar API")
    p_serve.add_argument("-p", "--port", type=int, default=5000)
    p_serve.add_argument("--debug", action="store_true")
    p_serve.add_argument("-v", "--verbose", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_health = sub.add_parser("health", help="Verificar saude do sistema")
    p_health.add_argument("-v", "--verbose", action="store_true")
    p_health.set_defaults(func=cmd_health)

    p_backup = sub.add_parser("backup", help="Criar backup")
    p_backup.add_argument("--label", default="")
    p_backup.add_argument("-v", "--verbose", action="store_true")
    p_backup.set_defaults(func=cmd_backup)

    p_discover = sub.add_parser("discover", help="Descobrir estrutura de portal via IA")
    p_discover.add_argument("url", help="URL do portal")
    p_discover.add_argument("-v", "--verbose", action="store_true")
    p_discover.set_defaults(func=cmd_discover)

    p_seed = sub.add_parser("seed", help="Criar usuario e licenca iniciais")
    p_seed.add_argument("--username", default="admin")
    p_seed.add_argument("--email", default="admin@botlocal.com")
    p_seed.add_argument("--password", default="admin123")
    p_seed.add_argument("--profile", default="admin", choices=["admin", "operador", "auditor"])
    p_seed.add_argument("--activate-license", default="", help="Plano para ativar (ex: 1ano)")
    p_seed.add_argument("-v", "--verbose", action="store_true")
    p_seed.set_defaults(func=cmd_seed)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
