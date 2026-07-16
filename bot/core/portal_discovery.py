import base64
import json
from pathlib import Path
from typing import Optional, Dict, List
from bot.core.portal_memory import PortalMemory

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None


PORTAL_DISCOVERY_PROMPT = """Voce e um especialista em automacao de portais escolares brasileiros.

Analise este screenshot de um portal de professores e retorne um JSON com a estrutura descoberta.

Retorne APENAS o JSON, sem markdown, sem explicacao:
{
  "portal_name": "nome do portal",
  "url": "url base se visivel",
  "auth_flow": {
    "username_field": "CSS selector do campo de usuario/CPF",
    "password_field": "CSS selector do campo de senha",
    "submit": {"selector": "CSS selector do botao de login"}
  },
  "navigation": {
    "steps": [
      {"action": "select", "selector": "CSS do select", "field": "escola"},
      {"action": "select", "selector": "CSS do select", "field": "turma"},
      {"action": "select", "selector": "CSS do select", "field": "trimestre"}
    ]
  },
  "grade_flow": {
    "student_name_selector": "CSS dos nomes dos alunos",
    "grade_input_selector": "CSS dos inputs de nota",
    "assessment_selector": "CSS para selecionar avaliacao",
    "save_selector": "CSS do botao salvar",
    "pagination_selector": "CSS da paginacao"
  },
  "columns": {
    "1": "nome da coluna posicao 1",
    "2": "nome da coluna posicao 2"
  },
  "confidence": 0.8,
  "notes": "observacoes sobre o portal"
}

Se nao conseguir identificar algo, use string vazia "".
Se nao houver paginacao, deixe pagination_selector vazio.
O campo confidence deve ser entre 0 e 1.
"""


class PortalDiscovery:
    """Motor de descoberta de estrutura de portais via IA.

    Tira screenshot do portal, envia para LLM, e recebe a estrutura
    CSS/fluxo de navegacao para criar um CustomPortalAdapter.
    """

    def __init__(self, ai_provider: str = "gemini", ai_config: dict = None):
        self.ai_provider = ai_provider
        self.ai_config = ai_config or {}
        self._llm = None

    def _get_llm(self):
        if self._llm:
            return self._llm

        provider = self.ai_provider.lower()
        config = self.ai_config

        if provider == "gemini":
            import google.generativeai as genai
            api_key = config.get("api_key") or ""
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY necessario")
            genai.configure(api_key=api_key)
            self._llm = ("gemini", genai.GenerativeModel("gemini-2.5-flash"))
        elif provider == "openai":
            import openai
            api_key = config.get("api_key") or ""
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY necessario")
            self._llm = ("openai", openai.OpenAI(api_key=api_key))
        elif provider == "anthropic":
            import anthropic
            api_key = config.get("api_key") or ""
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY necessario")
            self._llm = ("anthropic", anthropic.Anthropic(api_key=api_key))
        elif provider == "ollama":
            import openai
            self._llm = ("openai", openai.OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            ))
        else:
            raise RuntimeError(f"Provider desconhecido: {provider}")

        return self._llm

    def _ask_llm_with_image(self, image_b64: str) -> str:
        provider_type, client = self._get_llm()

        if provider_type == "gemini":
            import google.generativeai as genai
            image_data = base64.b64decode(image_b64)
            response = client.generate_content([
                PORTAL_DISCOVERY_PROMPT,
                {"inline_data": {"mime_type": "image/png", "data": image_b64}},
            ])
            return response.text

        elif provider_type == "openai":
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PORTAL_DISCOVERY_PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "high",
                        }},
                    ],
                }],
                max_tokens=2000,
            )
            return response.choices[0].message.content

        elif provider_type == "anthropic":
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        }},
                        {"type": "text", "text": PORTAL_DISCOVERY_PROMPT},
                    ],
                }],
            )
            return response.content[0].text

        return ""

    def discover_from_screenshot(self, screenshot_b64: str) -> Optional[Dict]:
        """Envia screenshot para IA e retorna estrutura do portal."""
        try:
            raw = self._ask_llm_with_image(screenshot_b64)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
            config = json.loads(raw)
            memory = PortalMemory(config.get("portal_name", "unknown"))
            memory.record_navigation("discovered", json.dumps(config, ensure_ascii=False))
            return config
        except Exception:
            return None

    def discover_from_url(self, url: str, page=None) -> Optional[Dict]:
        """Navega ate a URL, tira screenshot, e analisa."""
        own_page = False
        if not page:
            if sync_playwright is None:
                return None
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=False)
            page = browser.new_page()
            own_page = True

        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            screenshot_bytes = page.screenshot()
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return self.discover_from_screenshot(screenshot_b64)
        except Exception:
            return None
        finally:
            if own_page:
                try:
                    page.browser.close()
                except Exception:
                    pass

    def discover_from_sge_pages(self, base_url: str = "") -> List[Dict]:
        """Tenta varias URLs comuns de SGE e analisa cada uma."""
        urls = [
            f"{base_url or 'https://www.sge8147.com.br'}/hportalprofessor.aspx",
            f"{base_url or 'https://www.sge8147.com.br'}/hPortalProfessor8147.aspx",
            f"{base_url or 'https://www.sge8147.com.br'}/hPortalProfessor.aspx",
        ]
        configs = []
        for url in urls:
            config = self.discover_from_url(url)
            if config:
                configs.append(config)
        return configs

    def save_discovery(self, config: dict, portal_name: str = ""):
        """Salva a estrutura descoberta em disco."""
        name = portal_name or config.get("portal_name", "unknown")
        memory_dir = Path.home() / ".bot_local" / "portal_memory" / name.lower().replace(" ", "_")
        memory_dir.mkdir(parents=True, exist_ok=True)
        with open(memory_dir / "discovered_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
