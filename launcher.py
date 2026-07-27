#!/usr/bin/env python3
"""BotDoProfessor — Launcher completo.

Versao embedded: NAO depende de Python instalado no sistema.
Cria venv, instala dependencias, configura IA local, inicia painel.
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
import urllib.request
import urllib.error
import zipfile
import json
from pathlib import Path

APP_DIR = Path.home() / ".bot_local"
VENV_DIR = APP_DIR / "venv"
OLLAMA_DIR = APP_DIR / "ollama"
OLLAMA_EXE = OLLAMA_DIR / "ollama.exe"
CONFIG_FILE = APP_DIR / "config.json"
DOWNLOAD_URL = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"

OLLAMA_MODEL = "openbmb/minicpm-v4.6"
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_PULL_TIMEOUT = 1800

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
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python310\python.exe"),
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
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


def _find_ollama_exe():
    """Encontra executavel do Ollama."""
    if OLLAMA_EXE.exists():
        return str(OLLAMA_EXE)

    system_ollama = shutil.which("ollama")
    if system_ollama:
        return system_ollama

    local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local_app.exists():
        return str(local_app)

    return None


def _is_ollama_running():
    """Verifica se o servico Ollama esta rodando."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _is_model_available(model_name):
    """Verifica se um modelo ja foi baixado."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            models = data.get("models", [])
            return any(model_name in m.get("name", "") for m in models)
    except Exception:
        return False


def _get_available_ram_gb():
    """Retorna RAM disponivel em GB."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        c_ulonglong = ctypes.c_ulonglong
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", c_ulonglong),
                ("ullAvailPhys", c_ulonglong),
                ("ullTotalPageFile", c_ulonglong),
                ("ullAvailPageFile", c_ulonglong),
                ("ullTotalVirtual", c_ulonglong),
                ("ullAvailVirtual", c_ulonglong),
                ("ullAvailExtendedVirtual", c_ulonglong),
            ]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        return mem.ullAvailPhys / (1024 ** 3)
    except Exception:
        return 8.0


def setup_ollama():
    """Baixa e instala Ollama + modelo minicpm-v4.6 automaticamente."""
    print()
    print("=" * 56)
    print("  Configuracao de IA Local (Ollama)")
    print("=" * 56)
    print()

    if _is_ollama_running() and _is_model_available(OLLAMA_MODEL):
        print("[OK] Ollama rodando com modelo minicpm-v4.6")
        return True

    exe = _find_ollama_exe()

    if not exe:
        print("[i] Ollama nao encontrado. Baixando instalador (~100MB)...")
        print("  [i] Isso leva 1-2 minutos.")

        installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
        try:
            print("  [i] Baixando de ollama.com...")
            urllib.request.urlretrieve(OLLAMA_INSTALLER_URL, installer_path)
            print("  [OK] Instalador baixado.")
        except Exception as exc:
            print(f"  [ER] Falha ao baixar Ollama: {exc}")
            print("  [i] Instale manualmente: https://ollama.com/download")
            return False

        print("  [i] Instalando Ollama (pode pedir permissao de admin)...")
        try:
            subprocess.run([installer_path, "/SILENT"], check=True, timeout=120)
            print("  [OK] Ollama instalado!")
            time.sleep(3)
        except Exception as exc:
            print(f"  [ER] Falha na instalacao: {exc}")
            return False

        exe = _find_ollama_exe()
        if not exe:
            print("[ER] Ollama instalado mas executavel nao encontrado.")
            return False

    if not _is_ollama_running():
        print("[i] Iniciando servico do Ollama...")
        try:
            subprocess.Popen([exe, "serve"], creationflags=subprocess.DETACHED_PROCESS)
            time.sleep(3)
            for _ in range(15):
                if _is_ollama_running():
                    break
                time.sleep(2)
        except Exception:
            pass

    if not _is_ollama_running():
        print("[ER] Servico do Ollama nao iniciou.")
        print("  [i] Tente iniciar manualmente: ollama serve")
        return False

    print("[OK] Ollama rodando!")

    avail_ram = _get_available_ram_gb()
    print(f"[i] RAM disponivel: {avail_ram:.1f} GB")

    if not _is_model_available(OLLAMA_MODEL):
        print()
        print(f"[i] Baixando modelo {OLLAMA_MODEL} (~1.6GB)...")
        print("  [i] Isso leva 3-8 minutos dependendo da internet.")
        print("  [i] O modelo e necessario para IA analisar portais quando o bot falhar.")
        print()
        try:
            result = subprocess.run([exe, "pull", OLLAMA_MODEL], timeout=OLLAMA_PULL_TIMEOUT)
            if result.returncode == 0:
                print(f"  [OK] Modelo {OLLAMA_MODEL} baixado!")
            else:
                print(f"  [ER] Erro ao baixar modelo (codigo {result.returncode}).")
                print(f"  [i] Tente manualmente: ollama pull {OLLAMA_MODEL}")
        except subprocess.TimeoutExpired:
            print(f"  [ER] Timeout baixando modelo apos {OLLAMA_PULL_TIMEOUT}s.")
            print(f"  [i] Tente manualmente: ollama pull {OLLAMA_MODEL}")
        except Exception as exc:
            print(f"  [ER] {exc}")
    else:
        print(f"[OK] Modelo {OLLAMA_MODEL} ja disponivel")

    return True


def ensure_ollama():
    """Garante que Ollama esteja instalado e rodando com modelo."""
    try:
        sys.path.insert(0, str(get_bundled_dir()))
        from ai_assist import OLLAMA_AUTO_SETUP
        if not OLLAMA_AUTO_SETUP:
            return _is_ollama_running()
    except ImportError:
        pass
    return setup_ollama()


def load_config():
    """Carrega configuracao salva."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config):
    """Salva configuracao."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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
    print("  Funciona SEM precisar instalar Python.")
    print("  Tudo configurado automaticamente na primeira vez.")
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

        config = load_config()
        if config.get("ai_provider", "local") == "local":
            setup_ollama()

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
