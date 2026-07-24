#!/usr/bin/env python3
"""BotDoProfessor — Launcher.

Bootstrap: cria venv, instala dependencias, inicia Streamlit e abre o navegador.
Compilar com PyInstaller: pyinstaller --onefile --name BotDoProfessor launcher.py
"""

import os
import re
import sys
import shutil
import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path

APP_DIR = Path.home() / ".bot_local"
VENV_DIR = APP_DIR / "venv"
DOWNLOAD_URL = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"

if os.name == "nt":
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"


def _set_utf8():
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


def _is_valid_python(path):
    if not path:
        return False
    lower = path.lower()
    if "windowsapps" in lower:
        return False
    if path.endswith("python3.exe") and "local" in lower and "microsoft" in lower:
        return False
    try:
        return os.path.isfile(path) or os.access(path, os.X_OK)
    except Exception:
        return False


def find_system_python():
    """Encontra Python instalado no sistema."""
    py = shutil.which("py")
    if py and _is_valid_python(py):
        return py

    for name in ("python3", "python"):
        path = shutil.which(name)
        if _is_valid_python(path):
            return path

    uv_base = os.path.expandvars(r"%APPDATA%\uv\python")
    if os.path.isdir(uv_base):
        import glob
        for uv_py in sorted(glob.glob(os.path.join(uv_base, "cpython-3.*", "python.exe")), reverse=True):
            if _is_valid_python(uv_py):
                return uv_py

    common_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python310\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
        r"C:\Python312\python.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p

    return None


def get_bundled_dir():
    """Retorna diretorio dos arquivos bundlados pelo PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_painel_path():
    """Entra o painel.py — bundled ou local."""
    bundled = get_bundled_dir() / "painel.py"
    if bundled.exists():
        return str(bundled)
    local = Path(__file__).parent / "painel.py"
    if local.exists():
        return str(local)
    return None


def create_venv(python_path):
    """Cria virtual environment."""
    print("[i] Criando ambiente virtual...")
    subprocess.run([python_path, "-m", "venv", str(VENV_DIR)], check=True, capture_output=True)
    print("  [OK] Ambiente virtual criado")


def install_requirements():
    """Instala dependencias no venv."""
    print("[i] Instalando dependencias (pode demorar na primeira vez)...")
    print("  [i] pip install streamlit playwright openpyxl pandas...")
    reqs = [
        "streamlit>=1.32",
        "playwright>=1.40",
        "openpyxl>=3.1",
        "pandas>=2.0",
        "requests>=2.31",
        "python-dotenv>=1.0",
        "google-generativeai>=0.5",
        "openai>=1.30",
        "anthropic>=0.25",
    ]
    subprocess.run(
        [str(VENV_PIP), "install", "--quiet", "--disable-pip-version-check"] + reqs,
        check=True,
    )
    print("  [OK] Dependencias instaladas")


def install_playwright_chromium():
    """Instala navegador Chromium via Playwright."""
    ms_playwright = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not ms_playwright.exists():
        ms_playwright = Path.home() / ".cache" / "ms-playwright"
    if ms_playwright.exists():
        for d in ms_playwright.iterdir():
            if d.is_dir() and d.name.startswith("chromium-"):
                chrome = d / "chrome-win64" / "chrome.exe"
                if not chrome.exists():
                    chrome = d / "chrome-win" / "chrome.exe"
                if chrome.exists():
                    print("[OK] Navegador Chromium ja instalado")
                    return

    print("[i] Baixando navegador Chromium (~180MB, primeira vez)...")
    print("  [i] Isso demora cerca de 2 minutos e so acontece uma vez.")
    try:
        subprocess.run(
            [str(VENV_PYTHON), "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("  [OK] Navegador instalado com sucesso!")
    except subprocess.CalledProcessError:
        print("  [ER] Falha ao baixar navegador.")
        print("  Tente manualmente: python -m playwright install chromium")


def setup_ollama_if_needed():
    """Verifica e instala Ollama + modelo de visao se necessario."""
    try:
        sys.path.insert(0, str(get_bundled_dir()))
        from ai_assist import (
            _find_ollama_exe, _is_ollama_running, _is_ollama_installed,
            _is_model_available, _get_available_ram_gb,
            OLLAMA_MODEL,
        )

        os.environ.setdefault("AI_PROVIDER", "ollama")
        os.environ.setdefault("OLLAMA_MODEL", OLLAMA_MODEL)

        if _is_ollama_running() and _is_model_available(OLLAMA_MODEL):
            print("[OK] Ollama rodando com modelo de visao")
            return

        avail_ram = _get_available_ram_gb()
        if avail_ram < 4.0:
            print(f"[i] RAM disponivel: {avail_ram:.1f} GB — IA local requer 4GB+")
            print("[i] A extracao por foto nao estara disponivel.")
            print("[i] Use planilhas CSV/Excel ou Google Sheets como alternativa.")
            return

        print()
        print("  IA local (Ollama) pode ser instalada para extrair notas por foto.")
        print("  Isso leva 3-5 minutos e baixa ~1.5GB.")
        print("  Voce pode instalar depois pelo painel.")
        print()

        from ai_assist import setup_ollama
        print("[i] Instalando Ollama...")
        success = setup_ollama(logger=lambda m: print(f"  {m}"))
        if success:
            print("[OK] Ollama configurado!")
        else:
            print("[i] Ollama nao instalado agora. Instale depois pelo painel.")
    except ImportError:
        print("[i] Modulo de IA nao disponivel. Ignorando Ollama.")
    except Exception as e:
        print(f"[i] Verificacao de Ollama: {e}")


def wait_for_streamlit(port=8501, timeout=30):
    """Aguarda Streamlit iniciar."""
    import urllib.request
    import urllib.error
    url = f"http://localhost:{port}"
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main():
    _set_utf8()
    APP_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print("          BotDoProfessor — Automatize suas notas")
    print("=" * 56)
    print()
    print("  Este programa lanca notas, planos de aula e")
    print("  sequencias didaticas automaticamente no SGE.")
    print()

    python = find_system_python()
    if not python:
        print("[ER] Python nao encontrado no seu computador!")
        print()
        print("  Instale o Python: https://www.python.org/downloads/")
        print("  Marque a opcao 'Add Python to PATH' durante a instalacao.")
        print()
        input("  Pressione Enter para sair...")
        sys.exit(1)

    print(f"[i] Python encontrado: {python}")

    if not VENV_DIR.exists():
        print()
        create_venv(python)
        print()
        install_requirements()
        print()
        install_playwright_chromium()
        print()
        setup_ollama_if_needed()
        print()
        print("=" * 56)
        print("  [OK] Tudo configurado! Iniciando o painel...")
        print("=" * 56)
        print()
    else:
        print("[OK] Ambiente ja configurado")
        print()

    painel_path = get_painel_path()
    if not painel_path:
        print("[ER] painel.py nao encontrado!")
        input("  Pressione Enter para sair...")
        sys.exit(1)

    print("[i] Iniciando painel web...")
    print("[i] O navegador vai abrir automaticamente.")
    print("[i] Para fechar, pressione Ctrl+C neste terminal.")
    print()

    port = 8501
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "streamlit", "run", painel_path,
         "--server.headless", "true",
         "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=str(APP_DIR),
    )

    if wait_for_streamlit(port, timeout=30):
        webbrowser.open(f"http://localhost:{port}")
        print("[OK] Painel aberto no navegador!")
    else:
        print("[i] Verifique o navegador manualmente: http://localhost:8501")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[i] Encerrando...")
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
