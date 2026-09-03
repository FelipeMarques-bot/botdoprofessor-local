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
from typing import Any, Callable, Dict, List, Optional, Tuple

from leitor_planilhas import carregar_notas

from bot.core.portal_adapter import PortalContext
from bot.core.professor_online_adapter import ProfessorOnlineAdapter

LogFn = Callable[[str], None]

DEFAULT_LOGIN_URL = "https://professoronline.sed.sc.gov.br/CadLoginProfCaptchaCopy1.aspx"


def _headless() -> bool:
    """Modo headless e lido em tempo de execucao (painel define HEADLESS)."""
    return os.environ.get("HEADLESS", "1") == "1"


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


def _make_logger(logger: Optional[LogFn]) -> Callable[[str], None]:
    """Cria um callable de 1 argumento que repassa ao logger do fluxo."""
    def _fn(msg: str) -> None:
        _log(logger, msg)
    return _fn


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
        adapter.start(headless=_headless())
        if not adapter.login(cpf=cpf, senha=senha, log=_make_logger(logger)):
            _raise_login_error(adapter)

        for idx, (key, itens) in enumerate(grouped.items(), start=1):
            escola, turno, turma, trimestre, atividade = key
            _log(logger, f"[{idx}/{total_blocos}] {escola} | {turno} | {turma} | {trimestre} | {atividade}")

            contexto = PortalContext(escola=escola, turno=turno, turma=turma, trimestre=trimestre)
            if not adapter.navigate_to(contexto):
                disp = ", ".join(
                    sorted({f"{t.get('escola','')} | {t.get('serie','')}" for t in adapter.turmas})
                )
                _log(logger, f"  [AVISO] Turma '{turma}' nao encontrada no portal. "
                             f"Disponiveis no grid: {disp or '(nenhuma turma)'}")
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


# --------------------------------------------------------------------- #
#  Chamada diaria (Professor Online)                                     #
# --------------------------------------------------------------------- #

_CHAMADA_VALORES_NAO_PREENCHIDOS = {"", ".", "-"}


def _resolver_credenciais(cpf: str, senha: str, base_url: str, logger: Optional[LogFn]) -> Tuple[str, str, str]:
    """Resolve PO_CPF/PO_SENHA/PO_BASE_URL (variaveis ou parametros)."""
    cpf = cpf or _resolve_env_credential(os.environ.get("PO_CPF", ""), "PO_CPF", logger=logger, digits_only=True)
    senha = senha or _resolve_env_credential(os.environ.get("PO_SENHA", ""), "PO_SENHA", logger=logger, digits_only=False)
    base_url = base_url or os.environ.get("PO_BASE_URL", "")
    if not cpf or not senha:
        raise LancamentoError("Defina PO_CPF e PO_SENHA (ou configure no painel).")
    return cpf, senha, base_url


def _raise_login_error(adapter: "ProfessorOnlineAdapter") -> None:
    """Levanta LancamentoError informando o motivo real da falha no login."""
    erros = adapter.memory.get_known_errors("login")
    motivo = erros[-1].get("error", "") if erros else ""
    if "captcha" in motivo.lower():
        raise LancamentoError(
            "Captcha detectado no login do Professor Online. "
            "Execute com o navegador visivel e complete o captcha manualmente, ou aguarde e tente novamente."
        )
    if motivo and motivo != "nao_logado":
        raise LancamentoError(f"Falha no login do Professor Online. Motivo: {motivo}")
    raise LancamentoError(
        "Falha no login do Professor Online. Verifique o CPF (11 digitos, apenas numeros) e a senha. "
        "Atencao: a senha salva na config pode ser placeholder ('123456') - informe a senha REAL na barra lateral."
    )


def _carregar_foto_chamada(foto_path: str, logger: Optional[LogFn] = None) -> List[Dict[str, str]]:
    """Le a chamada da foto do diario usando a IA configurada."""
    if not foto_path or not os.path.exists(foto_path):
        raise LancamentoError(f"Foto do diario nao encontrada: {foto_path}")
    with open(foto_path, "rb") as f:
        image_bytes = f.read()
    _log(logger, f"[Chamada-PO] Lendo chamada da foto ({len(image_bytes)} bytes)...")
    from ai_assist import extrair_chamada_imagem
    alunos = extrair_chamada_imagem(image_bytes, logger=logger)
    _log(logger, f"[Chamada-PO] Foto lida: {len(alunos)} aluno(s).")
    return alunos


def _norm_nome(nome: str) -> str:
    tokens = "".join(ch for ch in (nome or "").lower() if ch.isalnum() or ch.isspace()).split()
    return " ".join(tokens)


def _score_aluno(nome_grade: str, nome_foto: str) -> float:
    a = set(_norm_nome(nome_grade).split())
    b = set(_norm_nome(nome_foto).split())
    if not a or not b:
        return 0.0
    if _norm_nome(nome_grade) == _norm_nome(nome_foto):
        return 1.0
    inter = a & b
    return len(inter) / max(len(a), len(b))


def _montar_plano_po(grade: List[Dict[str, str]], chamada_foto: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Compara a foto com o estado atual da chamada PO e monta o plano.

    Regras:
      - Aluno cuja presenca (vD1) ja esta preenchida -> pular (nao repreenche).
      - Aluno da foto presente -> 'presenca' (preenche 'C').
      - Aluno da foto com falta -> 'falta' (preenche '1F'/'2F').
      - Falta justificada -> 'falta' com motivo justificada ('1J'/'2J').
      - Nome da foto sem match -> nao_encontrados.
    """
    plano: List[Dict[str, Any]] = []
    nao_encontrados: List[str] = []
    por_foto = list(chamada_foto or [])
    usados_foto: set = set()

    for aluno in grade:
        nome_grade = str(aluno.get("nome", "") or "")
        ja_lancado = (aluno.get("presenca") or "").strip() not in _CHAMADA_VALORES_NAO_PREENCHIDOS
        base = {
            "aluno": nome_grade,
            "matricula": str(aluno.get("matricula", "") or ""),
            "ja_lancado": ja_lancado,
        }
        if ja_lancado:
            base.update({"acao": "pular", "motivo": "", "faltas": 0})
            plano.append(base)
            continue

        melhor_idx = -1
        melhor_score = 0.0
        for j, f in enumerate(por_foto):
            if j in usados_foto:
                continue
            score = _score_aluno(nome_grade, f.get("aluno", ""))
            if score > melhor_score:
                melhor_score = score
                melhor_idx = j
        if melhor_idx < 0 or melhor_score < 0.5:
            base.update({"acao": "pular", "motivo": "", "faltas": 0})
            plano.append(base)
            continue

        usados_foto.add(melhor_idx)
        situacao = str(por_foto[melhor_idx].get("situacao") or "presente").strip().lower()
        if situacao in ("falta", "ausente", "faltou", "falta_justificada", "justificada"):
            faltas = int(str(por_foto[melhor_idx].get("faltas") or "1").strip() or 1)
            justificada = situacao in ("falta_justificada", "justificada")
            base.update({
                "acao": "falta",
                "motivo": "justificada" if justificada else "injustificada",
                "faltas": faltas,
            })
        else:
            base.update({"acao": "presenca", "motivo": "", "faltas": 0})
        plano.append(base)

    for j, f in enumerate(por_foto):
        if j not in usados_foto:
            nao_encontrados.append(str(f.get("aluno") or "").strip())
    return plano, nao_encontrados


def _resumo_plano_po(plano: List[Dict[str, Any]]) -> Dict[str, int]:
    resumo = {"ja_lancados": 0, "presentes": 0, "faltas": 0, "pulados": 0}
    for item in plano:
        if item["acao"] == "pular":
            if item.get("ja_lancado"):
                resumo["ja_lancados"] += 1
            else:
                resumo["pulados"] += 1
        elif item["acao"] == "presenca":
            resumo["presentes"] += 1
        elif item["acao"] == "falta":
            resumo["faltas"] += 1
    return resumo


def _valor_presenca_po(item: Dict[str, Any]) -> str:
    """Converte a acao do plano no valor do campo vD1 do Professor Online."""
    if item.get("acao") == "presenca":
        return "C"
    try:
        n = min(max(int(item.get("faltas") or 1), 1), 2)
    except (TypeError, ValueError):
        n = 1
    return f"{n}J" if item.get("motivo") == "justificada" else f"{n}F"


def _registrar_escolas_po(adapter: ProfessorOnlineAdapter) -> None:
    try:
        from bot.core.escola_registry import registrar_escola
        for escola in adapter.detectar_escolas():
            registrar_escola(escola, "professor_online")
    except Exception:
        pass


def executar_chamada(
    filtro: Optional[Dict[str, str]] = None,
    chamada_foto: Optional[List[Dict[str, str]]] = None,
    foto_path: str = "",
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
    cpf: str = "",
    senha: str = "",
    base_url: str = "",
) -> Dict[str, Any]:
    """Executa o lancamento da chamada do dia no Professor Online.

    filtro chaves aceitas: escola, turno, turma, dia (DD/MM/AAAA).
    A chamada e lancada na data atual do portal por padrao; se 'dia' for
    informado, tenta ajustar a data na tela.
    """
    filtro = filtro or {}
    cpf, senha, base_url = _resolver_credenciais(cpf, senha, base_url, logger=logger)

    if not chamada_foto:
        chamada_foto = _carregar_foto_chamada(foto_path, logger=logger)
    if not chamada_foto:
        raise LancamentoError("Nenhuma chamada foi lida da foto. Verifique a imagem e a IA.")

    if dry_run:
        _log(logger, "Dry-run habilitado: le a grade atual do PO mas NAO envia nada.")

    resultado: Dict[str, Any] = {
        "success": False,
        "mensagem": "",
        "foto_lida": len(chamada_foto),
        "plano": [],
        "resumo": {},
        "nao_encontrados": [],
    }

    adapter = ProfessorOnlineAdapter(base_url=base_url)
    try:
        adapter.start(headless=_headless())
        if not adapter.login(cpf=cpf, senha=senha, log=_make_logger(logger)):
            _raise_login_error(adapter)
        _registrar_escolas_po(adapter)

        contexto = PortalContext(
            escola=filtro.get("escola", ""),
            turno=filtro.get("turno", ""),
            turma=filtro.get("turma", ""),
        )
        if not adapter.navigate_to(contexto):
            disp = ", ".join(
                sorted({f"{t.get('escola','')} | {t.get('serie','')}" for t in adapter.turmas})
            )
            raise LancamentoError(
                f"Turma '{filtro.get('turma', '')}' nao encontrada no Professor Online. "
                f"Disponiveis no grid: {disp or '(nenhuma turma)'}."
            )

        if not adapter.open_chamada():
            raise LancamentoError("Nao foi possivel abrir a chamada do dia no Professor Online.")

        dia = (filtro.get("dia") or "").strip()
        if dia:
            if adapter.set_chamada_dia(dia):
                _log(logger, f"[Chamada-PO] Data da chamada ajustada para {dia}.")
            else:
                _log(logger, f"[Chamada-PO] AVISO: nao foi possivel ajustar a data para {dia}. Usando a data atual do portal.")

        grade = adapter.read_chamada()
        _log(logger, f"[Chamada-PO] Grade atual: {len(grade)} aluno(s).")

        plano, nao_encontrados = _montar_plano_po(grade, chamada_foto)
        resumo = _resumo_plano_po(plano)
        resultado.update({
            "plano": plano,
            "resumo": resumo,
            "nao_encontrados": nao_encontrados,
        })

        if dry_run:
            _log(logger, f"[Chamada-PO] Dry-run: plano com {resumo['presentes']} presentes, {resumo['faltas']} falta(s).")
            resultado["mensagem"] = "Dry-run: nada enviado ao Professor Online."
            resultado["success"] = True
            return resultado

        preenchidos = 0
        for item in plano:
            if item["acao"] == "pular":
                continue
            valor = _valor_presenca_po(item)
            if adapter.fill_presenca(item["aluno"], valor):
                preenchidos += 1
            else:
                _log(logger, f"[Chamada-PO] [FALHA] '{item['aluno']}' nao localizado na grade.")

        if preenchidos > 0:
            if adapter.save_chamada():
                _log(logger, f"[Chamada-PO] Chamada confirmada: {preenchidos} registro(s).")
                resultado["success"] = True
                resultado["mensagem"] = f"Chamada confirmada com {preenchidos} registro(s)."
            else:
                _log(logger, "[Chamada-PO] [SAVE-FALHA] Nao foi possivel confirmar a chamada.")
                resultado["mensagem"] = "Falha ao confirmar a chamada no portal."
        else:
            resultado["success"] = True
            resultado["mensagem"] = "Nada a lancar (todos os alunos ja lancados ou sem registro na foto)."
            _log(logger, "[Chamada-PO] Nada a lancar.")
    finally:
        adapter.stop()

    return resultado


# --------------------------------------------------------------------- #
#  Faltas do mes (Professor Online - leitura)                            #
# --------------------------------------------------------------------- #

def executar_faltas_mes(
    filtro: Optional[Dict[str, str]] = None,
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
    cpf: str = "",
    senha: str = "",
    base_url: str = "",
) -> Dict[str, Any]:
    """Le as faltas do mes de uma turma no Professor Online (somente leitura).

    filtro chaves aceitas: escola, turno, turma.
    """
    filtro = filtro or {}
    cpf, senha, base_url = _resolver_credenciais(cpf, senha, base_url, logger=logger)

    adapter = ProfessorOnlineAdapter(base_url=base_url)
    try:
        adapter.start(headless=_headless())
        if not adapter.login(cpf=cpf, senha=senha, log=_make_logger(logger)):
            _raise_login_error(adapter)
        _registrar_escolas_po(adapter)

        contexto = PortalContext(
            escola=filtro.get("escola", ""),
            turno=filtro.get("turno", ""),
            turma=filtro.get("turma", ""),
        )
        if not adapter.navigate_to(contexto):
            disp = ", ".join(
                sorted({f"{t.get('escola','')} | {t.get('serie','')}" for t in adapter.turmas})
            )
            raise LancamentoError(
                f"Turma '{filtro.get('turma', '')}' nao encontrada no Professor Online. "
                f"Disponiveis no grid: {disp or '(nenhuma turma)'}."
            )

        if not adapter.open_faltas_mes():
            raise LancamentoError("Nao foi possivel abrir a tela de faltas do mes.")

        data = adapter.read_faltas_mes()
        alunos = data.get("alunos", [])
        total_faltas = 0
        for a in alunos:
            try:
                total_faltas += int(str(a.get("total_faltas") or "0").strip() or 0)
            except (TypeError, ValueError):
                pass

        if dry_run:
            _log(logger, "[FaltasMes-PO] Dry-run: apenas leitura (nenhuma alteracao e feita).")

        _log(logger, f"[FaltasMes-PO] {len(alunos)} aluno(s) | periodo: {data.get('periodo', '')} "
                     f"({data.get('data_inicio', '')} a {data.get('data_fim', '')}) | faltas totais: {total_faltas}")
        return {
            "success": True,
            "mensagem": f"Faltas do mes lidas: {len(alunos)} aluno(s), {total_faltas} falta(s) no total.",
            "faltas": data,
            "resumo": {
                "alunos": len(alunos),
                "total_faltas": total_faltas,
                "periodo": data.get("periodo", ""),
            },
        }
    finally:
        adapter.stop()


# --------------------------------------------------------------------- #
#  Sequencia didatica / planejamento (Professor Online)                  #
# --------------------------------------------------------------------- #

def executar_planejamento(
    filtro: Optional[Dict[str, str]] = None,
    registros: Optional[List[Dict[str, Any]]] = None,
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
    cpf: str = "",
    senha: str = "",
    base_url: str = "",
) -> Dict[str, Any]:
    """Publica sequencias didaticas (planejamentos) no Professor Online.

    O Professor Online so possui leitura de planejamentos implementada
    (``navigate_to_lesson_plan``/``read_planejamentos``). A criacao de nova
    versao e upload do PDF ainda nao foram gravados como passo a passo: quando
    necessario, o resultado retorna ``nao_implementado`` e o painel orienta o
    uso do Modo Aprendizado para gravar o fluxo e incluir a funcionalidade.

    registros: lista de dicts com chaves escola, turno, turma, trimestre,
    titulo_documento, arquivo_nome, arquivo_url, periodo_inicio, periodo_fim,
    n_aulas.
    """
    filtro = filtro or {}
    cpf, senha, base_url = _resolver_credenciais(cpf, senha, base_url, logger=logger)
    registros = list(registros or [])

    if not registros:
        raise LancamentoError("Nenhuma sequencia para publicar no Professor Online.")

    contextos: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for reg in registros:
        chave = (
            str(reg.get("escola") or filtro.get("escola") or ""),
            str(reg.get("turno") or filtro.get("turno") or ""),
            str(reg.get("turma") or filtro.get("turma") or ""),
        )
        contextos.setdefault(chave, []).append(reg)

    if dry_run:
        _log(logger, "Dry-run habilitado: nenhum dado sera enviado ao portal.")
        return {
            "success": True,
            "mensagem": f"Dry-run: {len(contextos)} contexto(s), {len(registros)} sequencia(s).",
            "contextos": len(contextos),
            "planejamentos_criados": 0,
            "anexos": 0,
            "situacoes": 0,
            "falhas": 0,
            "nao_implementado": 0,
        }

    adapter = ProfessorOnlineAdapter(base_url=base_url)
    criados = 0
    anexos = 0
    situacoes = 0
    falhas = 0
    nao_implementado = 0

    try:
        adapter.start(headless=_headless())
        if not adapter.login(cpf=cpf, senha=senha, log=_make_logger(logger)):
            _raise_login_error(adapter)
        _registrar_escolas_po(adapter)

        for idx, (chave, itens) in enumerate(contextos.items(), start=1):
            escola, turno, turma = chave
            _log(logger, f"[{idx}/{len(contextos)}] {escola} | {turno} | {turma}")

            if not adapter.navigate_to(PortalContext(escola=escola, turno=turno, turma=turma)):
                disp = ", ".join(
                    sorted({f"{t.get('escola','')} | {t.get('serie','')}" for t in adapter.turmas})
                )
                _log(logger, f"  [AVISO] Turma '{turma}' nao encontrada no portal. "
                             f"Disponiveis no grid: {disp or '(nenhuma turma)'}")
                falhas += len(itens)
                continue

            if not adapter.navigate_to_lesson_plan(PortalContext(escola=escola, turma=turma)):
                _log(logger, "  [AVISO] Nao foi possivel abrir os planejamentos da turma.")
                falhas += len(itens)
                continue

            existentes = adapter.read_planejamentos()
            _log(logger, f"  Planejamentos encontrados na turma: {len(existentes)}")

            for reg in itens:
                titulo = str(reg.get("titulo_documento") or "").strip()
                periodo_inicio = str(reg.get("periodo_inicio") or "").strip()
                ja_existe = False
                for e in existentes:
                    if periodo_inicio and periodo_inicio in (e.get("data_inicio") or ""):
                        ja_existe = True
                        break
                if ja_existe:
                    _log(logger, f"  [JA-EXISTE] '{titulo}' (inicio {periodo_inicio}). Nada a fazer.")
                    continue

                _log(logger, f"  [NAO-IMPLEMENTADO] Criacao/upload de planejamento '{titulo}' no Professor Online "
                             "ainda nao foi gravada. Use o Modo Aprendizado para registrar o fluxo.")
                nao_implementado += 1

        _log(logger, f"Resumo: {criados} criados, {anexos} anexos, {situacoes} situacoes, "
                     f"{falhas} falhas, {nao_implementado} pendente(s) de aprendizado")
    finally:
        adapter.stop()

    return {
        "success": nao_implementado == 0 and falhas == 0,
        "mensagem": (
            f"{criados} planejamento(s) criado(s). "
            + (f"{nao_implementado} pendente(s) de Modo Aprendizado." if nao_implementado else "")
        ),
        "contextos": len(contextos),
        "planejamentos_criados": criados,
        "anexos": anexos,
        "situacoes": situacoes,
        "falhas": falhas,
        "nao_implementado": nao_implementado,
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
