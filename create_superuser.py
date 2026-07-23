#!/usr/bin/env python3
"""Cria um usuario SuperUser (admin) no banco de dados."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=False)


def main():
    from app import create_app
    from bot.models.database import db
    from bot.models.user import User

    app = create_app()

    print("=" * 50)
    print("  Criar SuperUser — BotDoProfessor")
    print("=" * 50)
    print()

    with app.app_context():
        username = input("  Username: ").strip()
        if not username:
            print("  [ER] Username obrigatorio.")
            return

        existing = User.query.filter_by(username=username).first()
        if existing:
            print(f"  [ER] Username '{username}' ja existe.")
            return

        email = input("  Email: ").strip()
        if not email:
            print("  [ER] Email obrigatorio.")
            return

        import getpass
        password = getpass.getpass("  Senha: ")
        if not password:
            print("  [ER] Senha obrigatoria.")
            return

        confirm = getpass.getpass("  Confirmar senha: ")
        if password != confirm:
            print("  [ER] Senhas nao conferem.")
            return

        admin = User(username=username, email=email, profile="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        print()
        print("  [OK] SuperUser criado com sucesso!")
        print()
        print(f"  Username: {username}")
        print(f"  Email:    {email}")
        print(f"  Profile:  admin")
        print()
        print("  Acesse: http://localhost:5000/admin")
        print()


if __name__ == "__main__":
    main()
