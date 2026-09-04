from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _migrate_reminder_sent(app):
    """Adiciona coluna reminder_sent na tabela licenses se nao existir."""
    with app.app_context():
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='licenses' AND column_name='reminder_sent'"
                ))
                if not result.fetchone():
                    conn.execute(text("ALTER TABLE licenses ADD COLUMN reminder_sent BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                    print("[MIGRATE] Coluna reminder_sent adicionada em licenses")
        except Exception as e:
            print(f"[MIGRATE] Aviso: {e}")


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate_reminder_sent(app)
