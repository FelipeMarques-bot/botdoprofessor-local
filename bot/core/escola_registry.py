"""Registro de escolas por portal (mapa escola -> portal).

Persistido em ~/.sge_bot/escolas.json. Usado pelo painel para o roteamento
automatico (portal "Auto"): apos um login bem-sucedido no Professor Online,
as escolas do professor sao registradas aqui; depois, ao filtrar por escola,
o painel sabe em qual portal executar sem exigir a escolha manual.

Estrutura do arquivo:
    {
      "escolas": {
        "<normalizado>": {
          "nome": "EEB REGENTE FEIJO",
          "portal": "professor_online",
          "atualizado_em": "2026-08-13T..."
        }
      }
    }
"""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REGISTRY_PATH = Path.home() / ".sge_bot" / "escolas.json"

PORTAL_SGE = "sge"
PORTAL_PROFESSOR_ONLINE = "professor_online"


def _normalize(nome: str) -> str:
    """Normaliza o nome da escola para casamento tolerante a caixa/acento."""
    text = unicodedata.normalize("NFD", (nome or "").strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", text)


def load_registry() -> Dict:
    if not REGISTRY_PATH.exists():
        return {"escolas": {}}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("escolas"), dict):
            return {"escolas": {}}
        return data
    except (OSError, ValueError):
        return {"escolas": {}}


def save_registry(data: Dict) -> None:
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def registrar_escola(nome: str, portal: str) -> bool:
    """Registra uma escola no portal informado. Retorna True se mudou algo."""
    chave = _normalize(nome)
    if not chave or not portal:
        return False
    data = load_registry()
    atual = data["escolas"].get(chave, {})
    if atual.get("portal") == portal:
        return False
    data["escolas"][chave] = {
        "nome": (nome or "").strip(),
        "portal": portal,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
    }
    save_registry(data)
    return True


def portal_da_escola(nome: str) -> Optional[str]:
    """Retorna o portal ('sge', 'professor_online', ...) da escola, ou None."""
    chave = _normalize(nome)
    if not chave:
        return None
    data = load_registry()
    entry = data["escolas"].get(chave)
    return (entry or {}).get("portal") or None


def escolas_do_portal(portal: str) -> List[str]:
    data = load_registry()
    return [
        entry.get("nome", "")
        for entry in data["escolas"].values()
        if entry.get("portal") == portal and entry.get("nome")
    ]


def listar_registros() -> List[Dict]:
    return [
        {**entry, "escola": entry.get("nome", "")}
        for entry in load_registry()["escolas"].values()
    ]
