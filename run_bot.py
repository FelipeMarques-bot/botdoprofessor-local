#!/usr/bin/env python3
"""BotDoProfessor-Local — Executavel interativo.

Executavel CLI que o usuario final roda na maquina local.
Valida licenca, conecta no SGE e executa lancamentos.
"""

import os
import re
import sys
import csv
import json
import tempfile
import logging
import subprocess
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Forcar codepage UTF-8 no Windows (resolve charmap do node.exe do playwright)
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

CONFIG_DIR = Path.home() / ".bot_local"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

DOWNLOAD_URL = "https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest"
SERVER_URL = os.environ.get("SERVER_URL", "https://botdoprofessor.onrender.com")


def setup_logging():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = CONFIG_DIR / "logs" / "bot.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(fh)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print("=" * 50)
    print("       BotDoProfessor - Automatize suas notas")
    print("=" * 50)
    print()


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _find_python():
    """Encontra o interpretador Python real do sistema (ignora stubs da Microsoft Store)."""
    import shutil
    import stat

    def _is_valid_python(path):
        """Verifica se o caminho aponta para um Python real (ignora WindowsApps stubs)."""
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

    # 1. py launcher (mais confiavel no Windows)
    py_path = shutil.which("py")
    if py_path and _is_valid_python(py_path):
        return py_path

    # 2. python3 / python — pular stubs da Store
    for name in ("python3", "python"):
        path = shutil.which(name)
        if _is_valid_python(path):
            return path

    # 3. Buscar em locais comuns de instalacao (uv, python.org, etc.)
    uv_base = os.path.expandvars(r"%APPDATA%\uv\python")
    common_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python310\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
        r"C:\Python312\python.exe",
    ]
    if os.path.isdir(uv_base):
        import glob
        for uv_py in sorted(glob.glob(os.path.join(uv_base, "cpython-3.*", "python.exe")), reverse=True):
            common_paths.insert(0, uv_py)
    for p in common_paths:
        if os.path.isfile(p):
            return p

    return sys.executable


def check_playwright():
    """Verifica se Playwright + Chromium estao disponiveis."""
    # Checar se o binario do Chromium existe no diretorio padrao
    ms_playwright = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not ms_playwright.exists():
        ms_playwright = Path.home() / ".cache" / "ms-playwright"
    if ms_playwright.exists():
        for d in ms_playwright.iterdir():
            if d.is_dir() and d.name.startswith("chromium-"):
                chrome = d / "chrome-win64" / "chrome.exe"
                if not chrome.exists():
                    chrome = d / "chrome-win" / "chrome.exe"
                if not chrome.exists():
                    chrome = d / "chrome-linux" / "chrome"  # Linux
                if not chrome.exists():
                    chrome = d / "chrome-mac" / "Chromium.app"  # Mac
                if chrome.exists():
                    return True
    # Fallback: tentar importar e lancar (pode falhar no .exe por encoding)
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            browser = p.chromium.launch(headless=True)
            browser.close()
        except Exception:
            p.stop()
            return False
        p.stop()
        return True
    except (ImportError, Exception):
        return False


def install_playwright():
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        # Dentro do .exe: o playwright ja esta bundled.
        # Tenta instalar o Chromium usando o driver bundled.
        print("[!] Playwright detectado, mas Chromium nao encontrado.")
        print("[i] Baixando Chromium (~180MB, primeira vez)...")
        try:
            # Dentro do .exe frozen, extrair driver path diretamente
            base = Path(sys._MEIPASS) / "playwright" / "driver"
            node_exe = base / "node.exe"
            cli_js = base / "package" / "cli.js"
            if not node_exe.exists():
                raise FileNotFoundError(f"node.exe nao encontrado em {node_exe}")
            print(f"[i] Driver: {node_exe}")
            subprocess.run([str(node_exe), str(cli_js), "install", "chromium"], check=True)
            print("  [OK] Chromium instalado")
            return
        except Exception as e:
            print(f"  [ER] Falha ao baixar Chromium automaticamente: {e}")
            print("[i] Instale manualmente:")
            print("    1. pip install playwright")
            print("    2. python -m playwright install chromium")
            print(f"[i] Ou baixe o .exe novamente: {DOWNLOAD_URL}")
            return

    # Modo script: instala via Python do sistema
    python = _find_python()
    print("[!] Playwright nao encontrado.")
    print(f"[i] Usando Python: {python}")
    print("[i] Instalando playwright...")
    try:
        subprocess.run([python, "-m", "pip", "install", "playwright", "--quiet"], check=True)
        print("  [OK] playwright instalado")
    except Exception as e:
        print(f"  [ER] Falha ao instalar playwright: {e}")
        print("[i] Tente manualmente: pip install playwright")
        return

    print("[i] Baixando Chromium (~180MB, primeira vez)...")
    try:
        subprocess.run([python, "-m", "playwright", "install", "chromium"], check=True)
        print("  [OK] Chromium instalado")
    except Exception as e:
        print(f"  [ER] Falha ao baixar Chromium: {e}")
        print("[i] Tente manualmente: python -m playwright install chromium")


def validate_license(license_key):
    """Valida a licenca com o servidor."""
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            f"{SERVER_URL}/api/license/public-validate",
            data=json.dumps({"license_key": license_key}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode())
            return data
        except Exception:
            return {"valid": False, "error": f"Erro HTTP {e.code}"}
    except Exception as e:
        return {"valid": False, "error": f"Servidor indisponivel: {e}"}


def get_license_key():
    config = load_config()
    saved_key = config.get("license_key", "")
    if saved_key:
        print(f"[i] Licenca salva: {saved_key[:8]}...{saved_key[-4:]}")
        use_saved = input("Usar licenca salva? (S/n): ").strip().lower()
        if use_saved != "n":
            return saved_key

    key = input("Chave de licenca: ").strip()
    if not key:
        print("[ER] Chave obrigatoria.")
        return get_license_key()
    return key


def get_sge_credentials():
    config = load_config()
    saved_cpf = config.get("cpf", "")
    if saved_cpf:
        print(f"[i] CPF salvo: {saved_cpf[:3]}***{saved_cpf[-2:]}")
        use_saved = input("Usar CPF salvo? (S/n): ").strip().lower()
        if use_saved != "n":
            return saved_cpf

    cpf = input("CPF (apenas numeros): ").strip().replace(".", "").replace("-", "")
    return cpf


def get_context():
    config = load_config()
    print()
    print("[i] Configuracao do lancamento")
    print("-" * 40)

    escola = input(f"Escola [{config.get('escola', '')}]: ").strip()
    if not escola:
        escola = config.get("escola", "")

    turno = input(f"Turno [{config.get('turno', 'Manha')}]: ").strip()
    if not turno:
        turno = config.get("turno", "Manha")

    turma = input(f"Turma [{config.get('turma', '')}]: ").strip()
    if not turma:
        turma = config.get("turma", "")

    trimestre = input(f"Trimestre [{config.get('trimestre', '1o Trimestre')}]: ").strip()
    if not trimestre:
        trimestre = config.get("trimestre", "1o Trimestre")

    save_config({
        **config,
        "escola": escola,
        "turno": turno,
        "turma": turma,
        "trimestre": trimestre,
    })

    return {"escola": escola, "turno": turno, "turma": turma, "trimestre": trimestre}


def is_gsheets_url(url):
    """Verifica se e uma URL do Google Sheets."""
    return bool(re.search(r"docs\.google\.com/spreadsheets", url))


def download_gsheets_as_csv(url):
    """Baixa uma planilha Google Sheets como CSV."""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        print("[ER] Nao foi possivel extrair o ID da planilha.")
        return None

    sheet_id = m.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    print(f"[i] Baixando planilha do Google Sheets...")

    try:
        tmp_dir = tempfile.mkdtemp(prefix="gsheets_")
        target = os.path.join(tmp_dir, "planilha.csv")
        req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(target, "wb") as f:
            f.write(data)
        print(f"[OK] Planilha baixada: {len(data)} bytes")
        return target
    except Exception as e:
        print(f"[ER] Falha ao baixar: {e}")
        return None


def load_grades_from_file(filepath):
    """Carrega notas de um arquivo CSV ou Excel."""
    ext = Path(filepath).suffix.lower()
    grades = []

    if ext == ".csv":
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                reader = csv.DictReader(f, delimiter=",")
                f.seek(0)
            for row in reader:
                aluno = ""
                nota = ""
                for key, val in row.items():
                    kl = (key or "").lower().strip()
                    if "aluno" in kl or "nome" in kl:
                        aluno = (val or "").strip()
                    elif "nota" in kl or "valor" in kl or "media" in kl:
                        nota = (val or "").strip()
                if aluno and nota:
                    grades.append({"aluno": aluno, "nota": nota})
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            headers = [str(c.value or "").lower() for c in next(ws.iter_rows(max_row=1))]
            aluno_idx = next((i for i, h in enumerate(headers) if "aluno" in h or "nome" in h), None)
            nota_idx = next((i for i, h in enumerate(headers) if "nota" in h or "valor" in h or "media" in h), None)
            if aluno_idx is not None and nota_idx is not None:
                for row in ws.iter_rows(min_row=2, values_only=True):
                    aluno = str(row[aluno_idx] or "").strip()
                    nota = str(row[nota_idx] or "").strip()
                    if aluno and nota:
                        grades.append({"aluno": aluno, "nota": nota})
            wb.close()
        except ImportError:
            print("[ER] Para ler .xlsx, instale: pip install openpyxl")
            return []
    else:
        print(f"[ER] Formato nao suportado: {ext}")
        return []

    return grades


def execute_grades(cpf, context):
    print()
    print("[i] Modo: Lancamento de notas")
    print("-" * 40)
    print("  [1] Inserir notas manualmente")
    print("  [2] Importar de arquivo (CSV/Excel)")
    print()

    choice = input("Opcao: ").strip()

    grades = []
    if choice == "2":
        filepath = input("Caminho do arquivo ou URL do Google Sheets: ").strip().strip('"')

        if is_gsheets_url(filepath):
            downloaded = download_gsheets_as_csv(filepath)
            if not downloaded:
                return
            filepath = downloaded
        elif not os.path.isfile(filepath):
            print(f"[ER] Arquivo nao encontrado: {filepath}")
            return

        grades = load_grades_from_file(filepath)
        if not grades:
            print("[ER] Nenhuma nota encontrada no arquivo.")
            return
        print(f"[OK] {len(grades)} notas carregadas.")
    else:
        print("Digite as notas (aluno;nota). Linha vazia para finalizar:")
        while True:
            line = input("  > ").strip()
            if not line:
                break
            parts = line.split(";")
            if len(parts) >= 2:
                grades.append({"aluno": parts[0].strip(), "nota": parts[1].strip()})
            else:
                print("  [!] Formato: aluno;nota")

    if not grades:
        print("[ER] Nenhuma nota para lancar.")
        return

    print()
    print(f"[i] Lançando {len(grades)} notas...")
    print()

    from bot.core.sge_adapter import SGEAdapter
    from bot.core.portal_adapter import PortalContext
    from bot.core.engine import BotEngine

    adapter = SGEAdapter()
    try:
        print("  Iniciando browser...")
        adapter.start()
        print("  [OK] Browser iniciado")

        print("  Fazendo login no SGE...")
        if not adapter.login(cpf, ""):
            print("  [ER] Login falhou. Verifique o CPF.")
            return
        print("  [OK] Login realizado")

        ctx = PortalContext(
            escola=context["escola"],
            turno=context["turno"],
            turma=context["turma"],
            trimestre=context["trimestre"],
        )

        print("  Navegando...")
        adapter.navigate_to(ctx)
        print("  [OK] Navegacao concluida")

        engine = BotEngine(adapter, execution_id="cli-exec")
        result = engine.run(grades, context=ctx)

        print()
        print("=" * 40)
        print("  RESULTADO")
        print("=" * 40)
        print(f"  Lançadas: {result.filled}")
        print(f"  Falhas:   {result.failed}")
        print(f"  Puladas:  {result.skipped}")

        if result.failed > 0:
            print()
            print("  Detalhes das falhas:")
            for d in result.details:
                if d.get("status") in ("failed", "error"):
                    print(f"    - {d['aluno']}: {d.get('reason', d.get('error', '?'))}")

        if result.filled > 0:
            print()
            save = input("  Salvar no SGE? (S/n): ").strip().lower()
            if save != "n":
                adapter.save()
                print("  [OK] Salvo com sucesso")

    except Exception as e:
        print(f"  [ER] Erro: {e}")
        logging.exception("Erro na execucao")
    finally:
        adapter.stop()


def execute_lesson_plan(cpf, context):
    print()
    print("[i] Modo: Plano de Aula")
    print("-" * 40)

    titulo = input("Titulo do plano: ").strip()
    if not titulo:
        print("[ER] Titulo obrigatorio.")
        return

    data_inicio = input("Data inicio (DD/MM/AAAA): ").strip()
    data_fim = input("Data fim (DD/MM/AAAA): ").strip()
    n_aulas = input("Numero de aulas [1]: ").strip()
    n_aulas = int(n_aulas) if n_aulas.isdigit() else 1

    pdf_path = input("Caminho do PDF (vazio para pular): ").strip().strip('"')
    if pdf_path and not os.path.isfile(pdf_path):
        print(f"[ER] Arquivo nao encontrado: {pdf_path}")
        pdf_path = ""

    print()
    print(f"[i] Criando plano: {titulo}")
    print(f"    Periodo: {data_inicio} a {data_fim}")
    print(f"    Aulas: {n_aulas}")

    from bot.core.sge_adapter import SGEAdapter
    from bot.core.portal_adapter import PortalContext, LessonPlan

    adapter = SGEAdapter()
    try:
        print("  Iniciando browser...")
        adapter.start()
        print("  [OK] Browser iniciado")

        print("  Fazendo login no SGE...")
        if not adapter.login(cpf, ""):
            print("  [ER] Login falhou. Verifique o CPF.")
            return
        print("  [OK] Login realizado")

        ctx = PortalContext(
            escola=context["escola"],
            turno=context["turno"],
            turma=context["turma"],
            trimestre=context["trimestre"],
        )

        print("  Navegando para Plano de Aulas...")
        if not adapter.navigate_to_lesson_plan(ctx):
            print("  [ER] Nao foi possivel navegar para Plano de Aulas.")
            return
        print("  [OK] Navegacao concluida")

        plan = LessonPlan(
            titulo=titulo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            n_aulas=n_aulas,
        )

        print("  Criando planejamento...")
        if not adapter.create_lesson_plan(plan):
            print("  [ER] Falha ao criar planejamento.")
            return
        print("  [OK] Planejamento criado")

        if pdf_path:
            print("  Enviando PDF...")
            if adapter.upload_lesson_plan_pdf(titulo, pdf_path):
                print("  [OK] PDF enviado")
            else:
                print("  [!!] Falha ao enviar PDF (planejamento ja criado)")

        print()
        print("[OK] Plano de aula executado com sucesso!")

    except Exception as e:
        print(f"  [ER] Erro: {e}")
        logging.exception("Erro na execucao")
    finally:
        adapter.stop()


def start_dashboard():
    """Inicia o dashboard Streamlit em background."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "dashboard.py",
             "--server.headless", "true", "--server.port", "8501"],
            cwd=str(Path(__file__).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print("[OK] Dashboard aberto em http://localhost:8501")
    except Exception:
        print("[!!] Nao foi possivel abrir o dashboard automaticamente")


def main():
    setup_logging()
    clear()
    banner()

    if not check_playwright():
        install_playwright()
        if not check_playwright():
            print("[ER] Playwright nao pudo ser instalado.")
            print(f"[!] Baixe manualmente: {DOWNLOAD_URL}")
            input("\nPressione Enter para sair...")
            sys.exit(1)

    print("[OK] Playwright detectado")
    print()
    start_dashboard()
    print()

    license_key = get_license_key()
    print("[i] Validando licenca...")
    lic_result = validate_license(license_key)

    if not lic_result.get("valid"):
        print(f"[ER] Licenca invalida: {lic_result.get('error', 'desconhecido')}")
        input("\nPressione Enter para sair...")
        sys.exit(1)

    plan = lic_result.get("plan", "?")
    days = lic_result.get("days_remaining", "?")
    print(f"[OK] Licenca valida — plano: {plan} — {days} dias restantes")

    save_config({"license_key": license_key})
    cpf = get_sge_credentials()
    save_config({"cpf": cpf})
    context = get_context()

    print()
    print("[i] Tipo de lancamento:")
    print("  [1] Notas")
    print("  [2] Plano de Aula")
    print()

    choice = input("Opcao: ").strip()

    if choice == "2":
        execute_lesson_plan(cpf, context)
    else:
        execute_grades(cpf, context)

    print()
    print("=" * 50)
    print("  Operacao concluida!")
    print(f"  Logs: {CONFIG_DIR / 'logs' / 'bot.log'}")
    print("=" * 50)
    input("\nPressione Enter para sair...")


if __name__ == "__main__":
    main()
