"""Navegacao hibrida (screenshot + DOM) para portais genericos/novos.

Este modulo NAO substitui o fluxo DOM dos adapters conhecidos (SGE,
Professor Online). Ele e usado apenas por portais sem adapter dedicado,
ou como fallback quando o seletor DOM ja falhou.

O HybridNavigator combina:
  - ESTRUTURA DOM (page.content() resumida via ai_assist.dom_summary)
  - SCREENSHOT (analise visual)
numa unica chamada de IA, permitindo escolher seletores REAIS da pagina
em vez de chutar pela imagem. Aceita IA local (Ollama) e APIs web.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.core.portal_memory import PortalMemory

try:
    from playwright.sync_api import Page
except ImportError:
    Page = Any  # type: ignore

try:
    from ai_assist import (
        dom_summary,
        suggest_action_hybrid,
        find_element_hybrid,
        adapt_selector_hybrid,
        execute_action_hybrid,
        is_available,
    )
except ImportError:  # pragma: no cover
    dom_summary = None
    suggest_action_hybrid = None
    find_element_hybrid = None
    adapt_selector_hybrid = None
    execute_action_hybrid = None
    is_available = None

log = logging.getLogger(__name__)


class HybridNavigator:
    """Orquestra acoes hibridas sobre uma pagina Playwright.

    Cada passo: tira screenshot + pega o DOM -> pergunta a IA qual acao
    tomar (com base no objetivo) -> executa -> registra na memoria.
    """

    # Objetivos comuns de navegacao de um portal de professor.
    DEFAULT_OBJECTIVES = [
        "fazer login no portal do professor",
        "navegar ate a tela de lancamento de notas da turma",
        "localizar e selecionar a avaliacao/atividade correta",
        "preencher as notas dos alunos na grade",
        "salvar as notas lancadas",
    ]

    def __init__(
        self,
        portal_name: str,
        page: Optional[Page] = None,
        planner: Optional[Any] = None,
    ):
        self.portal_name = portal_name
        self._page: Optional[Page] = page
        self.memory = PortalMemory(portal_name)
        self.history: List[Dict[str, Any]] = []
        self._planner = planner

    # ------------------------------------------------------------------
    # Acesso a pagina / contexto
    # ------------------------------------------------------------------
    @property
    def page(self) -> Optional[Page]:
        return self._page

    @page.setter
    def page(self, value: Optional[Page]):
        self._page = value

    def _ai_ready(self) -> bool:
        return bool(is_available and is_available())

    def capture_context(self, page: Optional[Page] = None) -> Dict[str, Any]:
        """Tira screenshot + colhe DOM da pagina atual."""
        p = page or self._page
        if p is None:
            return {"screenshot": None, "html": "", "url": ""}
        screenshot = None
        html = ""
        url = ""
        try:
            screenshot = p.screenshot()
        except Exception:
            pass
        try:
            html = p.content()
        except Exception:
            html = ""
        try:
            url = p.url
        except Exception:
            url = ""
        return {"screenshot": screenshot, "html": html, "url": url}

    # ------------------------------------------------------------------
    # Passo hibrido principal
    # ------------------------------------------------------------------
    def suggest_next_step(
        self,
        objective: str,
        page: Optional[Page] = None,
    ) -> Dict[str, Any]:
        """Sugere a proxima acao usando screenshot + DOM."""
        if not self._ai_ready():
            return {"action": None, "error": "IA nao configurada (sem API key ou Ollama offline)"}

        ctx = self.capture_context(page)
        if not ctx["screenshot"]:
            return {"action": None, "error": "Nao foi possivel tirar screenshot"}

        result = suggest_action_hybrid(
            ctx["screenshot"],
            ctx["html"],
            objective,
            history=self.history,
            logger=log.info,
        )

        if result.get("action"):
            self.history.append({
                "ts": datetime.utcnow().isoformat(),
                "objective": objective,
                "action": result.get("action"),
                "selector": result.get("selector", ""),
                "value": result.get("value", ""),
                "description": result.get("description", ""),
                "url": ctx.get("url", ""),
            })
            self.history = self.history[-20:]

        return result

    def act(self, suggestion: Dict[str, Any], page: Optional[Page] = None) -> bool:
        """Executa a acao sugerida e registra o resultado na memoria."""
        p = page or self._page
        if p is None or execute_action_hybrid is None:
            return False

        action = suggestion.get("action", "")
        selector = suggestion.get("selector", "")
        ok = execute_action_hybrid(p, suggestion, logger=log.info)

        self.memory.record_success(action, selector) if ok else \
            self.memory.record_failure(action, selector, suggestion.get("error", ""))

        return ok

    def fill_grade(
        self,
        aluno: str,
        nota: str,
        coluna: str = "",
        page: Optional[Page] = None,
    ) -> bool:
        """Preenche a nota de um aluno usando o hibrido."""
        p = page or self._page
        if p is None:
            return False

        objective = f"preencher a nota {nota} do aluno {aluno}"
        if coluna:
            objective += f" na coluna/atividade {coluna}"

        suggestion = self.suggest_next_step(objective, p)
        if not suggestion.get("action") in ("fill", "click"):
            return False

        # Garante que o valor a preencher e a nota do aluno.
        if suggestion.get("action") == "fill" and not suggestion.get("value"):
            suggestion["value"] = nota

        return self.act(suggestion, p)

    def save(self, page: Optional[Page] = None) -> bool:
        """Localiza e clica no botao salvar usando o hibrido."""
        p = page or self._page
        if p is None:
            return False
        suggestion = self.suggest_next_step("salvar as notas lançadas no portal", p)
        if suggestion.get("action") != "click":
            # Tenta um fallback por texto explicito.
            suggestion = {
                "action": "click",
                "selector": "input[value*='Salvar' i], button:has-text('Salvar')",
                "value": "",
                "description": "clicar no botao salvar",
            }
        return self.act(suggestion, p)

    # ------------------------------------------------------------------
    # Adaptacao de seletor quebrado (fallback hibrido)
    # ------------------------------------------------------------------
    def adapt(
        self,
        original_selector: str,
        action: str,
        error: str,
        page: Optional[Page] = None,
    ) -> List[str]:
        """Quando um seletor falha, pede alternativas hibridas (imagem+DOM).

        Retorna lista de seletores alternativos ja validados (existem na pagina).
        """
        p = page or self._page
        if p is None or adapt_selector_hybrid is None:
            return []

        ctx = self.capture_context(p)
        if not ctx["screenshot"]:
            return []

        result = adapt_selector_hybrid(
            original_selector,
            action,
            error,
            ctx["screenshot"],
            ctx["html"],
            logger=log.info,
        )

        alternatives = []
        for alt in result.get("alternatives", []):
            selector = str(alt.get("selector", "")).strip()
            if not selector:
                continue
            try:
                if p.locator(selector).count() > 0:
                    alternatives.append(selector)
            except Exception:
                continue
        return alternatives

    def get_stats(self) -> dict:
        return {
            "portal": self.portal_name,
            "history_steps": len(self.history),
            "memory": self.memory.get_stats(),
        }
