"""IA Primeiro — interpreta o pedido do professor em linguagem natural.

Antes do bot agir, a IA local le o pedido do usuario (ex.: "lanca a chamada de
hoje do 7o ano da tarde"), consulta o documento de orientacoes
(docs/IA_ORIENTACOES.md) e devolve um plano de acao preciso em JSON:
tipo de lancamento, origem, filtros, detalhes e os procedimentos que o bot
deve executar.

Uso pelo painel:
    from interpretar_pedido import interpretar_pedido
    plano = interpretar_pedido("Lanca a chamada de hoje do 7o ano da tarde",
                               logger=log_progress)
    # plano = {"tipo": "chamada", "fonte": "imagem", "turma": "7o ano", ...}
"""

import datetime as _datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    from ai_assist import (
        AIAssistError,
        _call_ai,
        _call_ollama,
        _refresh_ai_env,
        _safe_json_parse,
    )
except Exception:  # pragma: no cover - ambiente sem ai_assist
    AIAssistError = RuntimeError
    _call_ai = None
    _call_ollama = None
    _refresh_ai_env = None
    _safe_json_parse = None

LogFn = Callable[[str], None]

TIPOS = ("notas", "chamada", "sequencia")
FONTES = ("notion", "imagem", "excel", "csv", "google_sheets", "google_drive")
TURNOS = ("", "Matutino", "Vespertino", "Noturno")
TRIMESTRES = ("", "1o Trimestre", "2o Trimestre", "3o Trimestre")

_TEXTO_ORIENTACOES_FALLBACK = """\
Voce e a IA Primeiro do Bot do Professor. O usuario escreve em linguagem comum o
que quer fazer e voce prepara o plano de acao para o bot, respondendo APENAS com
um JSON valido (sem texto antes ou depois).

Procedimentos na ordem:
1. Tipo de lancamento: notas | chamada | sequencia.
   - notas: notas, avaliacoes, provas, trabalhos.
   - chamada: chamada, frequencia, faltas, presenca, diario de classe.
   - sequencia: sequencia didatica, plano de aula, conteudo.
2. Origem dos dados (somente para notas): notion | imagem | excel | csv |
   google_sheets | google_drive. Chamada usa sempre "imagem" (foto do diario).
3. Filtros: escola, turma (ex.: "6o Ano A"), turno (Matutino | Vespertino |
   Noturno ou "") e trimestre (1o Trimestre | 2o Trimestre | 3o Trimestre ou "").
   Normalize: manha=Matutino, tarde=Vespertino, noite=Noturno, T1=1o Trimestre.
4. Detalhes: atividade (nome da avaliacao), data_realizacao (DD/MM/AAAA),
   chamada_dia (DD/MM/AAAA, "hoje" = data de hoje), chamada_disciplina, lote
   (true se o pedido pedir TODAS as escolas/turmas/trimestres).
5. Procedimentos: lista curta de passos que o bot vai executar, na ordem.
6. Duvidas: lista de informacoes necessarias que nao estavam no pedido.

Regras: NUNCA invente escola, turma, turno, trimestre, atividade ou data. Datas
sempre em DD/MM/AAAA. Turno e trimestre apenas nos valores exatos acima. Se faltar
informacao necessaria, coloque em duvidas. Resumo: frase curta do entendimento.
Confianca: alta | media | baixa.

Formato (APENAS o JSON):
{"tipo":"notas","fonte":"notion","escola":"","turma":"","turno":"","trimestre":"",
 "atividade":"","data_realizacao":"","chamada_dia":"","chamada_disciplina":"",
 "lote":false,"resumo":"...","procedimentos":["..."],"duvidas":["..."],"confianca":"alta"}
"""


def _log(logger: Optional[LogFn], msg: str) -> None:
    if logger:
        try:
            logger(msg)
        except Exception:
            pass


def _caminho_orientacoes() -> Optional[Path]:
    """Localiza o documento de orientacoes (repo, app_dir ou bundle)."""
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(getattr(sys, "_MEIPASS", "")) / "docs" / "IA_ORIENTACOES.md")
    candidatos.append(Path(__file__).resolve().parent / "docs" / "IA_ORIENTACOES.md")
    for caminho in candidatos:
        try:
            if caminho and caminho.exists():
                return caminho
        except OSError:
            pass
    return None


def carregar_orientacoes() -> str:
    """Retorna o documento de orientacoes da IA (arquivo ou fallback interno)."""
    caminho = _caminho_orientacoes()
    if caminho:
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass
    return _TEXTO_ORIENTACOES_FALLBACK


def _normalizar_data(valor: Any) -> str:
    """Converte data para DD/MM/AAAA; retorna string vazia se nao reconhecer."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    formatos = ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y",
                "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f")
    for fmt in formatos:
        try:
            dt = _datetime.datetime.strptime(texto, fmt)
            return dt.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            continue
    return texto


def _normalizar_bool(valor: Any, padrao: bool = False) -> bool:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return padrao
    if isinstance(valor, (int, float)):
        return bool(valor)
    t = str(valor).strip().lower()
    if not t:
        return padrao
    if t in ("false", "nao", "0", "no", "n", "nenhum", "nada"):
        return False
    positivos = ("sim", "todos", "todas", "tudo", "yes", "true", "lote")
    frases = ("todas as turmas", "todas as escolas", "todos os anos",
              "todas as escolas e turmas")
    if any(frase in t for frase in frases):
        return True
    tokens = re.split(r"[^a-z0-9]+", t)
    return any(tok in positivos for tok in tokens)


_TURNO_SINONIMOS = {
    "Matutino": ("matutino", "manha", "morning"),
    "Vespertino": ("vespertino", "tarde", "vespera", "afternoon"),
    "Noturno": ("noturno", "noite", "night"),
}

_TRIMESTRE_SINONIMOS = {
    "1o Trimestre": ("1o", "1", "primeiro", "primeiro trimestre", "t1", "trimestre 1", "1o trim"),
    "2o Trimestre": ("2o", "2", "segundo", "segundo trimestre", "t2", "trimestre 2", "2o trim"),
    "3o Trimestre": ("3o", "3", "terceiro", "terceiro trimestre", "t3", "trimestre 3", "3o trim"),
}


def _casa_sinonimo(texto: str, aliases) -> bool:
    """True se o texto (sem acento) corresponder a algum dos sinonimos."""
    if not texto:
        return False
    for alias in aliases:
        alias = alias.lower()
        if texto == alias:
            return True
        if len(alias) >= 2 and alias in texto:
            return True
        if len(texto) >= 2 and texto in alias:
            return True
    return False


def _escolher(valor: Any, opcoes: tuple, padrao: str = "",
               sinonimos: Optional[Dict[str, tuple]] = None) -> str:
    if valor is None:
        return padrao
    texto = str(valor).strip()
    if texto in opcoes:
        return texto
    if not texto:
        return padrao
    sem_acento = _sem_acentos(texto)
    if sinonimos:
        for canonical, aliases in sinonimos.items():
            if _casa_sinonimo(sem_acento, aliases):
                return canonical
    for opcao in opcoes:
        if not opcao:
            continue
        sem_acento_opcao = _sem_acentos(opcao)
        if len(sem_acento_opcao) >= 2 and sem_acento_opcao in sem_acento:
            return opcao
        if len(sem_acento) >= 2 and sem_acento in sem_acento_opcao:
            return opcao
    return padrao


def _sem_acentos(texto: str) -> str:
    return (texto.lower()
            .replace("ç", "c").replace("ã", "a").replace("á", "a")
            .replace("â", "a").replace("à", "a").replace("é", "e")
            .replace("ê", "e").replace("í", "i").replace("ó", "o")
            .replace("ô", "o").replace("õ", "o").replace("ú", "u")
            .replace("ü", "u"))


def _normalizar_pedido(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"error": "Resposta da IA nao e um JSON valido."}
    if raw.get("error"):
        return {"error": str(raw["error"])}

    def _str(chave: str) -> str:
        valor = raw.get(chave)
        return str(valor).strip() if valor is not None else ""

    procedimentos = raw.get("procedimentos") or []
    if not isinstance(procedimentos, list):
        procedimentos = []
    procedimentos = [str(p).strip() for p in procedimentos if str(p).strip()]

    duvidas = raw.get("duvidas") or []
    if not isinstance(duvidas, list):
        duvidas = []
    duvidas = [str(d).strip() for d in duvidas if str(d).strip()]

    return {
        "tipo": _escolher(raw.get("tipo"), TIPOS),
        "fonte": _escolher(raw.get("fonte"), FONTES),
        "escola": _str("escola"),
        "turma": _str("turma"),
        "turno": _escolher(raw.get("turno"), TURNOS, sinonimos=_TURNO_SINONIMOS),
        "trimestre": _escolher(raw.get("trimestre"), TRIMESTRES, sinonimos=_TRIMESTRE_SINONIMOS),
        "atividade": _str("atividade"),
        "data_realizacao": _normalizar_data(raw.get("data_realizacao")),
        "chamada_dia": _normalizar_data(raw.get("chamada_dia")),
        "chamada_disciplina": _str("chamada_disciplina"),
        "lote": _normalizar_bool(raw.get("lote")),
        "resumo": _str("resumo") or "Pedido interpretado pela IA.",
        "procedimentos": procedimentos,
        "duvidas": duvidas,
        "confianca": _escolher(raw.get("confianca"), ("alta", "media", "baixa"), "media"),
    }


def _montar_prompt(pedido: str) -> str:
    orientacoes = carregar_orientacoes()
    return (
        f"{orientacoes}\n\n"
        f"PEDIDO DO PROFESSOR:\n{pedido}\n\n"
        f"Responda APENAS com o JSON, sem texto antes ou depois."
    )


def _chamar_ia_local(prompt: str, logger: Optional[LogFn] = None) -> str:
    """Tenta a IA local (Ollama) primeiro; em seguida, o provedor configurado."""
    if _refresh_ai_env is not None:
        try:
            _refresh_ai_env()
        except Exception:
            pass
    if _call_ollama is not None:
        try:
            _log(logger, "[IA-Primeiro] Usando IA local (Ollama)...")
            return _call_ollama(prompt, logger=logger)
        except AIAssistError as exc:
            _log(logger, f"[IA-Primeiro] IA local indisponivel ({exc}); tentando provedor configurado.")
    if _call_ai is not None:
        return _call_ai(prompt)
    raise AIAssistError("Nenhuma IA disponivel para interpretar o pedido.")


def interpretar_pedido(
    pedido: str,
    logger: Optional[LogFn] = None,
    caller: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Interpreta o pedido do professor e devolve o plano de acao (dict).

    Args:
        pedido: texto em linguagem natural (ex.: "lanca a chamada de hoje do
            7o ano da tarde").
        logger: funcao de log opcional.
        caller: funcao alternativa que recebe o prompt e devolve o texto bruto
            da IA (usado em testes).

    Returns:
        Dict normalizado com: tipo, fonte, escola, turma, turno, trimestre,
        atividade, data_realizacao, chamada_dia, chamada_disciplina, lote,
        resumo, procedimentos, duvidas, confianca.
    """
    texto = (pedido or "").strip()
    if not texto:
        return {"error": "Pedido vazio. Descreva o que o bot deve fazer."}

    prompt = _montar_prompt(texto)
    _log(logger, "[IA-Primeiro] Interpretando o pedido com a IA...")

    if caller is not None:
        resposta = caller(prompt)
    else:
        resposta = _chamar_ia_local(prompt, logger=logger)

    _log(logger, "[IA-Primeiro] IA respondeu. Organizando o plano de acao.")
    if _safe_json_parse is not None:
        raw = _safe_json_parse(resposta, fallback={"error": "Resposta invalida da IA."})
    else:  # pragma: no cover
        try:
            raw = json.loads(resposta)
        except (ValueError, TypeError):
            raw = {"error": "Resposta invalida da IA."}
    return _normalizar_pedido(raw)
