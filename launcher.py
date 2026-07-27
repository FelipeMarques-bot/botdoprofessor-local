#!/usr/bin/env python3
"""BotDoProfessor — Launcher embarcado.

Funciona SEM Python instalado no sistema.
Baixa Python portatil, cria venv, instala deps, inicia painel no navegador.
Tudo silencioso — sem janela de terminal.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import time
import threading
import zipfile
import urllib.request
import urllib.error
from pathlib import Path

APP_DIR = Path.home() / ".bot_local"
VENV_DIR = APP_DIR / "venv"
PORTABLE_PYTHON_DIR = APP_DIR / "python_portable"
CONFIG_FILE = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "launcher.log"

PYTHON_VERSION = "3.11.9"
PYTHON_ZIP_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

if os.name == "nt":
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
    PORTABLE_PYTHON = PORTABLE_PYTHON_DIR / "python.exe"
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"
    PORTABLE_PYTHON = PORTABLE_PYTHON_DIR / "python3"
    NO_WINDOW = 0


def log(msg):
    """Escreve no log file (silencioso)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _hide_console():
    """Esconde a janela do console no Windows."""
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def _set_utf8():
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


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
    """Encontra Python 3.11+ instalado no sistema."""
    import shutil as _shutil
    py = _shutil.which("py")
    if py and _is_valid_python(py):
        return py
    for name in ("python3", "python"):
        path = _shutil.which(name)
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


def download_portable_python():
    """Baixa Python portavel embutido (~11MB)."""
    log("Baixando Python portavel...")
    PORTABLE_PYTHON_DIR.mkdir(parents=True, exist_ok=True)

    if PORTABLE_PYTHON.exists():
        log("Python portavel ja existe")
        return True

    zip_path = os.path.join(tempfile.gettempdir(), f"python-{PYTHON_VERSION}-embed.zip")
    try:
        urllib.request.urlretrieve(PYTHON_ZIP_URL, zip_path)
        log("Download concluido")
    except Exception as e:
        log(f"Falha ao baixar Python: {e}")
        return False

    log("Extraindo Python portavel...")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(str(PORTABLE_PYTHON_DIR))
        os.remove(zip_path)
        log("Extraido com sucesso")
    except Exception as e:
        log(f"Falha ao extrair: {e}")
        return False

    pth_file = PORTABLE_PYTHON_DIR / f"python{PYTHON_VERSION.replace('.', '')}._pth"
    if pth_file.exists():
        content = pth_file.read_text(encoding="utf-8")
        content = content.replace("#import site", "import site")
        pth_file.write_text(content, encoding="utf-8")

    log("Configurando pip...")
    try:
        get_pip_path = os.path.join(tempfile.gettempdir(), "get-pip.py")
        urllib.request.urlretrieve(GET_PIP_URL, get_pip_path)
        subprocess.run(
            [str(PORTABLE_PYTHON), get_pip_path],
            capture_output=True, timeout=120, creationflags=NO_WINDOW,
        )
        os.remove(get_pip_path)
        log("pip instalado")
    except Exception as e:
        log(f"Falha ao instalar pip: {e}")
        return False

    return True


def get_python():
    """Retorna o caminho do Python: sistema ou portavel."""
    sys_py = find_system_python()
    if sys_py:
        log(f"Python do sistema: {sys_py}")
        return sys_py

    log("Python do sistema nao encontrado, verificando portavel...")
    if PORTABLE_PYTHON.exists():
        log("Usando Python portavel")
        return str(PORTABLE_PYTHON)

    log("Baixando Python portavel...")
    if download_portable_python():
        return str(PORTABLE_PYTHON)

    return None


def get_bundled_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_painel_path():
    bundled = get_bundled_dir() / "painel.py"
    if bundled.exists():
        return str(bundled)
    local = Path(__file__).parent / "painel.py"
    if local.exists():
        return str(local)
    return None


def run_silent(cmd, timeout=300):
    """Executa comando silenciosamente (sem console)."""
    log(f"Executando: {' '.join(str(c) for c in cmd[:3])}...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=NO_WINDOW,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            log(f"Erro (code {result.returncode}): {stderr}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"Timeout apos {timeout}s")
        return False
    except Exception as e:
        log(f"Excecao: {e}")
        return False


def create_venv(python_path):
    log("Criando ambiente virtual...")
    return run_silent([python_path, "-m", "venv", str(VENV_DIR)], timeout=120)


def install_requirements(pip_path):
    log("Instalando dependencias...")
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
    return run_silent(
        [str(pip_path), "install", "--quiet", "--disable-pip-version-check"] + reqs,
        timeout=600,
    )


def install_playwright_chromium(python_path):
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
                    log("Chromium ja instalado")
                    return True

    log("Baixando Chromium (~180MB)...")
    return run_silent(
        [python_path, "-m", "playwright", "install", "chromium"],
        timeout=300,
    )


def setup_ollama_background():
    """Instala Ollama em background (nao bloqueia)."""
    try:
        from ai_assist import OLLAMA_AUTO_SETUP
        if not OLLAMA_AUTO_SETUP:
            return
    except ImportError:
        pass

    ollama_dir = APP_DIR / "ollama"
    ollama_exe = ollama_dir / "ollama.exe"

    def _find_ollama():
        if ollama_exe.exists():
            return str(ollama_exe)
        import shutil as _shutil
        system_ollama = _shutil.which("ollama")
        if system_ollama:
            return system_ollama
        local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local_app.exists():
            return str(local_app)
        return None

    exe = _find_ollama()
    if not exe:
        log("Ollama nao encontrado — instalacao pulada")
        return

    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        urllib.request.urlopen(req, timeout=3)
        log("Ollama ja rodando")
        return
    except Exception:
        pass

    log("Iniciando Ollama...")
    try:
        subprocess.Popen(
            [exe, "serve"],
            creationflags=subprocess.DETACHED_PROCESS | NO_WINDOW,
        )
    except Exception as e:
        log(f"Falha ao iniciar Ollama: {e}")


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def wait_for_streamlit(port=8501, timeout=60):
    import urllib.error
    url = f"http://localhost:{port}"
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def show_error_box(title, message):
    """Mostra message box de erro (Windows)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            pass
    log(f"ERRO: {title} — {message}")


def main():
    _set_utf8()
    _hide_console()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("=" * 40)
    log("BotDoProfessor — Iniciando...")

    python = get_python()
    if not python:
        show_error_box(
            "BotDoProfessor",
            "Nao foi possivel encontrar ou baixar Python.\n\n"
            "Instale o Python: https://www.python.org/downloads/\n"
            "Marque 'Add Python to PATH' durante a instalacao."
        )
        sys.exit(1)

    if not VENV_DIR.exists():
        log("Primeira execucao — configurando ambiente...")
        if not create_venv(python):
            show_error_box("BotDoProfessor", "Falha ao criar ambiente virtual.")
            sys.exit(1)
        if not install_requirements(VENV_PIP):
            show_error_box("BotDoProfessor", "Falha ao instalar dependencias.\nVerifique sua conexao com a internet.")
            sys.exit(1)
        install_playwright_chromium(str(VENV_PYTHON))
        threading.Thread(target=setup_ollama_background, daemon=True).start()
        log("Configuracao concluida")
    else:
        log("Ambiente ja configurado")

    painel_path = get_painel_path()
    if not painel_path:
        show_error_box("BotDoProfessor", "Arquivo do painel nao encontrado.")
        sys.exit(1)

    log("Iniciando painel web...")
    port = 8501
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "streamlit", "run", painel_path,
         "--server.headless", "true",
         "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=str(APP_DIR),
        creationflags=NO_WINDOW,
    )

    import webbrowser
    if wait_for_streamlit(port, timeout=60):
        webbrowser.open(f"http://localhost:{port}")
        log("Navegador aberto!")
    else:
        log("Streamlit nao respondeu — tentando abrir manualmente...")
        webbrowser.open(f"http://localhost:{port}")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
