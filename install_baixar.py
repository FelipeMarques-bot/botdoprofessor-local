#!/usr/bin/env python3
"""BotDoProfessor-Local — Instalacao automatica do Playwright.

Executa na primeira vez para baixar e instalar o Chromium.
Pode ser chamado pelo run_bot.py ou pelo first_run.bat.
"""

import os
import sys
import subprocess


def main():
    print("=" * 50)
    print("  BotDoProfessor — Instalacao de dependencias")
    print("=" * 50)
    print()

    print("[1/3] Verificando pip...")
    try:
        import pip
        print("  [OK] pip disponivel")
    except ImportError:
        print("  [ER] pip nao encontrado. Instale Python com 'Add to PATH'.")
        input("\nPressione Enter para sair...")
        sys.exit(1)

    print()
    print("[2/3] Instalando playwright...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "playwright", "--quiet"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [ER] Falha: {result.stderr}")
        input("\nPressione Enter para sair...")
        sys.exit(1)
    print("  [OK] playwright instalado")

    print()
    print("[3/3] Baixando Chromium (~180MB)...")
    print("  Isso pode demorar alguns minutos na primeira vez...")
    print()
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [ER] Falha ao baixar Chromium: {result.stderr}")
        print("  Tente manualmente: python -m playwright install chromium")
        input("\nPressione Enter para sair...")
        sys.exit(1)

    print()
    print("[OK] Chromium instalado com sucesso!")
    print()
    print("=" * 50)
    print("  Instalacao concluida!")
    print("  Agora voce pode executar o BotDoProfessor.")
    print("=" * 50)
    input("\nPressione Enter para continuar...")


if __name__ == "__main__":
    main()
