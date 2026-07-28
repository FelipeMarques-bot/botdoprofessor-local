#!/usr/bin/env python3
"""BotDoProfessor — Launcher embarcado.

Mostra splash screen com progresso, configura tudo silenciosamente,
e abre o navegador automaticamente.
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
import webbrowser
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
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


class SplashScreen:
    """Janela de progresso minimalista com tkinter."""

    def __init__(self):
        self.root = None
        self.label_status = None
        self.label_detail = None
        self._closed = False
        self._init_tk()

    def _init_tk(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.title("BotDoProfessor")
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)

            w, h = 420, 220
            sx = self.root.winfo_screenwidth()
            sy = self.root.winfo_screenheight()
            self.root.geometry(f"{w}x{h}+{(sx-w)//2}+{(sy-h)//2}")

            self.root.configure(bg="#0f3460")

            tk.Label(
                self.root, text="BotDoProfessor",
                font=("Segoe UI", 18, "bold"), fg="white", bg="#0f3460",
            ).pack(pady=(28, 4))

            tk.Label(
                self.root, text="Automatize suas notas no SGE",
                font=("Segoe UI", 10), fg="#94a3b8", bg="#0f3460",
            ).pack()

            self.label_status = tk.Label(
                self.root, text="Iniciando...",
                font=("Segoe UI", 11, "bold"), fg="white", bg="#0f3460",
            )
            self.label_status.pack(pady=(24, 4))

            self.label_detail = tk.Label(
                self.root, text="Aguarde, isso pode levar alguns minutos na primeira vez",
                font=("Segoe UI", 9), fg="#94a3b8", bg="#0f3460",
                wraplength=360,
            )
            self.label_detail.pack()

            self._progress_bar = tk.Frame(self.root, bg="#1b2a4a", height=4)
            self._progress_bar.pack(fill="x", padx=40, pady=(16, 0))
            self._progress_bar.pack_propagate(False)
            self._progress_fill = tk.Frame(self._progress_bar, bg="#e94560", width=0)
            self._progress_fill.pack(side="left", fill="y")

            self.root.update()
        except Exception as e:
            log(f"Falha ao criar splash: {e}")
            self.root = None

    def update(self, status, detail=""):
        if self._closed:
            return
        try:
            if self.label_status:
                self.label_status.config(text=status)
            if self.label_detail:
                self.label_detail.config(text=detail or "Aguarde...")
            if self.root:
                self.root.update()
        except Exception:
            pass

    def set_progress(self, fraction):
        if self._closed:
            return
        try:
            if self._progress_fill and self._progress_bar:
                w = int(self._progress_bar.winfo_width() * min(fraction, 1.0))
                self._progress_fill.config(width=w)
                if self.root:
                    self.root.update()
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.root:
                self.root.destroy()
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
    """Encontra Python 3.10+ instalado no sistema.
    Prioriza instalacoes diretas ( Programs\Python ) sobre o py launcher,
    pois o py pode retornar uma versao diferente da instalada.
    """
    candidates = []

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
            candidates.append(p)

    uv_base = os.path.expandvars(r"%APPDATA%\uv\python")
    if os.path.isdir(uv_base):
        import glob
        for uv_py in sorted(glob.glob(os.path.join(uv_base, "cpython-3.*", "python.exe")), reverse=True):
            if _is_valid_python(uv_py):
                candidates.append(uv_py)

    for name in ("python3", "python"):
        path = shutil.which(name)
        if _is_valid_python(path) and path not in candidates:
            candidates.append(path)

    py = shutil.which("py")
    if py and _is_valid_python(py) and py not in candidates:
        candidates.append(py)

    if candidates:
        return candidates[0]

    return None


def download_portable_python(splash):
    log("Baixando Python portavel...")
    PORTABLE_PYTHON_DIR.mkdir(parents=True, exist_ok=True)
    if PORTABLE_PYTHON.exists():
        log("Python portavel ja existe")
        return True

    splash.update("Baixando Python...", "Arquivo de ~11MB, rapido na primeira vez")
    zip_path = os.path.join(tempfile.gettempdir(), f"python-{PYTHON_VERSION}-embed.zip")
    try:
        urllib.request.urlretrieve(PYTHON_ZIP_URL, zip_path)
        log("Download concluido")
    except Exception as e:
        log(f"Falha ao baixar Python: {e}")
        return False

    splash.update("Extraindo Python...", "Isso leva poucos segundos")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(str(PORTABLE_PYTHON_DIR))
        os.remove(zip_path)
    except Exception as e:
        log(f"Falha ao extrair: {e}")
        return False

    pth_file = PORTABLE_PYTHON_DIR / f"python{PYTHON_VERSION.replace('.', '')}._pth"
    if pth_file.exists():
        content = pth_file.read_text(encoding="utf-8")
        content = content.replace("#import site", "import site")
        pth_file.write_text(content, encoding="utf-8")

    splash.update("Configurando pip...", "Preparando gerenciador de pacotes")
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


def get_python(splash):
    sys_py = find_system_python()
    if sys_py:
        log(f"Python do sistema: {sys_py}")
        return sys_py

    log("Python do sistema nao encontrado")
    if PORTABLE_PYTHON.exists():
        log("Usando Python portavel existente")
        return str(PORTABLE_PYTHON)

    if download_portable_python(splash):
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
    try:
        sys.path.insert(0, str(get_bundled_dir()))
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
        system_ollama = shutil.which("ollama")
        if system_ollama:
            return system_ollama
        local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local_app.exists():
            return str(local_app)
        return None

    exe = _find_ollama()
    if not exe:
        return

    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        urllib.request.urlopen(req, timeout=3)
        return
    except Exception:
        pass

    try:
        subprocess.Popen(
            [exe, "serve"],
            creationflags=subprocess.DETACHED_PROCESS | NO_WINDOW,
        )
    except Exception:
        pass


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def wait_for_streamlit(proc, port=8501, timeout=90, splash=None):
    """Aguarda Streamlit responder. Verifica se processo ainda esta vivo."""
    url = f"http://localhost:{port}"
    log_file = str(LOG_DIR / "streamlit.log")

    log(f"Aguardando Streamlit na porta {port}...")
    time.sleep(3)

    for i in range(timeout * 2):
        if proc.poll() is not None:
            stderr = ""
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    stderr = f.read()[-2000:]
            except Exception:
                pass
            log(f"Streamlit morreu (code {proc.returncode}). Log:\n{stderr}")
            return False, f"Streamlit encerrou inesperadamente (codigo {proc.returncode})\n\n{stderr[-500:]}"

        try:
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                return True, ""
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)

    return False, "Servidor nao respondeu em 90 segundos"


def show_error_box(title, message):
    log(f"ERRO: {title} — {message}")
    error_file = Path.home() / "Desktop" / "BotDoProfessor_erro.txt"
    try:
        with open(error_file, "w", encoding="utf-8") as f:
            f.write(f"BotDoProfessor — Log de Erro\n")
            f.write(f"Data: {time.strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write(f"{'='*50}\n\n")
            f.write(message)
            f.write(f"\n\n{'='*50}\n")
            f.write(f"Log completo: {LOG_FILE}\n")
        log(f"Erro salvo em: {error_file}")
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            pass


def _set_utf8():
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _hide_console():
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass


def main():
    _set_utf8()
    _hide_console()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("=" * 40)
    log("BotDoProfessor — Iniciando...")

    splash = SplashScreen()

    try:
        splash.update("Verificando Python...", "Procurando Python no sistema")
        python = get_python(splash)
        if not python:
            splash.close()
            show_error_box(
                "BotDoProfessor",
                "Nao foi possivel encontrar ou baixar Python.\n\n"
                "Instale o Python: https://www.python.org/downloads/\n"
                "Marque 'Add Python to PATH' durante a instalacao."
            )
            sys.exit(1)

        venv_valid = VENV_DIR.exists() and VENV_PYTHON.exists()

        if venv_valid:
            try:
                r = subprocess.run(
                    [str(VENV_PYTHON), "-c", "import sys; print(sys.version_info[:2])"],
                    capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
                )
                venv_ver = r.stdout.strip()
                r2 = subprocess.run(
                    [python, "-c", "import sys; print(sys.version_info[:2])"],
                    capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
                )
                sys_ver = r2.stdout.strip()
                log(f"Venv={venv_ver} Sistema={sys_ver}")
                if venv_ver != sys_ver:
                    log("Versao diferente — deletando venv")
                    venv_valid = False
            except Exception as e:
                log(f"Erro ao checar venv: {e}")
                venv_valid = False

        if not venv_valid:
            log("Deletando venv antigo...")
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(VENV_DIR)],
                    capture_output=True, timeout=60, creationflags=NO_WINDOW,
                )
            except Exception:
                pass
            try:
                shutil.rmtree(str(VENV_DIR), ignore_errors=True)
            except Exception:
                pass
            log("Criando venv novo...")
            splash.update("Configurando ambiente...", "Criando virtual environment (1/4)")
            splash.set_progress(0.1)
            if not create_venv(python):
                splash.close()
                show_error_box("BotDoProfessor", "Falha ao criar ambiente virtual.")
                sys.exit(1)

            splash.update("Instalando dependencias...", "Baixando pacotes necessarios (2/4)")
            splash.set_progress(0.2)
            if not install_requirements(VENV_PIP):
                splash.close()
                show_error_box("BotDoProfessor", "Falha ao instalar dependencias.\nVerifique sua conexao com a internet.")
                sys.exit(1)

            splash.update("Instalando navegador...", "Chromium para automacao (3/4)")
            splash.set_progress(0.6)
            install_playwright_chromium(str(VENV_PYTHON))

            splash.update("Configurando IA local...", "Ollama + modelo de visao (4/4)")
            splash.set_progress(0.8)
            threading.Thread(target=setup_ollama_background, daemon=True).start()

            log("Configuracao concluida")
        else:
            log("Venv OK, ambas versoes 3.12")

        painel_path = get_painel_path()
        if not painel_path:
            splash.close()
            show_error_box("BotDoProfessor", "Arquivo do painel nao encontrado.")
            sys.exit(1)

        if not VENV_PYTHON.exists():
            log(f"VENV_PYTHON nao encontrado: {VENV_PYTHON}")
            splash.close()
            show_error_box(
                "BotDoProfessor",
                f"Ambiente virtual incompleto.\n\n"
                f"Delete a pasta: {VENV_DIR}\n"
                f"e execute o programa novamente."
            )
            sys.exit(1)

        splash.update("Iniciando painel web...", "O navegador vai abrir automaticamente")
        splash.set_progress(0.9)
        log("Iniciando Streamlit...")

        port = 8501
        streamlit_log = open(str(LOG_DIR / "streamlit.log"), "w", encoding="utf-8")
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        clean_env.pop("PYTHONHOME", None)
        clean_env.pop("PYTHONNOUSERSITE", None)
        clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "streamlit", "run", painel_path,
             "--server.headless", "true",
             "--server.port", str(port),
             "--browser.gatherUsageStats", "false"],
            cwd=str(APP_DIR),
            stdout=streamlit_log,
            stderr=streamlit_log,
            env=clean_env,
        )

        splash.update("Aguardando painel...", "Verificando se o servidor esta pronto")
        splash.set_progress(0.95)

        ok, err_msg = wait_for_streamlit(proc, port, timeout=90, splash=splash)
        if ok:
            splash.update("Abrindo navegador...", "Pronto!")
            splash.set_progress(1.0)
            time.sleep(0.5)
            webbrowser.open(f"http://localhost:{port}")
            log("Navegador aberto!")
        else:
            log(f"Streamlit falhou: {err_msg}")
            splash.close()
            show_error_box(
                "BotDoProfessor",
                f"O painel nao abriu.\n\n"
                f"Detalhes: {err_msg}\n\n"
                f"Log completo: {LOG_FILE}\n\n"
                f"Tente abrir manualmente: http://localhost:{port}"
            )
            webbrowser.open(f"http://localhost:{port}")

        splash.close()

        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        finally:
            try:
                streamlit_log.close()
            except Exception:
                pass

    except Exception as e:
        log(f"Erro fatal: {e}")
        splash.close()
        show_error_box("BotDoProfessor", f"Erro inesperado:\n{e}")


if __name__ == "__main__":
    main()
