from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _default_literal(column, dialect: str):
    """Converte o default da coluna em literal SQL, quando possivel.

    Defaults que sao callables (ex.: datetime.utcnow) retornam None: nesse
    caso a coluna e adicionada sem DEFAULT (permanece NULL nas linhas antigas).
    """
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    arg = default.arg
    if isinstance(arg, bool):
        if dialect == "postgresql":
            return "TRUE" if arg else "FALSE"
        return "1" if arg else "0"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        escaped = arg.replace("'", "''")
        return f"'{escaped}'"
    return None


def _auto_migrate(app):
    """Adiciona colunas faltantes em tabelas ja existentes.

    Funciona em SQLite e PostgreSQL (ao contrario do antigo _migrate_reminder_sent,
    que so funcionava no Postgres por usar information_schema). Assim o banco local
    nao fica desatualizado e o painel admin nao quebra ao inserir registros.
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        engine = db.engine
        dialect_obj = engine.dialect
        dialect = dialect_obj.name
        try:
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names())
        except Exception as e:
            print(f"[MIGRATE] Aviso: nao foi possivel inspecionar o banco: {e}")
            return

        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # tabela nova: db.create_all() ja criou completa
            try:
                existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            except Exception as e:
                print(f"[MIGRATE] Aviso ao ler colunas de {table.name}: {e}")
                continue
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(dialect=dialect_obj)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}'
                default_literal = _default_literal(column, dialect)
                if default_literal is not None:
                    ddl += f" DEFAULT {default_literal}"
                try:
                    with engine.begin() as conn:
                        conn.execute(text(ddl))
                    print(f"[MIGRATE] Coluna {table.name}.{column.name} adicionada")
                except Exception as e:
                    print(f"[MIGRATE] Aviso ao adicionar {table.name}.{column.name}: {e}")


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _auto_migrate(app)
