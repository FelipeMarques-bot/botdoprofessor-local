import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


MEMORY_DIR = Path.home() / ".bot_local" / "portal_memory"


class PortalMemory:
    """Memoria persistente de aprendizado de cada portal.

    Salva selectors que funcionaram, colunas detectadas, fluxos de navegacao,
    erros conhecidos e padraos descobertos.
    """

    def __init__(self, portal_name: str):
        self.portal_name = portal_name
        self.memory_dir = MEMORY_DIR / portal_name.lower().replace(" ", "_")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _memory_file(self) -> Path:
        return self.memory_dir / "memory.json"

    def _load(self) -> dict:
        f = self._memory_file()
        if f.exists():
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {
            "portal": self.portal_name,
            "created_at": datetime.utcnow().isoformat(),
            "last_updated": None,
            "selectors": {},
            "columns": {},
            "navigation": {},
            "save_flow": {},
            "errors_known": [],
            "success_count": 0,
            "failure_count": 0,
            "execution_history": [],
        }

    def save(self):
        self.data["last_updated"] = datetime.utcnow().isoformat()
        with open(self._memory_file(), "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def record_success(self, action: str, selector: str, context: dict = None):
        key = f"success:{action}"
        if key not in self.data["selectors"]:
            self.data["selectors"][key] = []
        entry = {"selector": selector, "count": 0, "last_used": None}
        for e in self.data["selectors"][key]:
            if e["selector"] == selector:
                entry = e
                break
        else:
            self.data["selectors"][key].append(entry)
        entry["count"] += 1
        entry["last_used"] = datetime.utcnow().isoformat()
        if context:
            entry["context"] = context
        self.data["success_count"] += 1
        self.save()

    def record_failure(self, action: str, selector: str, error: str = ""):
        key = f"failure:{action}"
        if key not in self.data["selectors"]:
            self.data["selectors"][key] = []
        self.data["selectors"][key].append({
            "selector": selector,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.data["errors_known"].append({
            "action": action,
            "selector": selector,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.data["failure_count"] += 1
        self.save()

    def record_column(self, position: int, column_name: str):
        self.data["columns"][str(position)] = column_name
        self.save()

    def record_navigation(self, key: str, value: str):
        self.data["navigation"][key] = value
        self.save()

    def record_save_flow(self, flow: dict):
        self.data["save_flow"] = flow
        self.save()

    def get_best_selector(self, action: str) -> Optional[str]:
        key = f"success:{action}"
        entries = self.data["selectors"].get(key, [])
        if not entries:
            return None
        entries.sort(key=lambda e: e.get("count", 0), reverse=True)
        return entries[0]["selector"]

    def get_known_errors(self, action: str = "") -> list:
        if action:
            return [e for e in self.data["errors_known"] if e["action"] == action]
        return self.data["errors_known"]

    def get_stats(self) -> dict:
        return {
            "portal": self.portal_name,
            "success_count": self.data["success_count"],
            "failure_count": self.data["failure_count"],
            "selectors_recorded": len(self.data["selectors"]),
            "columns_recorded": len(self.data["columns"]),
            "last_updated": self.data["last_updated"],
        }

    def record_execution(self, result: dict):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            **result,
        }
        self.data["execution_history"].append(entry)
        if len(self.data["execution_history"]) > 100:
            self.data["execution_history"] = self.data["execution_history"][-100:]
        self.save()

    def export_for_sharing(self) -> dict:
        return {
            "portal": self.portal_name,
            "columns": self.data["columns"],
            "selectors": {
                k: v for k, v in self.data["selectors"].items()
                if k.startswith("success:")
            },
            "navigation": self.data["navigation"],
            "save_flow": self.data["save_flow"],
        }
