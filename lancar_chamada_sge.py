"""Lancamento de chamada diaria por foto no SGE.

Orquestra: leitura da foto (IA) -> login/navegacao no SGE -> leitura do estado
atual da grade de frequencia -> diff (nao repreenche ja lancados) -> preenchimento
-> salvar.

Uso pelo painel:
    from lancar_chamada_sge import executar_chamada
    resultado = executar_chamada(filtro={"escola": "...", "dia": "2026/08/05"},
                                 foto_path="caminho/da/foto.jpg",
                                 logger=log_progress, dry_run=True)
"""

import os
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import sync_playwright

from bot.core.sge_chamada_adapter import (
    SGEChamadaExecutor,
    ChamadaContexto,
    montar_plano,
    navegar_para_frequencia,
    _resumo_plano,
)
from lancar_notas_sge import (
    HEADLESS,
    ContextoTurma,
    LancamentoError,
    _is_period_selection_page,
    _is_school_selection_page,
    _login_sge,
    _log,
    _normalize_cpf_for_sge,
    _resolve_env_credential,
    _select_period,
    _select_school,
)

LogFn = Callable[[str], None]


def _carregar_foto(foto_path: str, logger: Optional[LogFn] = None) -> List[Dict[str, str]]:
    """Le a chamada da foto do diario usando a IA configurada."""
    if not foto_path or not os.path.exists(foto_path):
        raise LancamentoError(f"Foto do diario nao encontrada: {foto_path}")
    with open(foto_path, "rb") as f:
        image_bytes = f.read()
    _log(logger, f"[Chamada] Lendo chamada da foto ({len(image_bytes)} bytes)...")
    from ai_assist import extrair_chamada_imagem
    alunos = extrair_chamada_imagem(image_bytes, logger=logger)
    _log(logger, f"[Chamada] Foto lida: {len(alunos)} aluno(s).")
    return alunos


def _preview_plano(plano) -> List[Dict[str, Any]]:
    return [
        {
            "aluno": item.aluno.nome,
            "matricula": item.aluno.matricula,
            "acao": item.acao,
            "motivo": item.motivo_nome or item.motivo,
            "faltas": item.faltas if item.acao == "falta" else 0,
            "ja_lancado": item.aluno.ja_lancado,
        }
        for item in plano
    ]


def executar_chamada(
    filtro: Optional[Dict[str, str]] = None,
    chamada_foto: Optional[List[Dict[str, str]]] = None,
    foto_path: str = "",
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Executa o lancamento da chamada do dia.

    filtro chaves aceitas: escola, turno, turma, disciplina, dia (YYYY/MM/DD).
    """
    filtro = filtro or {}
    cpf = _resolve_env_credential(os.environ.get("SGE_CPF", ""), "SGE_CPF", logger=logger, digits_only=True)
    cpf = _normalize_cpf_for_sge(cpf, logger=logger)
    senha = _resolve_env_credential(os.environ.get("SGE_SENHA", ""), "SGE_SENHA", logger=logger, digits_only=False)

    if not cpf or not senha:
        raise LancamentoError("Defina SGE_CPF e SGE_SENHA (ou configure no painel).")

    if not chamada_foto:
        chamada_foto = _carregar_foto(foto_path, logger=logger)
    if not chamada_foto:
        raise LancamentoError("Nenhuma chamada foi lida da foto. Verifique a imagem e a IA.")

    dia = (filtro.get("dia") or "").strip()
    if not dia:
        raise LancamentoError("Informe o dia da chamada no formato AAAA/MM/DD (filtro 'dia').")

    if dry_run:
        _log(logger, "Dry-run habilitado: le a grade atual do SGE mas NAO envia nada.")

    contexto = ChamadaContexto(
        escola=filtro.get("escola", ""),
        turno=filtro.get("turno", ""),
        disciplina=filtro.get("disciplina", ""),
        dia=dia,
    )

    resultado: Dict[str, Any] = {
        "success": False,
        "mensagem": "",
        "foto_lida": len(chamada_foto),
        "plano": [],
        "resumo": {},
        "nao_encontrados": [],
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.set_default_timeout(20000)

        _login_sge(page, cpf=cpf, senha=senha, logger=logger)

        if _is_school_selection_page(page) and contexto.escola:
            _select_school(page, ContextoTurma(escola=contexto.escola, turno="", turma="", trimestre=""), logger=logger)

        if _is_period_selection_page(page):
            _select_period(page, ContextoTurma(escola="", turno="", turma="", trimestre="2o Trimestre"), logger=logger)

        if not navegar_para_frequencia(page, contexto):
            browser.close()
            raise LancamentoError(
                "Nao foi possivel abrir a pagina de Frequencia. "
                "Capture o fluxo turma->Frequencia com gravar_chamada.py e verifique o runbook."
            )

        executor = SGEChamadaExecutor(page=page)
        if not executor.selecionar_dia(dia):
            browser.close()
            raise LancamentoError(f"Dia {dia} nao encontrado no calendario da turma.")

        grade = executor.ler_grade()
        _log(logger, f"[Chamada] Grade atual: {len(grade)} aluno(s).")

        plano = montar_plano(grade, chamada_foto)
        resumo = _resumo_plano(plano)
        nao_encontrados = [f.get("aluno", "") for f in chamada_foto if f.get("aluno")]
        for item in plano:
            if item.acao == "pular" and not item.aluno.ja_lancado:
                nao_encontrados.append(item.aluno.nome)

        resultado["plano"] = _preview_plano(plano)
        resultado["resumo"] = resumo
        resultado["nao_encontrados"] = nao_encontrados
        resultado["mensagem"] = (
            f"{resumo['presentes']} presentes, {resumo['faltas']} falta(s), "
            f"{resumo['ja_lancados']} ja lancado(s)."
        )

        if dry_run:
            _log(logger, f"[Chamada][DRY-RUN] {resultado['mensagem']}")
            resultado["success"] = True
            browser.close()
            return resultado

        _log(logger, f"[Chamada] Aplicando plano: {resultado['mensagem']}")
        res = executor.aplicar_plano(plano)
        if res.faltas or res.presentes:
            salvo = executor.salvar()
            if not salvo:
                browser.close()
                raise LancamentoError("Nao foi possivel clicar em Confirmar para salvar a chamada.")
            _log(logger, f"[Chamada] Salvo com sucesso. {res.mensagem}")
        else:
            _log(logger, "[Chamada] Nada a lancar (todos os alunos ja lancados ou sem registro na foto).")

        browser.close()

    resultado["success"] = True
    resultado["mensagem"] = res.mensagem
    return resultado
