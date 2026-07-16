#!/usr/bin/env python3
"""BotDoProfessor-Local -- Operacao guiada (pos-implementacao).

Executa os 4 passos da secao 7 do MD:
  1. Verificacao de saude
  2. Execucao assistida (dry-run)
  3. Tratamento de falhas (relatorio)
  4. Fechamento operacional

Uso:
  python guided_operation.py --cpf 12345678901 --senha minhasenha
  python guided_operation.py --health-only
  python guided_operation.py --dry-run --cpf 12345678901 --senha minhasenha
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import DATA_DIR, LOGS_DIR

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
EVIDENCE_DIR = Path.home() / ".bot_local" / "evidences"


def setup_logging():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"guided_op_{ts}.log"
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(fh)
    return log_file


def step1_health():
    """Passo 1 -- Verificacao de saude."""
    print("=" * 60)
    print("PASSO 1 - Verificacao de saude do sistema")
    print("=" * 60)

    from app import create_app
    app = create_app()

    with app.app_context():
        from bot.ops.monitoring import HealthChecker
        checker = HealthChecker()
        result = checker.full_check()

        all_ok = True
        for key, val in result.items():
            if isinstance(val, dict):
                status = val.get("status", "unknown")
                icon = "[OK]" if status == "ok" else "[!!]" if status == "warning" else "[ER]"
                msg = val.get("message", val)
                print(f"  {icon} {key}: {msg}")
                if status == "error":
                    all_ok = False
            else:
                print(f"  [--] {key}: {val}")

        print()
        if all_ok:
            print("[OK] Sistema saudavel - todos os checks OK")
        else:
            print("[ER] Problemas detectados - verifique os erros acima")

        return all_ok, result


def step2_dry_run(cpf, senha):
    """Passo 2 -- Execucao assistida (dry-run com browser)."""
    print()
    print("=" * 60)
    print("PASSO 2 - Execucao assistida (dry-run)")
    print("=" * 60)

    from bot.core.sge_adapter import SGEAdapter

    print("  Iniciando browser...")
    adapter = SGEAdapter()
    try:
        adapter.start()
        print("  [OK] Browser iniciado")

        print("  Fazendo login no SGE...")
        ok = adapter.login(cpf, senha)
        if not ok:
            print("  [ER] Login falhou - verifique credenciais")
            return False

        print("  [OK] Login realizado com sucesso")

        print("  Detectando colunas da grade...")
        columns = adapter.detect_columns()
        if columns:
            print(f"  [OK] Colunas detectadas: {columns}")
        else:
            print("  [!!] Colunas nao detectadas (pode ser necessario navegar ate a grade)")

        print("  Lendo amostra de alunos...")
        sample = adapter.get_student_sample(limit=5)
        if sample:
            print(f"  [OK] Amostra de alunos ({len(sample)}):")
            for name in sample:
                print(f"     - {name}")
        else:
            print("  [!!] Nenhum aluno encontrado (navegue ate a grade manualmente)")

        print()
        print("[OK] Dry-run concluido com sucesso")
        print("  Browser permanece aberto para inspecao manual.")
        print("  Feche quando terminar de verificar.")
        return True

    except Exception as e:
        print(f"  [ER] Erro: {e}")
        return False


def step3_error_report():
    """Passo 3 -- Relatorio de falhas."""
    print()
    print("=" * 60)
    print("PASSO 3 - Relatorio de falhas")
    print("=" * 60)

    from app import create_app
    app = create_app()

    with app.app_context():
        from bot.models.audit import AuditLog
        from datetime import timedelta

        since = datetime.utcnow() - timedelta(hours=24)
        errors = AuditLog.query.filter(
            AuditLog.timestamp >= since,
            AuditLog.status.in_(["denied", "error", "failed"])
        ).order_by(AuditLog.timestamp.desc()).limit(50).all()

        if not errors:
            print("  [OK] Nenhuma falha nas ultimas 24h")
        else:
            print(f"  [!!] {len(errors)} falha(s) encontrada(s):")
            for log_entry in errors:
                print(f"     [{log_entry.timestamp}] {log_entry.action} -- {log_entry.status} "
                      f"(user={log_entry.user_id}, ip={log_entry.ip})")

        return len(errors)


def step4_closing():
    """Passo 4 -- Fechamento operacional."""
    print()
    print("=" * 60)
    print("PASSO 4 - Fechamento operacional")
    print("=" * 60)

    from app import create_app
    app = create_app()

    with app.app_context():
        from bot.ops.monitoring import BackupManager

        mgr = BackupManager()
        path = mgr.create_backup(label="guided_op")
        print(f"  [OK] Backup criado: {path}")

        backups = mgr.list_backups()
        print(f"  [--] Total de backups: {len(backups)}")

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "operation": "guided_operation",
            "status": "completed",
            "backup_path": path,
            "total_backups": len(backups),
        }

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        report_file = EVIDENCE_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"  [OK] Relatorio salvo: {report_file}")
        print()
        print("[OK] Fechamento operacional concluido")


def main():
    parser = argparse.ArgumentParser(description="Operacao guiada do BotDoProfessor-Local")
    parser.add_argument("--cpf", default="", help="CPF para login no SGE")
    parser.add_argument("--senha", default="", help="Senha para login no SGE")
    parser.add_argument("--health-only", action="store_true", help="Apenas verificar saude")
    parser.add_argument("--dry-run", action="store_true", help="Executar dry-run com browser")
    args = parser.parse_args()

    log_file = setup_logging()
    logging.info("Operacao guiada iniciada")

    ok, health = step1_health()

    if args.health_only:
        return

    step3_error_report()

    if args.dry_run and args.cpf and args.senha:
        step2_dry_run(args.cpf, args.senha)
    elif args.dry_run:
        print("\n[!!] --dry-run requer --cpf e --senha")

    step4_closing()

    logging.info("Operacao guiada concluida")
    print(f"\nLog completo: {log_file}")


if __name__ == "__main__":
    main()
