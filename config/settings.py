import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
EVIDENCIAS_DIR = BASE_DIR / "evidencias"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_db_url = os.environ.get("DATABASE_URL", "")
if _db_url and not _db_url.startswith("sqlite:///data/"):
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
else:
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR / 'bot_local.db'}"
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = os.environ.get("SECRET_KEY", "bot-local-change-in-production")

LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "")

AI_PROVIDER = os.environ.get("AI_PROVIDER", "local")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")

PLANOS = {
    # Linha "1 Portal" (apenas SGE)
    "mensal": {"dias": 30, "preco": 49.90, "label": "Mensal 1 Portal", "portais": 1, "multi_portal": False},
    "1ano": {"dias": 365, "preco": 479.04, "label": "1 Ano 1 Portal", "portais": 1, "multi_portal": False},
    "2anos": {"dias": 730, "preco": 838.32, "label": "2 Anos 1 Portal", "portais": 1, "multi_portal": False},
    # Linha "Todos os Portais" (SGE + Professor Online + novos via IA)
    "mensal_todos": {"dias": 30, "preco": 79.90, "label": "Mensal Todos os Portais", "portais": -1, "multi_portal": True},
    "1ano_todos": {"dias": 365, "preco": 767.04, "label": "1 Ano Todos os Portais", "portais": -1, "multi_portal": True},
    "2anos_todos": {"dias": 730, "preco": 1342.32, "label": "2 Anos Todos os Portais", "portais": -1, "multi_portal": True},
    # Planos internos da licenca (nao vendidos diretamente)
    "basico": {"dias": 30, "preco": 49.90, "label": "Basico", "portais": 1, "ai_assist": False, "multi_portal": False},
    "profissional": {"dias": 30, "preco": 99.90, "label": "Profissional", "portais": 3, "ai_assist": True, "multi_portal": True},
    "premium": {"dias": 30, "preco": 199.90, "label": "Premium", "portais": -1, "ai_assist": True, "multi_portal": True},
}

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
