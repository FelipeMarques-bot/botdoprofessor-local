"""Lancamento de notas no Portal Professor Online (SED/SC).

Orquestra: leitura dos registros (planilha/CSV) -> login -> selecao da turma
-> abertura da atividade -> preenchimento das notas -> confirmacao.

Reutiliza o parser deterministico (professor_online_parser) e o adapter
(ProfessorOnlineAdapter). Estrutura de resultado identica ao
``executar_lancamento`` do lancar_notas_sge.py para compatibilidade com o
painel: {blocos, notas, notas_preenchidas, ausentes, falhas}.
"""

import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from leitor_planilhas import carregar_notas

from bot.core.portal_adapter import PortalContext
from bot.core.professor_online_adapter import ProfessorOnlineAdapter

LogFn = Callable[[str], None]

DEFAULT_LOGIN_URL = "https://professoronline.sed.sc.gov.br/CadLoginProfCaptchaCopy1.aspx"

HEADLESS = os.environ.get("HEADLESS", "1") == "1"


@dataclass
class RegistroNota:
    escola: str
    turno: str
    turma: str
    trimestre: str
    aluno: str
    atividade: str
    nota: float
    data_realizacao: str = ""


class LancamentoError(RuntimeError):
    pass


def _log(logger: Optional[LogFn], msg: str) -> None:
    if logger:
        logger(msg)


def _resolve_env_credential(value: str, name: str, logger: Optional[LogFn], digits_only: bool = False) -> str:
    v = (value or "").strip()
    if not v:
        _log(logger, f"Aviso: variavel de ambiente {name} vazia.")
        return ""
    if digits_only:
        v = "".join(ch for ch in v if ch.isdigit())
    return v


def _group_for_launch(registros: List[RegistroNota]):
    grouped: Dict[Tuple[str, str, str, str, str], List[RegistroNota]] = defaultdict(list)
    for reg in registros:
        key = (reg.escola, reg.turno, reg.turma, reg.trimestre, reg.atividade)
        grouped[key].append(reg)
    return grouped


def executar_lancamento(
    fonte: str = "excel",
    fonte_path: str = "",
    filtro: Optional[Dict[str, str]] = None,
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
    cpf: str = "",
    senha: str = "",
    base_url: str = "",
    registros: Optional[List[RegistroNota]] = None,
) -> Dict[str, int]:
    """Lanca as notas de uma planilha/CSV no Portal Professor Online.

    Args:
        fonte: 'excel' ou 'csv'.
        fonte_path: caminho do arquivo.
        filtro: filtro opcional por escola/turno/turma/trimestre/atividade.
        dry_run: True apenas valida e mostra o que seria lancado.
        cpf/senha: credenciais do portal (fallback: variaveis PO_CPF/PO_SENHA).
        base_url: URL base do portal (fallback: variavel PO_BASE_URL).
        registros: lista pronta de RegistroNota (dispensa leitura de arquivo).
    """
    cpf = cpf or _resolve_env_credential(os.environ.get("PO_CPF", ""), "PO_CPF", logger=logger, digits_only=True)
    senha = senha or _resolve_env_credential(os.environ.get("PO_SENHA", ""), "PO_SENHA", logger=logger, digits_only=False)
    base_url = base_url or os.environ.get("PO_BASE_URL", "")

    if not cpf or not senha:
        raise LancamentoError("Defina PO_CPF e PO_SENHA nas variaveis de ambiente (ou passe cpf/senha).")

    if registros is None:
        registros = carregar_notas(fonte, fonte_path, logger=logger)
    if filtro:
        registros = _filtrar_registros(registros, filtro, logger=logger)

    if not registros:
        raise LancamentoError("Nenhuma nota encontrada para o filtro selecionado.")

    grouped = _group_for_launch(registros)
    total_blocos = len(grouped)
    total_notas = len(registros)
    _log(logger, f"Blocos para lancamento: {total_blocos} | notas: {total_notas}")

    if dry_run:
        _log(logger, "Dry-run habilitado: nenhum dado sera enviado ao portal.")
        return {
            "blocos": total_blocos,
            "notas": total_notas,
            "notas_preenchidas": 0,
            "ausentes": 0,
            "falhas": 0,
        }

    adapter = ProfessorOnlineAdapter(base_url=base_url)
    notas_ok = 0
    falhas = 0
    ausentes = 0

    try:
        adapter.start(headless=HEADLESS)
        if not adapter.login(cpf=cpf, senha=senha):
            erros = adapter.memory.get_known_errors("login")
            motivo = erros[-1].get("error", "") if erros else ""
            if "captcha" in motivo.lower():
                raise LancamentoError("Captcha detectado no login. Complete manualmente e tente novamente.")
            raise LancamentoError("Falha no login do Portal Professor Online.")

        for idx, (key, itens) in enumerate(grouped.items(), start=1):
            escola, turno, turma, trimestre, atividade = key
            _log(logger, f"[{idx}/{total_blocos}] {escola} | {turno} | {turma} | {trimestre} | {atividade}")

            contexto = PortalContext(escola=escola, turno=turno, turma=turma, trimestre=trimestre)
            if not adapter.navigate_to(contexto):
                _log(logger, f"  [AVISO] Turma '{turma}' nao encontrada no portal. Pulando bloco.")
                falhas += len(itens)
                continue

            encontrada = adapter.find_assessment(atividade)
            if not encontrada:
                _log(logger, f"  [AVISO] Atividade '{atividade}' nao encontrada. Pulando bloco.")
                falhas += len(itens)
                continue

            novos = 0
            for reg in itens:
                nota_texto = str(reg.nota).replace(".", ",")
                if adapter.fill_grade(reg.aluno, nota_texto):
                    notas_ok += 1
                    novos += 1
                else:
                    _log(logger, f"  [AUSENTE] Aluno '{reg.aluno}' nao localizado na grade. Pulando...")
                    ausentes += 1

            if novos > 0:
                if adapter.save():
                    _log(logger, f"  [SAVE-OK] {novos} nota(s) confirmada(s).")
                else:
                    _log(logger, f"  [SAVE-FALHA] Nao foi possivel confirmar {novos} nota(s).")

        _log(logger, f"Resumo: {notas_ok} preenchidas, {ausentes} ausentes, {falhas} falhas")
    finally:
        adapter.stop()

    return {
        "blocos": total_blocos,
        "notas": total_notas,
        "notas_preenchidas": notas_ok,
        "ausentes": ausentes,
        "falhas": falhas,
    }


def _filtrar_registros(registros: List[RegistroNota], filtro: Dict[str, str], logger: Optional[LogFn]) -> List[RegistroNota]:
    def is_empty(v: Optional[str]) -> bool:
        return not (v and v.strip())

    def matches(reg: RegistroNota, campo: str, alvo: str) -> bool:
        if is_empty(alvo):
            return True
        return alvo.strip().lower() in (getattr(reg, campo, "") or "").lower()

    filtrados = []
    for reg in registros:
        if not matches(reg, "escola", filtro.get("escola", "")):
            continue
        if not matches(reg, "turno", filtro.get("turno", "")):
            continue
        if not matches(reg, "turma", filtro.get("turma", "")):
            continue
        if not matches(reg, "trimestre", filtro.get("trimestre", "")):
            continue
        if not matches(reg, "atividade", filtro.get("atividade", "")):
            continue
        filtrados.append(reg)
    _log(logger, f"Registros apos filtro: {len(filtrados)}")
    return filtrados


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Lancamento de notas no Portal Professor Online")
    parser.add_argument("--fonte", default="excel", choices=["excel", "csv"])
    parser.add_argument("--arquivo", default="")
    parser.add_argument("--cpf", default=os.environ.get("PO_CPF", ""))
    parser.add_argument("--senha", default=os.environ.get("PO_SENHA", ""))
    parser.add_argument("--escola", default="")
    parser.add_argument("--turma", default="")
    parser.add_argument("--atividade", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    filtro = {}
    if args.escola:
        filtro["escola"] = args.escola
    if args.turma:
        filtro["turma"] = args.turma
    if args.atividade:
        filtro["atividade"] = args.atividade

    resultado = executar_lancamento(
        fonte=args.fonte,
        fonte_path=args.arquivo,
        filtro=filtro,
        logger=print,
        dry_run=args.dry_run,
        cpf=args.cpf,
        senha=args.senha,
    )
    print(f"- blocos: {resultado['blocos']}")
    print(f"- notas: {resultado['notas']}")
    print(f"- notas_preenchidas: {resultado['notas_preenchidas']}")
    print(f"- ausentes: {resultado['ausentes']}")
    print(f"- falhas: {resultado['falhas']}")


if __name__ == "__main__":
    main()
