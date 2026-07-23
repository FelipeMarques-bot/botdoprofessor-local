import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
EVIDENCIAS_DIR = BASE_DIR / "evidencias"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url or _db_url.startswith("sqlite:///data/"):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR / 'bot_local.db'}"
else:
    SQLALCHEMY_DATABASE_URI = _db_url
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = os.environ.get("SECRET_KEY", "bot-local-change-in-production")

LICENSE_SERVER_URL = os.environ.get("LICENSE_SERVER_URL", "")

AI_PROVIDER = os.environ.get("AI_PROVIDER", "local")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")

PLANOS = {
    "basico": {"dias": 30, "preco": 49.90, "label": "Basico", "portais": 1, "ai_assist": False, "multi_portal": False},
    "profissional": {"dias": 30, "preco": 99.90, "label": "Profissional", "portais": 3, "ai_assist": True, "multi_portal": True},
    "premium": {"dias": 30, "preco": 199.90, "label": "Premium", "portais": -1, "ai_assist": True, "multi_portal": True},
    "1ano": {"dias": 365, "preco": 99.90, "label": "1 ano"},
    "2anos": {"dias": 730, "preco": 169.83, "label": "2 anos"},
    "3anos": {"dias": 1095, "preco": 224.78, "label": "3 anos"},
}

ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
