import os
import json
from datetime import datetime
from pathlib import Path

EVIDENCIAS_DIR = Path(__file__).resolve().parent.parent / "evidencias"
EVIDENCIAS_DIR.mkdir(exist_ok=True)


def register_evidence(phase: str, task: str, status: str, details: str = "", evidence_file: str = ""):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    entry = {
        "phase": phase,
        "task": task,
        "status": status,
        "details": details,
        "evidence_file": evidence_file,
        "timestamp": datetime.utcnow().isoformat(),
    }

    phase_dir = EVIDENCIAS_DIR / phase
    phase_dir.mkdir(exist_ok=True)

    log_file = phase_dir / "evidence_log.json"
    entries = []
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            entries = json.load(f)

    entries.append(entry)

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    return entry
