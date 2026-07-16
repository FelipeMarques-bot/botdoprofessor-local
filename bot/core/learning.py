import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from bot.core.portal_memory import PortalMemory


class LearningTracker:
    """Rastreia aprendizado continuo entre execucoes.

    Monitora padrao de sucesso/falha, detecta mudancas no portal,
    e sugere selectors alternativos baseado em historico.
    """

    def __init__(self, portal_name: str):
        self.portal_name = portal_name
        self.memory = PortalMemory(portal_name)
        self._log_dir = Path.home() / ".bot_local" / "logs" / portal_name.lower().replace(" ", "_")
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def record_attempt(self, action: str, selector: str, success: bool, error: str = ""):
        if success:
            self.memory.record_success(action, selector)
        else:
            self.memory.record_failure(action, selector, error)

        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "selector": selector,
            "success": success,
            "error": error,
        }
        log_file = self._log_dir / f"attempts_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def detect_selector_drift(self, action: str, current_selector: str) -> Optional[Dict]:
        """Detecta se um selector parou de funcionar.

        Compara com o historico de sucesso e retorna sugestao
        se houver um selector que funcionava antes.
        """
        best = self.memory.get_best_selector(action)
        if not best or best == current_selector:
            return None

        today = datetime.utcnow().strftime("%Y%m%d")
        log_file = self._log_dir / f"attempts_{today}.jsonl"
        recent_failures = []
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry["action"] == action and not entry["success"]:
                            recent_failures.append(entry)
                    except Exception:
                        continue

        if len(recent_failures) >= 3:
            return {
                "drift_detected": True,
                "action": action,
                "current_selector": current_selector,
                "suggested_selector": best,
                "recent_failures": len(recent_failures),
            }
        return None

    def get_recommended_columns(self) -> Dict[str, str]:
        """Retorna colunas recomendadas baseadas em aprendizado anterior."""
        return self.memory.data.get("columns", {})

    def get_recommended_save_flow(self) -> Dict:
        """Retorna fluxo de save recomendado."""
        return self.memory.data.get("save_flow", {})

    def get_execution_summary(self, days: int = 7) -> Dict:
        """Resumo das execucoes nos ultimos N dias."""
        summaries = []
        log_dir = self._log_dir
        for f in sorted(log_dir.glob("attempts_*.jsonl"), reverse=True)[:days]:
            date_str = f.stem.replace("attempts_", "")
            count = 0
            successes = 0
            failures = 0
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                        count += 1
                        if entry["success"]:
                            successes += 1
                        else:
                            failures += 1
                    except Exception:
                        continue
            summaries.append({
                "date": date_str,
                "total": count,
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / count * 100, 1) if count > 0 else 0,
            })

        return {
            "portal": self.portal_name,
            "days_analyzed": len(summaries),
            "daily_summaries": summaries,
            "overall_stats": self.memory.get_stats(),
        }

    def suggest_fixes(self) -> List[Dict]:
        """Analisa historico e sugere correcoes."""
        suggestions = []
        stats = self.memory.get_stats()

        if stats["failure_count"] > stats["success_count"] * 2:
            suggestions.append({
                "type": "high_failure_rate",
                "message": "Taxa de falha alta. Considere redescobrir o portal.",
                "severity": "warning",
            })

        for action in ["fill_grade", "save", "navigate"]:
            drift = self.detect_selector_drift(action, "")
            if drift:
                suggestions.append({
                    "type": "selector_drift",
                    "action": action,
                    "message": f"Selector de '{action}' pode ter mudado. Sugestao: {drift['suggested_selector']}",
                    "severity": "info",
                })

        return suggestions
