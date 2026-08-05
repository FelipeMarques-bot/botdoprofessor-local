"""
Gravador de fluxo da CHAMADA no SGE (modo aprendizado manual).

Uso:
    python gravar_chamada.py
    python gravar_chamada.py --outdir artifacts/chamada-recording

Como funciona:
    1. Abre o SGE com navegador visivel (HEADLESS=0)
    2. Voce faz o fluxo da chamada manualmente (login, escola/turma, abrir a
       chamada do dia, marcar presenca/falta/falta justificada, salvar)
    3. O script captura screenshot + HTML + DOM em cada passo:
       - automaticamente quando a URL muda
       - manualmente ao pressionar [ENTER]
    4. Ao final, os artefatos ficam em outdir/ para analise e geracao do
       adaptador deterministico (sge_chamada_adapter.py)

Teclas no terminal:
    [ENTER]   captura o estado atual da tela
    n         captura com uma anotacao (digite depois do 'n')
    q         encerra e fecha o navegador
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright nao instalado. Rode: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False


DEFAULT_SGE_LOGIN_URL = "https://www.sge8147.com.br/hportalprofessor.aspx"


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name or "passo")


def _frame_summary(scope):
    def _el_info(el):
        return {
            "tag": (el.tagName or "").lower(),
            "name": el.getAttribute("name") or "",
            "id": el.getAttribute("id") or "",
            "class": el.getAttribute("class") or "",
            "type": el.getAttribute("type") or "",
            "value": (el.value or "").strip()[:120] if el.tagName in ("INPUT", "TEXTAREA", "SELECT") else "",
        }

    try:
        inputs = scope.evaluate("""
            () => Array.from(document.querySelectorAll('input, select, textarea'))
                .slice(0, 400)
                .map((el) => ({
                    tag: el.tagName.toLowerCase(),
                    name: el.getAttribute('name') || '',
                    id: el.getAttribute('id') || '',
                    cls: el.getAttribute('class') || '',
                    type: el.getAttribute('type') || '',
                    value: (el.value || '').trim().slice(0, 120)
                }))
        """)
    except Exception:
        inputs = []

    try:
        tables = scope.evaluate("""
            () => Array.from(document.querySelectorAll('table'))
                .slice(0, 6)
                .map((t) => {
                    const rows = Array.from(t.querySelectorAll('tr'));
                    const head = rows.slice(0, 2).map((r) =>
                        Array.from(r.querySelectorAll('th, td')).map((c) =>
                            (c.textContent || '').trim().slice(0, 60)
                        )
                    );
                    return { id: t.getAttribute('id') || '', head, nrows: rows.length };
                })
        """)
    except Exception:
        tables = []

    try:
        links = scope.evaluate("""
            () => Array.from(document.querySelectorAll('a, input[type="image"]'))
                .slice(0, 150)
                .map((el) => ({
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || '').trim().slice(0, 60),
                    name: el.getAttribute('name') || '',
                    id: el.getAttribute('id') || '',
                    title: el.getAttribute('title') || '',
                    alt: el.getAttribute('alt') || '',
                    src: el.getAttribute('src') || '',
                    onclick: el.getAttribute('onclick') || '',
                }))
        """)
    except Exception:
        links = []

    return {"inputs": inputs, "tables": tables, "links": links}


def _capture_step(page, outdir: Path, step: int, note: str = "", extra: dict = None):
    outdir.mkdir(parents=True, exist_ok=True)
    base = f"step_{step:03d}"
    try:
        page.screenshot(path=str(outdir / f"{base}_screen.png"), full_page=True)
    except Exception as exc:
        print(f"  [gravador] ERRO screenshot: {exc}")

    try:
        html = page.content()
        (outdir / f"{base}_page.html").write_text(html, encoding="utf-8")
    except Exception as exc:
        print(f"  [gravador] ERRO html: {exc}")

    try:
        (outdir / f"{base}_dom.json").write_text(
            json.dumps(_frame_summary(page), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"  [gravador] ERRO dom: {exc}")

    frames = []
    try:
        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            try:
                fhtml = frame.content()
                (outdir / f"{base}_frame{i}.html").write_text(fhtml, encoding="utf-8")
                frames.append({"idx": i, "url": frame.url})
            except Exception:
                continue
    except Exception:
        pass

    meta = {
        "step": step,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "url": page.url,
        "title": page.title() if page.title() else "",
        "note": note,
        "frames": frames,
    }
    (outdir / f"{base}_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  [gravador] {_now()} capturado passo {step} ({note or 'sem nota'}) -> {base}")


def _wait_for_key(timeout_ms: int):
    if not HAS_MSVCRT:
        return None
    deadline = time.time() + timeout_ms / 1000.0
    buf = []
    while time.time() < deadline:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch == "\r" or ch == "\n":
                return ("enter", "".join(buf))
            if ch == "\x00" or ch == "\xe0":
                msvcrt.getwch()
                continue
            buf.append(ch)
        time.sleep(0.05)
    return None


def _prompt_choice():
    while True:
        print("")
        print(">>> Acao? [ENTER]=capturar  [n]=capturar+nota  [q]=sair")
        if HAS_MSVCRT:
            result = _wait_for_key(15000)
            if result is None:
                print("  (sem acao em 15s; aguardando proximo passo...)")
                return None
            key, text = result
        else:
            line = input(">>> ").strip()
            key, text = ("q", "") if line.lower() == "q" else ("n" if line.lower().startswith("n") else ("enter", ""))
        if key == "q":
            return "quit"
        if key == "n":
            if HAS_MSVCRT:
                nota = input("  Nota da captura: ").strip()
            else:
                nota = (text[1:] if text and text[0].lower() == "n" else text).strip()
            return ("capture", nota or "sem nota")
        return ("capture", "")


def main():
    parser = argparse.ArgumentParser(description="Gravador do fluxo de CHAMADA no SGE")
    parser.add_argument("--outdir", default="artifacts/chamada-recording")
    parser.add_argument("--login-url", default=os.environ.get("SGE_LOGIN_URL", DEFAULT_SGE_LOGIN_URL))
    parser.add_argument("--prefill-login", action="store_true",
                        help="Preenche CPF/senha automaticamente se estiverem no .env")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("GRAVADOR DA CHAMADA - SGE")
    print("=" * 60)
    print("Faca o fluxo completo manualmente no navegador:")
    print("  1. Login no portal do professor")
    print("  2. Selecione escola/turno/turma")
    print("  3. Abra a CHAMADA do dia (diario de classe)")
    print("  4. Marque: presenca (.), falta (F) e FALTA JUSTIFICADA (J) com")
    print("     os 5 motivos (medica, obito, suspensao, justificada, extra classe)")
    print("  5. Salve e confira o resultado")
    print("")
    print("Cada tela relevante sera capturada automaticamente (mudanca de URL).")
    print("DICA: aperte ENTER no terminal apos abrir POPUPS/dialogos (ex.: motivo")
    print("da falta justificada) para capturar o HTML do dialogo.")
    print("Artefatos sao salvos em:", outdir)
    print("")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(30000)

        print(f"Abrindo {args.login_url} ...")
        try:
            page.goto(args.login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print(f"  [gravador] Aviso ao abrir login: {exc}")

        if args.prefill_login:
            cpf = os.environ.get("SGE_CPF", "")
            senha = os.environ.get("SGE_SENHA", "")
            if cpf:
                try:
                    for sel in ["input[name='_USUCOD']", "input[name*='cpf' i]", "input[id*='cpf' i]"]:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.fill(cpf)
                            break
                except Exception:
                    pass
            if senha:
                try:
                    loc = page.locator("input[type='password']")
                    if loc.count() > 0:
                        loc.first.fill(senha)
                except Exception:
                    pass

        step = 0
        last_url = page.url
        pending_url = None
        pending_since = 0.0
        last_capture_ts = 0.0
        MIN_INTERVAL = 2.0
        quit_flag = False

        def do_capture(note=""):
            nonlocal step, last_capture_ts
            now = time.time()
            if now - last_capture_ts < MIN_INTERVAL:
                return
            step += 1
            _capture_step(page, outdir, step, note=note)
            last_capture_ts = time.time()

        print("[gravador] Pronto. Navegue no SGE e use ENTER/q no terminal quando quiser.")
        print("[gravador] (voce pode alternar entre o navegador e este terminal)")

        while not quit_flag:
            try:
                current = page.url
            except Exception:
                break

            if current != last_url:
                if pending_url is None:
                    pending_url = current
                    pending_since = time.time()
                elif pending_url == current and time.time() - pending_since >= 1.5:
                    do_capture(note=f"auto: url={current}")
                    pending_url = None
                elif pending_url != current:
                    pending_url = current
                    pending_since = time.time()
            last_url = current

            action = _prompt_choice()
            if action is None:
                continue
            if action == "quit":
                quit_flag = True
                break
            do_capture(note=action[1] if isinstance(action, tuple) else "")

        browser.close()

    print("=" * 60)
    print(f"Gravacao concluida. Artefatos em: {outdir.resolve()}")
    print("Proximo passo: analisar os passos e escrever o sge_chamada_adapter.py")


if __name__ == "__main__":
    main()
