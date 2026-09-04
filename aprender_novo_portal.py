"""Aprendizado de um portal novo pelo modo manual guiado.

Uso (a partir do painel):
    1. Escolha "Novo Portal" no seletor de portal.
    2. Informe URL, CPF e senha.
    3. Clique em EXECUTAR. (O modo aprendizado e ativado automaticamente.)

O navegador abre (visivel) na URL informada. O usuario faz o acesso
manualmente (login, navegacao ate a grade, etc.). O bot grava cada passo
(screenshot + metadados). Ao fechar o navegador, a IA local gera o plano
de automacao e o portal fica registrado para uso futuro.

Tambem pode ser usado por linha de comando:

    python aprender_novo_portal.py --url https://portal.exemplo.br --cpf 000 --senha xxx

Encerre fechando a janela do navegador (ou aguardando o tempo limite).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_OUTDIR = "artifacts/novo-portal"


def _log(logger, msg):
    if logger:
        try:
            logger(msg)
        except Exception:
            pass


def _slug_from_url(url: str) -> str:
    host = re.sub(r"^https?://", "", (url or "").strip().lower())
    host = host.split("/")[0].split(":")[0]
    host = host.replace("www.", "").split(".")[0]
    slug = re.sub(r"[^a-z0-9_]+", "_", host).strip("_")
    return f"novo_portal_{slug}" if slug else "novo_portal"


def _dom_signature(page) -> str:
    try:
        text = page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 3000)"
        ) or ""
        title = page.title() or ""
        return hashlib.md5(f"{title}|{text}".encode("utf-8", "ignore")).hexdigest()
    except Exception:
        return ""


def _try_prefill_login(page, cpf: str, senha: str, logger=None):
    """Tenta preencher CPF/senha com seletores comuns. Falha silenciosamente."""
    if not cpf and not senha:
        return
    try:
        if cpf:
            for sel in [
                "input[name*='cpf' i]",
                "input[id*='cpf' i]",
                "input[name*='login' i]",
                "input[name*='usuario' i]",
                "input[name*='user' i]",
                "input[name*='_USUCOD' i]",
            ]:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill(cpf)
                    break
        if senha:
            loc = page.locator("input[type='password']")
            if loc.count() > 0:
                loc.first.fill(senha)
        _log(logger, "[Aprender] Preenchimento automatico de login tentado.")
    except Exception:
        pass


def _register_portal(portal_name: str, plan: dict, outdir: Path):
    """Registra o portal aprendido na memoria para uso futuro."""
    try:
        from bot.core.portal_memory import PortalMemory
        from bot.core.portal_discovery import PortalDiscovery

        memory = PortalMemory(portal_name)
        memory.record_navigation("learned_plan", json.dumps(plan, ensure_ascii=False))
        memory.record_navigation("learned_at", datetime.utcnow().isoformat())

        discovery = PortalDiscovery()
        config = {
            "portal_name": portal_name,
            "learned": True,
            "workflow_name": plan.get("workflow_name", ""),
            "steps": plan.get("steps", []),
            "observations": plan.get("observations", []),
        }
        discovery.save_discovery(config, portal_name=portal_name)

        learned_copy = Path.home() / ".bot_local" / "portal_memory" / portal_name.lower().replace(" ", "_") / "learned_plan.json"
        learned_copy.parent.mkdir(parents=True, exist_ok=True)
        learned_copy.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(None, f"[Aprender] Portal '{portal_name}' registrado em {learned_copy}")
        return True
    except Exception:
        return False


def executar_aprendizado(
    url: str = "",
    cpf: str = "",
    senha: str = "",
    portal_name: str = "",
    outdir: str = DEFAULT_OUTDIR,
    max_minutes: int = 30,
    logger=None,
):
    """Executa a sessao de aprendizado de um portal novo.

    Abre o navegador visivel, grava os passos do usuario e, ao final,
    gera o plano de automacao com a IA local. Retorna dict resumo.
    """
    if not url:
        raise ValueError("Informe a URL do novo portal.")
    if not cpf or not senha:
        raise ValueError("Informe CPF e senha do novo portal.")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    portal_name = (portal_name or _slug_from_url(url)).strip()
    _log(logger, f"[Aprender] Iniciando aprendizado do portal '{portal_name}' ({url})")
    _log(logger, "[Aprender] Modo aprendizado ativo: os passos serao gravados.")

    try:
        import ai_assist
    except ImportError:
        ai_assist = None

    if ai_assist is not None:
        ai_assist.AI_RECORDING_DIR = str(outdir)
        ai_assist.AI_LEARN_MODE = True
    os.environ["AI_LEARN_MODE"] = "1"
    os.environ["AI_RECORDING_DIR"] = str(outdir)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright nao instalado. Rode: pip install playwright && playwright install chromium")

    step = 0
    last_capture_ts = 0.0
    MIN_INTERVAL = 1.5

    def do_capture(page, note: str):
        nonlocal step, last_capture_ts
        now = time.time()
        if now - last_capture_ts < MIN_INTERVAL:
            return
        step += 1
        if ai_assist is not None:
            try:
                ai_assist.record_demonstration_step(
                    step, page, note or "acesso manual", user_description=note or "", logger=logger
                )
            except Exception as exc:
                _log(logger, f"[Aprender] Erro ao gravar passo {step}: {exc}")
        last_capture_ts = time.time()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30000)

            _log(logger, f"[Aprender] Abrindo {url} ...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                _log(logger, f"[Aprender] Aviso ao abrir a URL: {exc}")

            _try_prefill_login(page, cpf, senha, logger=logger)
            _log(logger, "[Aprender] Navegue manualmente no portal (login, turma, grade, salvar).")
            _log(logger, "[Aprender] Cada tela relevante sera gravada automaticamente.")
            _log(logger, "[Aprender] Quando terminar, FECHE a janela do navegador.")

            time.sleep(2)
            do_capture(page, "abriu portal")

            last_url = ""
            last_dom = ""
            start = time.time()
            deadline = start + max_minutes * 60

            while True:
                if time.time() > deadline:
                    _log(logger, "[Aprender] Tempo limite atingido. Encerrando gravacao.")
                    break
                try:
                    current = page.url
                    _ = page.title()
                except Exception:
                    _log(logger, "[Aprender] Navegador fechado pelo usuario. Encerrando gravacao.")
                    break

                dom = _dom_signature(page)
                if current != last_url:
                    do_capture(page, f"navegou para {current}")
                    last_url = current
                    last_dom = dom
                elif dom != last_dom and time.time() - last_capture_ts >= MIN_INTERVAL:
                    do_capture(page, "tela mudou")
                    last_dom = dom

                time.sleep(0.4)

            _log(logger, f"[Aprender] {step} passo(s) gravado(s) em {outdir}")

            if ai_assist is not None and step > 0:
                _log(logger, "[Aprender] Gerando plano de automacao com a IA local...")
                plan = ai_assist.learn_from_recording(logger=logger)
            else:
                plan = None
    except Exception as exc:
        _log(logger, f"[Aprender] Erro durante a sessao: {exc}")
        plan = None

    if not plan:
        _log(logger, "[Aprender] Nao foi possivel gerar o plano (veja os passos gravados).")
        return {
            "ok": False,
            "portal": portal_name,
            "steps": step,
            "outdir": str(outdir),
            "plan": None,
        }

    plan_path = outdir / "learned_plan.json"
    try:
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(logger, f"[Aprender] Plano salvo em: {plan_path}")
    except Exception:
        pass

    registered = _register_portal(portal_name, plan, outdir)
    _log(logger, f"[Aprender] Portal '{portal_name}' registrado: {'sim' if registered else 'nao'}")

    return {
        "ok": bool(plan),
        "portal": portal_name,
        "steps": step,
        "outdir": str(outdir),
        "plan": plan,
        "plan_path": str(plan_path) if plan_path.exists() else "",
    }


def main():
    parser = argparse.ArgumentParser(description="Aprendizado de um portal novo")
    parser.add_argument("--url", default=os.environ.get("NP_URL", ""))
    parser.add_argument("--cpf", default=os.environ.get("NP_CPF", ""))
    parser.add_argument("--senha", default=os.environ.get("NP_SENHA", ""))
    parser.add_argument("--portal", default="")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--max-minutes", type=int, default=30)
    args = parser.parse_args()

    if not args.url:
        print("Uso: python aprender_novo_portal.py --url https://portal.exemplo.br --cpf 000 --senha xxx")
        sys.exit(1)

    os.environ.setdefault("AI_LEARN_MODE", "1")
    resultado = executar_aprendizado(
        url=args.url,
        cpf=args.cpf,
        senha=args.senha,
        portal_name=args.portal,
        outdir=args.outdir,
        max_minutes=args.max_minutes,
        logger=print,
    )
    print(f"- ok: {resultado['ok']}")
    print(f"- portal: {resultado['portal']}")
    print(f"- passos gravados: {resultado['steps']}")
    print(f"- plano: {resultado.get('plan_path', '')}")


if __name__ == "__main__":
    main()
