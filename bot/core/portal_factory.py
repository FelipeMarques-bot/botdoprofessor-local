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

MEMORY_DIR = Path.home() / ".bot_local" / "portal_memory"


def get_adapter(portal: str, config: dict = None) -> PortalAdapter:
    """Factory que retorna o adapter correto para o portal.

    Args:
        portal: Nome do portal (ex: 'SGE', 'SGP', 'ieducar')
        config: Configuracao adicional (URL, selectors, etc.)
    """
    key = portal.lower().strip()

    if key in KNOWN_PORTALS:
        adapter_class = KNOWN_PORTALS[key]
        if key == "sge":
            url = (config or {}).get("url", "")
            return adapter_class(base_url=url)
        if key == "professor_online":
            url = (config or {}).get("url", "")
            return adapter_class(base_url=url)
        return adapter_class()

    memory = PortalMemory(portal)
    if memory.data.get("columns") or memory.data.get("selectors"):
        return CustomPortalAdapter(portal, config or {})

    memory_dir = MEMORY_DIR / key / "discovered_config.json"
    if memory_dir.exists():
        with open(memory_dir, "r", encoding="utf-8") as f:
            saved_config = json.load(f)
        merged = {**saved_config, **(config or {})}
        return CustomPortalAdapter(portal, merged)

    return CustomPortalAdapter(portal, config or {})


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
