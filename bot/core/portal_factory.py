from typing import Optional
from bot.core.portal_adapter import PortalAdapter
from bot.core.sge_adapter import SGEAdapter
from bot.core.professor_online_adapter import ProfessorOnlineAdapter
from bot.core.custom_adapter import CustomPortalAdapter
from bot.core.portal_discovery import PortalDiscovery
from bot.core.portal_memory import PortalMemory
from pathlib import Path
import json

KNOWN_PORTALS = {
    "sge": SGEAdapter,
    "professor_online": ProfessorOnlineAdapter,
}

# Nome magico usado para exigir o modo hibrido em um portal generico.
HYBRID_MODE_KEY = "hybrid"
# Por padrao, portais conhecidos (SGE, Professor Online) nunca usam o hibrido.
HYBRID_DEFAULT = False

MEMORY_DIR = Path.home() / ".bot_local" / "portal_memory"


def get_adapter(portal: str, config: dict = None, hybrid: bool = None) -> PortalAdapter:
    """Factory que retorna o adapter correto para o portal.

    Args:
        portal: Nome do portal (ex: 'SGE', 'SGP', 'ieducar')
        config: Configuracao adicional (URL, selectors, etc.)
        hybrid: Forca o modo hibrido (screenshot+DOM) mesmo para portais
            com memoria. Se None, usa o comportamento padrao.
    """
    key = portal.lower().strip()

    # SGE e Professor Online SEMPRE usam seus fluxos DOM dedicados.
    # O modo hibrido nao se aplica a eles (evita quebrar o que ja funciona).
    if key in KNOWN_PORTALS:
        if hybrid:
            raise ValueError(
                f"O portal '{portal}' possui adapter dedicado (nativo) e nao usa modo hibrido."
            )
        adapter_class = KNOWN_PORTALS[key]
        if key == "sge":
            url = (config or {}).get("url", "")
            return adapter_class(base_url=url)
        if key == "professor_online":
            url = (config or {}).get("url", "")
            return adapter_class(base_url=url)
        return adapter_class()

    # Portal listado como "novo" -> modo hibrido como abordagem principal.
    if key == HYBRID_MODE_KEY:
        return _build_hybrid(portal, config)

    memory = PortalMemory(portal)

    if hybrid:
        return _build_hybrid(portal, config)

    if memory.data.get("columns") or memory.data.get("selectors"):
        return CustomPortalAdapter(portal, config or {})

    memory_dir = MEMORY_DIR / key / "discovered_config.json"
    if memory_dir.exists():
        with open(memory_dir, "r", encoding="utf-8") as f:
            saved_config = json.load(f)
        merged = {**saved_config, **(config or {})}
        return CustomPortalAdapter(portal, merged)

    return CustomPortalAdapter(portal, config or {})


def _build_hybrid(portal: str, config: dict) -> PortalAdapter:
    """Constroi o adapter hibrido para um portal generico/novo."""
    from bot.core.hybrid_adapter import HybridPortalAdapter
    return HybridPortalAdapter(portal, config or {})


def discover_portal(url: str, ai_provider: str = "gemini", ai_config: dict = None) -> Optional[dict]:
    """Descobre a estrutura de um portal via IA."""
    discovery = PortalDiscovery(ai_provider=ai_provider, ai_config=ai_config)
    config = discovery.discover_from_url(url)
    if config:
        discovery.save_discovery(config)
    return config


def list_portals() -> list:
    """Lista todos os portais conhecidos."""
    portals = list(KNOWN_PORTALS.keys())

    if MEMORY_DIR.exists():
        for d in MEMORY_DIR.iterdir():
            if d.is_dir() and d.name not in portals:
                portals.append(d.name)

    return sorted(set(portals))
