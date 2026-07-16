import json
import shutil
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from config.settings import DATA_DIR, LOGS_DIR, BASE_DIR


class BackupManager:
    """Gerencia backups do banco de dados e configuracoes."""

    BACKUP_DIR = Path.home() / ".bot_local" / "backups"

    def __init__(self):
        self.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def create_backup(self, label: str = "") -> str:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        name = f"backup_{label}_{ts}" if label else f"backup_{ts}"
        dest = self.BACKUP_DIR / name
        dest.mkdir(parents=True, exist_ok=True)

        db_file = DATA_DIR / "bot_local.db"
        if db_file.exists():
            shutil.copy2(db_file, dest / "bot_local.db")

        settings_file = BASE_DIR / "config" / "settings.py"
        if settings_file.exists():
            shutil.copy2(settings_file, dest / "settings.py")

        env_file = BASE_DIR / ".env"
        if env_file.exists():
            shutil.copy2(env_file, dest / ".env")

        return str(dest)

    def restore_backup(self, backup_name: str) -> bool:
        src = self.BACKUP_DIR / backup_name
        if not src.exists():
            return False

        db_backup = src / "bot_local.db"
        if db_backup.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_backup, DATA_DIR / "bot_local.db")

        return True

    def list_backups(self) -> List[Dict]:
        backups = []
        for d in sorted(self.BACKUP_DIR.iterdir(), reverse=True):
            if d.is_dir():
                backups.append({
                    "name": d.name,
                    "path": str(d),
                    "created": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    "size": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()),
                })
        return backups

    def cleanup_old(self, keep: int = 10):
        backups = self.list_backups()
        for b in backups[keep:]:
            path = Path(b["path"])
            if path.exists():
                shutil.rmtree(path)


class HealthChecker:
    """Verificacao de saude do sistema."""

    def check_database(self) -> Dict:
        try:
            from bot.models.database import db
            from sqlalchemy import text
            db.session.execute(text("SELECT 1"))
            return {"status": "ok", "message": "Banco conectado"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_portal_memory(self) -> Dict:
        mem_dir = Path.home() / ".bot_local" / "portal_memory"
        if not mem_dir.exists():
            return {"status": "warning", "message": "Diretorio de memoria nao existe"}
        portals = [d.name for d in mem_dir.iterdir() if d.is_dir()]
        return {"status": "ok", "portals": portals, "count": len(portals)}

    def check_disk_space(self) -> Dict:
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        return {
            "status": "ok" if free_gb > 1 else "warning",
            "free_gb": round(free_gb, 2),
        }

    def check_logs(self) -> Dict:
        if not LOGS_DIR.exists():
            return {"status": "warning", "message": "Diretorio de logs nao existe"}
        files = list(LOGS_DIR.rglob("*.log"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "status": "ok",
            "log_files": len(files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    def full_check(self) -> Dict:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "database": self.check_database(),
            "portal_memory": self.check_portal_memory(),
            "disk": self.check_disk_space(),
            "logs": self.check_logs(),
        }
