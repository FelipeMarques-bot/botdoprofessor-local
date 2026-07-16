import logging
import time
from typing import Optional, List, Dict
from bot.core.portal_adapter import PortalAdapter, PortalContext, GradeResult
from bot.core.portal_memory import PortalMemory
from bot.core.sge_adapter import SGEAdapter
from bot.core.custom_adapter import CustomPortalAdapter

log = logging.getLogger(__name__)


class BotEngine:
    """Motor principal que orquestra a lancamento de notas."""

    def __init__(self, adapter: PortalAdapter, execution_id: str = ""):
        self.adapter = adapter
        self.execution_id = execution_id
        self.memory = PortalMemory(adapter.name)
        self.results: List[GradeResult] = []

    def run(self, grades: List[Dict], context: PortalContext = None) -> GradeResult:
        """Executa o lancamento de notas.

        Args:
            grades: Lista de dicts com 'aluno', 'nota', e opcionalmente 'coluna', 'atividade'.
            context: Contexto de navegacao (escola, turno, turma, etc.)
        """
        total_filled = 0
        total_failed = 0
        total_skipped = 0
        total_already = 0
        details = []

        for entry in grades:
            aluno = entry.get("aluno", "").strip()
            nota = entry.get("nota", "").strip()
            coluna = entry.get("coluna", "")
            atividade = entry.get("atividade", "")

            if not aluno or not nota:
                total_skipped += 1
                continue

            if nota.upper() in ("NI", "I", "-"):
                total_skipped += 1
                details.append({"aluno": aluno, "status": "skipped", "reason": "nota_nula"})
                continue

            try:
                success = self.adapter.fill_grade(aluno, nota, coluna=coluna)
                if success:
                    total_filled += 1
                    details.append({"aluno": aluno, "status": "filled", "nota": nota})
                else:
                    total_failed += 1
                    details.append({"aluno": aluno, "status": "failed", "reason": "fill_returned_false"})
            except Exception as e:
                total_failed += 1
                details.append({"aluno": aluno, "status": "error", "error": str(e)})
                log.error("Erro ao preencher %s: %s", aluno, e)

        result = GradeResult(
            success=total_failed == 0 and total_filled > 0,
            filled=total_filled,
            failed=total_failed,
            skipped=total_skipped,
            already_exists=total_already,
            details=details,
        )

        self.results.append(result)
        self.memory.record_execution({
            "filled": total_filled,
            "failed": total_failed,
            "skipped": total_skipped,
            "execution_id": self.execution_id,
        })

        return result

    def save_and_verify(self) -> bool:
        """Salva e verifica se a pagina deu feedback de sucesso."""
        success = self.adapter.save()
        if not success:
            log.warning("Save retornou false, tentando verificar status...")
        return success

    def read_and_compare(self, expected: List[Dict]) -> Dict:
        """Le as notas atuais e compara com o esperado."""
        current = self.adapter.read_grades()
        comparison = {
            "matched": 0,
            "mismatched": 0,
            "missing": 0,
            "details": [],
        }

        expected_map = {}
        for e in expected:
            key = e.get("aluno", "").strip().lower()
            if key:
                expected_map[key] = e.get("nota", "").strip()

        found_map = {}
        for c in current:
            key = c.get("aluno", "").strip().lower()
            if key:
                found_map[key] = c.get("nota", "").strip()

        for aluno, nota in expected_map.items():
            found = found_map.get(aluno, "")
            if not found:
                comparison["missing"] += 1
                comparison["details"].append({
                    "aluno": aluno, "expected": nota, "found": "",
                    "status": "missing",
                })
            elif found == nota:
                comparison["matched"] += 1
            else:
                comparison["mismatched"] += 1
                comparison["details"].append({
                    "aluno": aluno, "expected": nota, "found": found,
                    "status": "mismatch",
                })

        return comparison

    def handle_error(self, error: str, context: dict = None) -> dict:
        """Trata erros e decide acao (retry, skip, abort)."""
        self.memory.record_failure("execution", self.execution_id, error)

        retry_keywords = ["timeout", "elemento nao encontrado", "not found"]
        should_retry = any(kw in error.lower() for kw in retry_keywords)

        return {
            "should_retry": should_retry,
            "error": error,
            "context": context or {},
        }

    def get_stats(self) -> dict:
        return {
            "portal": self.adapter.name,
            "total_runs": len(self.results),
            "total_filled": sum(r.filled for r in self.results),
            "total_failed": sum(r.failed for r in self.results),
            "total_skipped": sum(r.skipped for r in self.results),
            "memory_stats": self.memory.get_stats(),
        }
