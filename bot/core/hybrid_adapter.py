"""Adapter hibrido (screenshot + DOM) para portais genericos/novos.

Nao substitui o fluxo DOM do SGE / Professor Online. Este adapter e
usado apenas por portais sem adapter dedicado, quando o usuario escolhe
"portal novo" ou a memória nao tem seletores confiaveis.

Usa o HybridNavigator (IA com screenshot + estrutura DOM) para:
  - login
  - navegacao (escola/turma/atividade)
  - preenchimento de notas
  - salvamento
"""

import json
from typing import Any, Dict, List, Optional

from bot.core.portal_adapter import PortalAdapter, PortalContext
from bot.core.portal_memory import PortalMemory
from bot.core.hybrid_navigator import HybridNavigator

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    sync_playwright = None


class HybridPortalAdapter(PortalAdapter):
    """Adapter para portais desconhecidos, guiado por IA hibrida.

    Diferente do CustomPortalAdapter (que depende de um JSON descoberto),
    este adapter usa o HybridNavigator a cada passo: tira screenshot +
    le o DOM e deixa a IA decidir a acao. Quando um passo tem sucesso,
    memoriza o seletor para nao re-analisar na proxima execucao.
    """

    def __init__(self, portal_name: str, portal_config: dict):
        self._portal_name = portal_name
        self._config = portal_config or {}
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._pw = None
        self.memory = PortalMemory(portal_name)
        self.navigator = HybridNavigator(portal_name)
        self._logged_in = False

    @property
    def name(self) -> str:
        return self._portal_name

    @property
    def url(self) -> str:
        return self._config.get("url", "")

    def start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright nao instalado")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(20000)
        self.navigator.page = self._page

    def stop(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self.navigator.page = None

    @property
    def page(self):
        if not self._page:
            self.start()
        return self._page

    def login(self, cpf: str, senha: str) -> bool:
        p = self.page
        url = self._config.get("url", "")
        try:
            p.goto(url, timeout=20000, wait_until="domcontentloaded")
        except Exception:
            return False

        # Objetivo composto: preencher CPF/senha e clicar em entrar.
        suggestion = self.navigator.suggest_next_step(
            "fazer login com CPF, preencher a senha e clicar no botao de entrar"
        )
        if suggestion.get("action") is None:
            return False

        # Preenche credenciais se a IA sugerir fill/click nos campos certos.
        if suggestion.get("action") == "fill" and not suggestion.get("value"):
            suggestion["value"] = cpf
        self.navigator.act(suggestion)

        # Segunda passada: garantir preenchimento da senha e clique no botao.
        suggestion2 = self.navigator.suggest_next_step(
            "preencher a senha do usuario e clicar em entrar/login/acessar"
        )
        if suggestion2.get("action"):
            if suggestion2.get("action") == "fill" and not suggestion2.get("value"):
                suggestion2["value"] = senha
            self.navigator.act(suggestion2)

        try:
            p.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Login considerado ok se a URL mudou ou nao ha form de login visivel.
        login_fields = p.locator("input[type='password']")
        if login_fields.count() == 0 or "login" not in (p.url or "").lower():
            self._logged_in = True
        else:
            self._logged_in = False
        return self._logged_in

    def navigate_to(self, context: PortalContext) -> bool:
        p = self.page
        if not context:
            return True

        fields = []
        if context.escola:
            fields.append(("escola", context.escola))
        if context.turno:
            fields.append(("turno", context.turno))
        if context.turma:
            fields.append(("turma", context.turma))
        if context.trimestre:
            fields.append(("trimestre", context.trimestre))

        for field, value in fields:
            objective = (
                f"selecionar {field} = '{value}' na tela atual "
                f"(use select/option se existir, senao clique)"
            )
            suggestion = self.navigator.suggest_next_step(objective)
            if suggestion.get("action") in ("select", "click"):
                if suggestion.get("action") == "select" and not suggestion.get("value"):
                    suggestion["value"] = value
                self.navigator.act(suggestion)
        return True

    def find_assessment(self, atividade: str) -> Optional[Dict]:
        objective = f"localizar e selecionar a avaliacao/atividade '{atividade}'"
        suggestion = self.navigator.suggest_next_step(objective)
        if suggestion.get("action") == "click":
            if self.navigator.act(suggestion):
                return {"found": True, "text": atividade, "via": "hybrid"}
        return None

    def detect_columns(self) -> Dict[str, str]:
        return self.memory.data.get("columns", {})

    def read_grades(self) -> List[Dict]:
        return []

    def fill_grade(self, aluno: str, nota: str, coluna: str = "") -> bool:
        return self.navigator.fill_grade(aluno, nota, coluna, self.page)

    def save(self) -> bool:
        return self.navigator.save(self.page)

    def is_logged_in(self) -> bool:
        return self._logged_in
