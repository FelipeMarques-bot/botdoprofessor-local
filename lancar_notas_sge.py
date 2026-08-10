import argparse
import difflib
import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from notion_client import Client
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        return False

try:
    from ai_assist import (
        AI_ASSIST,
        AI_LEARN_MODE,
        AI_RECORDING_DIR,
        GEMINI_API_KEY,
        OPENAI_API_KEY,
        ANTHROPIC_API_KEY,
        AI_PROVIDER,
        AIAssistError,
        analyze_login_screen,
        analyze_portal_failure,
        find_element_on_screen,
        verify_grade_on_screen,
        is_available as ai_is_available,
        is_enabled as ai_is_enabled,
        ensure_ollama,
        record_demonstration_step,
        learn_from_recording,
        load_learned_plan,
        execute_learned_step,
        suggest_next_action,
    )
except ImportError:
    AI_ASSIST = False
    AI_LEARN_MODE = False
    AI_RECORDING_DIR = "artifacts/ai-recordings"
    GEMINI_API_KEY = ""
    OPENAI_API_KEY = ""
    ANTHROPIC_API_KEY = ""
    AI_PROVIDER = "local"

    def ai_is_available():
        return False

    def ai_is_enabled():
        return False

    def ensure_ollama(logger=None):
        return False

    def analyze_login_screen(*args, **kwargs):
        return {"elements": [], "has_login_form": False}

    def analyze_portal_failure(*args, **kwargs):
        return {"diagnosis": "IA nao disponivel", "suggested_fixes": [], "needs_rediscovery": False}

    def find_element_on_screen(*args, **kwargs):
        return {"found": False}

    def verify_grade_on_screen(*args, **kwargs):
        return {"found": False, "confirmed": False}

    def record_demonstration_step(*args, **kwargs):
        return None

    def learn_from_recording(*args, **kwargs):
        return None

    def load_learned_plan(*args, **kwargs):
        return None

    def execute_learned_step(*args, **kwargs):
        return False

    def suggest_next_action(*args, **kwargs):
        return {"action": None}


LogFn = Callable[[str], None]

load_dotenv(override=False)

# O SDK do Notion emite WARNING a cada retry de timeout/ObjectNotFound.
# Mantemos o comportamento do script e reduzimos ruido no output do workflow.
_notion_log_level = (os.environ.get("NOTION_CLIENT_LOG_LEVEL", "ERROR") or "ERROR").upper()
logging.getLogger("notion_client").setLevel(getattr(logging, _notion_log_level, logging.ERROR))

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
ROOT_PAGE_ID = os.environ.get("ROOT_PAGE_ID", "")
SGE_CPF = os.environ.get("SGE_CPF", "")
SGE_SENHA = os.environ.get("SGE_SENHA", "")
DEFAULT_SGE_LOGIN_URL = "https://www.sge8147.com.br/hportalprofessor.aspx"

# Forca a deteccao da ia_assist (importada acima) com a env var ja carregada
if not GEMINI_API_KEY:
    globals()["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")
PORTAL_LOGIN_FALLBACK_URLS = [
    "https://www.sge8147.com.br/hportalprofessor.aspx",
    "https://www.sge8147.com.br/hPortalProfessor8147.aspx",
    "https://www.sge8147.com.br/hlogin8147.aspx",
]
SGE_LOGIN_URL = os.environ.get("SGE_LOGIN_URL", DEFAULT_SGE_LOGIN_URL)
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "20000"))
ACTION_TIMEOUT_MS = int(os.environ.get("ACTION_TIMEOUT_MS", "5000"))

# Timeout adaptativo: aumenta progressivamente em caso de falha
_ADAPTIVE_TIMEOUT_MULTIPLIER = 1.0
_ADAPTIVE_TIMEOUT_MAX = 3.0


def _get_adaptive_timeout(base_ms: int) -> int:
    """Retorna timeout adaptativo baseado no historico de falhas."""
    return int(base_ms * min(_ADAPTIVE_TIMEOUT_MULTIPLIER, _ADAPTIVE_TIMEOUT_MAX))


def _increase_adaptive_timeout():
    """Aumenta o multiplicador de timeout adaptativo."""
    global _ADAPTIVE_TIMEOUT_MULTIPLIER
    _ADAPTIVE_TIMEOUT_MULTIPLIER = min(_ADAPTIVE_TIMEOUT_MULTIPLIER + 0.2, _ADAPTIVE_TIMEOUT_MAX)


def _reset_adaptive_timeout():
    """Reseta o multiplicador de timeout adaptativo."""
    global _ADAPTIVE_TIMEOUT_MULTIPLIER
    _ADAPTIVE_TIMEOUT_MULTIPLIER = 1.0

# Mapeamento posicao da atividade na GRIDAGENDA → prefixo da coluna no SGE.
_COLUNA_POR_POSICAO = {1: "N1S", 2: "N2S", 3: "N15S", 4: "PE"}


def _norm_coluna(value: str) -> str:
    """Normaliza um token de coluna para comparacao (ex: 'N1S' == 'n1s'; 'NOTA 1' == 'nota1')."""
    return _normalize_loose(value).replace(" ", "")


def _coluna_token_from_atividade(atividade: str) -> str:
    """Extrai o token de coluna a partir do nome da atividade (ex: 'N1S', 'NOTA 1', 'PE')."""
    a = _normalize(atividade)
    m = re.search(r"(?:^|[^a-z0-9])(n\s*\d+(?:\.\d+)?\s*s|nota\s*\d+|pe)(?:[^a-z0-9]|$)", a)
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(1))


def _collect_coluna_patterns(page) -> List[Tuple[str, int]]:
    """Coleta contagens de padroes de coluna de nota (ex.: 'N1S', 'NOTA1', 'PE') em todos os scopes da pagina.

    Retorna lista de (coluna, contagem) ordenada por frequencia descrescente.
    """
    patterns: List[Tuple[str, int]] = []
    try:
        for scope in _iter_scopes(page):
            try:
                counts = scope.evaluate("""
                    () => {
                        const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
                        const counts = {};
                        for (const el of inputs) {
                            const name = (el.getAttribute('name') || '').trim();
                            const id = (el.getAttribute('id') || '').trim();
                            const attrs = name + ' ' + id;
                            // Procura por padroes de coluna: _N1S_, _NOTA1_, _NOTA_1_, etc
                            const m = attrs.match(/(?:^|[_.])(N\d+S|NOTA\s*\d+|Nota\s*\d+|PE|N\d+(?:\.\d+)?S?)(?:[_\s]|$)/i);
                            if (m) {
                                const p = m[1].toUpperCase();
                                counts[p] = (counts[p] || 0) + 1;
                            }
                        }
                        return counts;
                    }
                """)
                if isinstance(counts, dict):
                    patterns.extend((str(k), int(v)) for k, v in counts.items())
            except Exception:  # noqa: BLE001
                continue
        # Agrega contagens entre scopes e ordena por frequencia.
        counts_tot: Dict[str, int] = {}
        for pat, cnt in patterns:
            counts_tot[pat] = counts_tot.get(pat, 0) + cnt
        patterns = sorted(counts_tot.items(), key=lambda x: x[1], reverse=True)
    except Exception:  # noqa: BLE001
        pass
    return patterns


def _distinct_grade_columns_on_page(page) -> List[str]:
    """Colunas de nota distintas presentes na pagina (ex.: ['N1S', 'N2S']).

    Usada para decidir se uma leitura/escrita SEM filtro de coluna e confiavel:
    pagina com mais de uma coluna distinta pode conter o valor de outra avaliacao.
    """
    return [pat for pat, _cnt in _collect_coluna_patterns(page)]


def _detect_coluna_from_page(page, posicao_grid: int, logger: Optional[LogFn] = None, atividade: str = "") -> str:
    """Detecta o nome real da coluna de nota na pagina do SGE.

    Escaneia os inputs de nota na pagina e retorna o prefixo correto (ex: 'N1S', 'NOTA1', 'PE').
    Prioriza: (1) coluna que bate com o nome da atividade, (2) coluna padrao de _COLUNA_POR_POSICAO
    se presente na pagina, (3) padrao mais comum, (4) coluna padrao.
    """
    coluna_default = _COLUNA_POR_POSICAO.get(posicao_grid, "")

    patterns = _collect_coluna_patterns(page)

    _log(logger, f"[COLUNA-DETECT] Padroes encontrados na pagina: {patterns} (posicao_grid={posicao_grid})")

    chosen = ""
    token = _coluna_token_from_atividade(atividade)
    if token:
        for pat, _count in patterns:
            if _norm_coluna(pat) == token:
                chosen = pat
                break
        if not chosen:
            for pat, _count in patterns:
                if token in _norm_coluna(pat) or _norm_coluna(pat) in token:
                    chosen = pat
                    break

    if not chosen and coluna_default:
        for pat, _count in patterns:
            if _norm_coluna(pat) == _norm_coluna(coluna_default):
                chosen = pat
                break

    if not chosen and patterns:
        distinct = {_norm_coluna(p) for p, _c in patterns}
        if coluna_default or len(distinct) == 1:
            chosen = patterns[0][0]
        else:
            # Posicao fora de _COLUNA_POR_POSICAO e varias colunas na pagina sem
            # token da atividade para desambiguar: nao adivinhar. Retornar '' faz
            # a leitura de 'nota existente' nao confiar em coluna unica (evita
            # [SGE-JA] falso ao ler o valor de outra avaliacao da mesma pagina).
            _log(logger, f"[COLUNA-DETECT] Posicao {posicao_grid} fora do mapa com varias colunas ({sorted(distinct)}); coluna indefinida (atividade={atividade!r}).")
            return ""

    if not chosen and not patterns:
        # Pagina sem inputs com segmento de coluna (ex.: '_NOTA_0001' na pagina
        # 'Notas da Avaliacao'). Retornar '' faz leitura/escrita usarem o caminho
        # sem filtro de coluna, que e o correto para avaliacao unica na pagina.
        # NAO retornar coluna_default aqui: filtrar por '_N1S_' inexistente faria
        # todos os alunos aparecerem como 'nao casou' / ausentes.
        _log(logger, f"[COLUNA-DETECT] Pagina sem segmento de coluna; usando caminho sem filtro de coluna (posicao_grid={posicao_grid}, atividade={atividade!r})")
        return ""

    if chosen:
        _log(logger, f"[COLUNA-DETECT] Coluna detectada: '{chosen}' (posicao_grid={posicao_grid}, atividade={atividade!r})")
    return chosen
MANUAL_LOGIN = os.environ.get("MANUAL_LOGIN", "0") == "1"
MANUAL_LOGIN_TIMEOUT_SEC = int(os.environ.get("MANUAL_LOGIN_TIMEOUT_SEC", "300"))
DEBUG_LOGIN = os.environ.get("SGE_DEBUG_LOGIN", "1" if os.environ.get("GITHUB_ACTIONS") == "true" else "0") == "1"
DEBUG_OUTPUT_DIR = os.environ.get("SGE_DEBUG_DIR", "artifacts/sge-login")
NOTION_STATUS_PROP = os.environ.get("NOTION_STATUS_PROP", "Status lancamento")
NOTION_LAST_RUN_PROP = os.environ.get("NOTION_LAST_RUN_PROP", "Ultima execucao")
NOTION_LAUNCH_DATE_PROP = os.environ.get("NOTION_LAUNCH_DATE_PROP", "Data lancamento")
NOTION_LOG_PROP = os.environ.get("NOTION_LOG_PROP", "Log execucao")
NOTION_REQUEST_PROP = os.environ.get("NOTION_REQUEST_PROP", "Solicitar lancamento")

_DEBUG_CAPTURED_STAGES: set[str] = set()

# Cache simples para chamadas de metadata de databases (evita retrive redundante)
_db_metadata_cache: Dict[str, Dict] = {}

# Cache de slots de alunos por escopo (evita coletas repetidas do DOM)
# Chave: id do elemento scope no DOM; Valor: lista de slots
_slots_cache: Dict[int, List[Dict[str, str]]] = {}

# Evidencia de mudanca de estrutura do SGE (alarme [ESTRUTURA-CHANGED])
ESTRUTURA_DIR = os.environ.get("SGE_ESTRUTURA_DIR", "artifacts/estrutura")
ESTRUTURA_OVERRIDE_PATH = os.path.join(ESTRUTURA_DIR, "estrutura_override.json")

# Evidencias dos itens de revisao pos-lancamento (fila de confirmacao do painel)
REVISAO_DIR = os.environ.get("SGE_REVISAO_DIR", "artifacts/revisao")


def _load_estrutura_override() -> Dict[str, Any]:
    """Le o override local de estrutura salvo pelo usuario via 'Remodelar'.

    Formato: {"slot_selector": "...", "grade_selectors": ["...", ...]}
    Retorna {} se nao houver override. NUNCA cria o arquivo (so leitura).
    """
    try:
        if os.path.exists(ESTRUTURA_OVERRIDE_PATH):
            with open(ESTRUTURA_OVERRIDE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def _salvar_estrutura_override(override: Dict[str, Any]) -> bool:
    """Persiste o override de estrutura apos consentimento do usuario ('Remodelar')."""
    try:
        os.makedirs(ESTRUTURA_DIR, exist_ok=True)
        with open(ESTRUTURA_OVERRIDE_PATH, "w", encoding="utf-8") as f:
            json.dump(override, f, ensure_ascii=False, indent=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def _sanitize_ai_selector(selector: str) -> str:
    """Sanitiza seletores CSS retornados por IA, removendo caracteres invalidos."""
    if not selector:
        return ""
    # Remove { } que a IA as vezes coloca em seletores
    cleaned = selector.replace("{", "").replace("}", "")
    # Remove espacos extras
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Remove aspas simples/duplas no inicio/fim que podem causar problemas
    cleaned = cleaned.strip("'\"")
    return cleaned


class _LearningStore:
    """Armazena seletores que funcionaram para cada tipo de operacao.

    Arquivo: ~/.sge_bot/learning.json
    Estrutura: { "operacoes": { "abrir_icone_avaliacao": { "seletor": "...", "vezes": 5 }, ... } }
    """

    def __init__(self):
        self._path = os.path.join(os.path.expanduser("~"), ".sge_bot", "learning.json")
        self._data: Dict[str, Any] = {"operacoes": {}}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {"operacoes": {}}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def registrar_sucesso(self, operacao: str, detalhes: Dict[str, Any]) -> None:
        """Registra que uma operacao funcionou com determinados detalhes."""
        ops = self._data.setdefault("operacoes", {})
        entry = ops.setdefault(operacao, {"vezes": 0, "ultimo_sucesso": "", "detalhes": {}})
        entry["vezes"] = entry.get("vezes", 0) + 1
        entry["ultimo_sucesso"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["detalhes"].update(detalhes)
        self._save()

    def registrar_falha(self, operacao: str, detalhes: Dict[str, Any]) -> None:
        """Registra que uma operacao falhou (para evitar repetir)."""
        ops = self._data.setdefault("operacoes", {})
        entry = ops.setdefault(operacao, {"vezes": 0, "falhas": 0, "detalhes_falha": {}})
        entry["falhas"] = entry.get("falhas", 0) + 1
        entry["detalhes_falha"].update(detalhes)
        self._save()

    def melhor_seletor(self, operacao: str) -> Optional[str]:
        """Retorna o seletor mais bem-sucedido para uma operacao."""
        entry = self._data.get("operacoes", {}).get(operacao, {})
        return entry.get("detalhes", {}).get("seletor")

    def pode_pular(self, operacao: str) -> bool:
        """Retorna True se uma operacao falhou muitas vezes (evita repetir)."""
        entry = self._data.get("operacoes", {}).get(operacao, {})
        falhas = entry.get("falhas", 0)
        sucessos = entry.get("vezes", 0)
        return falhas > 3 and sucessos == 0


_learning_store = _LearningStore()

TURNOS_KNOWN = ["Matutino", "Vespertino", "Noturno", "Integral"]
TRIMESTRES_KNOWN = [
    "1o Trimestre",
    "2o Trimestre",
    "3o Trimestre",
    "1º Trimestre",
    "2º Trimestre",
    "3º Trimestre",
]

IGNORE_COLS = {
    "Nome",
    "Name",
    "Status",
    "Status Fluxo",
    "Media",
    "Media Final",
    "Observacoes",
    "Observacoes Pedagogicas",
    "Observações",
    "Observações 1",
    "Observações 2",
    "Observações 3",
    "Ultima Atualizacao",
    "Última Atualização",
}


@dataclass
class RegistroNota:
    escola: str
    turno: str
    turma: str
    trimestre: str
    aluno: str
    atividade: str
    nota: float
    notion_page_id: str = ""
    notion_status_prop: str = ""
    data_realizacao: str = ""


@dataclass
class ContextoTurma:
    escola: str
    turno: str
    turma: str
    trimestre: str


class LancamentoError(RuntimeError):
    pass


class EstruturaChangedError(LancamentoError):
    """Estrutura da grade do SGE mudou a ponto de nenhum seletor reconhecer os campos.

    Levantado para ABORTAR a execucao SEM gravar nada; a evidencia (screenshot +
    HTML + sugestao de IA) fica salva em ESTRUTURA_DIR para o usuario revisar.
    """

    def __init__(self, evidencia: Optional[Dict[str, str]] = None):
        super().__init__("Estrutura do SGE mudou (nenhum campo reconhecido).")
        self.evidencia = evidencia or {}


def _log(logger: Optional[LogFn], msg: str) -> None:
    if logger:
        logger(msg)


def _is_non_empty(value: Optional[str]) -> bool:
    return bool(value and value.strip())


def _is_placeholder_env(value: str) -> bool:
    return value.strip().lower() in {
        "your_token_here",
        "your_root_page_id_here",
        "seu_token",
        "id_da_pagina_raiz",
        "seu_cpf",
        "sua_senha",
    }


def _normalize(s: str) -> str:
    text = (s or "").strip().lower()
    # Uniformiza ordinais usados em serie/trimestre: 6º == 6o, 2° == 2o.
    text = text.replace("º", "o").replace("°", "o").replace("ª", "a")
    text = text.replace("\u00a0", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Remove caracteres invisiveis de controle/formato (ex.: zero-width space).
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"Cf", "Cc"})
    return re.sub(r"\s+", " ", text)


def _normalize_loose(s: str) -> str:
    text = _normalize(s)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _name_tokens(s: str) -> List[str]:
    stopwords = {"da", "de", "do", "das", "dos", "e"}
    return [t for t in _normalize_loose(s).split() if t and t not in stopwords]


def _normalize_notion_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    # Aceita UUID com ou sem hifens, ou URL da pagina do Notion.
    match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})",
        raw,
    )
    if not match:
        return raw

    token = match.group(1).replace("-", "").lower()
    if len(token) != 32:
        return raw
    return f"{token[:8]}-{token[8:12]}-{token[12:16]}-{token[16:20]}-{token[20:32]}"


def _resolve_sge_login_url(logger: Optional[LogFn] = None) -> str:
    raw = (SGE_LOGIN_URL or "").strip().strip('"').strip("'")
    if not raw:
        _log(logger, f"Aviso: SGE_LOGIN_URL vazia; usando padrao {DEFAULT_SGE_LOGIN_URL}")
        return DEFAULT_SGE_LOGIN_URL

    # Corrige quando o valor do secret vem no formato de atribuicao, ex.:
    # "SGE_LOGIN_URL=https//www.sge8147.com.br/"
    if "=" in raw and re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", raw):
        raw = raw.split("=", 1)[1].strip().strip('"').strip("'")

    # Corrige esquema sem ':' (https// ou http//).
    raw = re.sub(r"^https//", "https://", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^http//", "http://", raw, flags=re.IGNORECASE)

    # Corrige esquema com apenas uma barra (https:/dominio).
    raw = re.sub(r"^(https?):/([^/])", r"\1://\2", raw, flags=re.IGNORECASE)

    # Remove duplicacao de esquema (ex.: "https://https://...").
    raw = re.sub(r"^(https?://)+", r"\1", raw, flags=re.IGNORECASE)

    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _log(logger, f"Aviso: SGE_LOGIN_URL invalida; usando padrao {DEFAULT_SGE_LOGIN_URL}")
        return DEFAULT_SGE_LOGIN_URL

    # Remove // duplicado no path (ex.: "https://dominio.com//path").
    path = re.sub(r"/{2,}", "/", parsed.path)
    if path != parsed.path:
        raw = parsed._replace(path=path).geturl()
        _log(logger, f"Duplo // corrigido no path da URL de login: {raw}")

    return raw


def _resolve_env_credential(
    value: str,
    env_name: str,
    logger: Optional[LogFn] = None,
    digits_only: bool = False,
) -> str:
    raw = (value or "").strip().strip('"').strip("'")
    if not raw:
        return ""

    # Corrige quando o secret vem no formato de atribuicao literal,
    # por exemplo: "SGE_CPF=997748010".
    if "=" in raw and re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", raw):
        left, right = raw.split("=", 1)
        raw = right.strip().strip('"').strip("'")
        _log(logger, f"Aviso: {env_name} veio como atribuicao literal; usando apenas o valor.")

    if digits_only:
        only_digits = re.sub(r"\D", "", raw)
        if only_digits != raw:
            _log(logger, f"Aviso: {env_name} continha caracteres extras; usando apenas digitos.")
        raw = only_digits

    return raw


def _normalize_cpf_for_sge(cpf: str, logger: Optional[LogFn] = None) -> str:
    digits = re.sub(r"\D", "", cpf or "")
    if not digits:
        return ""

    if len(digits) not in (10, 11):
        raise LancamentoError(
            f"SGE_CPF invalido: {len(digits)} digito(s) informados. "
            "Informe o CPF completo (11 digitos) no painel."
        )

    # Portal costuma esperar 11 digitos, com zeros a esquerda quando necessario.
    if len(digits) < 11:
        padded = digits.zfill(11)
        _log(logger, f"Aviso: SGE_CPF com {len(digits)} digitos; usando formato com zeros a esquerda ({len(padded)} digitos).")
        return padded
    if len(digits) > 11:
        _log(logger, "Aviso: SGE_CPF com mais de 11 digitos; usando os 11 ultimos.")
        return digits[-11:]
    return digits


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: str) -> Optional[datetime]:
    """Tenta extrair uma data de uma string no formato ISO (YYYY-MM-DD) ou DD/MM/YYYY."""
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _date_diff_days(date_str: str) -> Optional[int]:
    """Retorna a diferenca em dias entre a data informada e hoje. Negativo = futuro."""
    dt = _parse_date(date_str)
    if dt is None:
        return None
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (dt.date() - today.date()).days


def _status_prop_for_activity(atividade: str) -> str:
    texto = (atividade or "").strip().lower()
    match = re.search(r"(\d+)\s*$", texto)
    if not match:
        match = re.search(r"^(\d+)", texto)
    if match:
        return f"Status lancamento {match.group(1)}"
    return "Status lancamento"


def _resolve_existing_status_prop(props: Dict[str, Dict], preferred: str) -> str:
    alvo = (preferred or "").strip()
    if not alvo:
        return preferred

    num_match = re.search(r"(\d+)", alvo)
    num_suffix = num_match.group(1) if num_match else ""

    # 1) Match exato primeiro
    if alvo in props:
        return alvo

    # 2) Se tem numero, busca a propriedade com o mesmo numero
    if num_suffix:
        for name in props.keys():
            name_num = re.search(r"(\d+)", name)
            if name_num and name_num.group(1) == num_suffix:
                norm = _normalize(name)
                if "status" in norm and "lancamento" in norm:
                    return name

    # 3) Fallback: qualquer propriedade que contenha "status" e "lancamento"
    best: Optional[str] = None
    for name in props.keys():
        norm = _normalize(name)
        if "status" in norm and "lancamento" in norm:
            if best is None:
                best = name
            # Se preferred tem numero, prefere match com o mesmo numero
            if num_suffix:
                name_num = re.search(r"(\d+)", norm)
                if name_num and name_num.group(1) == num_suffix:
                    return name
    if best is not None:
        return best

    return preferred


def _student_name_matches(expected: str, current: str) -> bool:
    a = _normalize_loose(expected)
    b = _normalize_loose(current)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True

    # Compara nomes compactados para tolerar ruido de espacos/codificacao.
    a_compact = re.sub(r"[^a-z0-9]", "", a)
    b_compact = re.sub(r"[^a-z0-9]", "", b)
    if a_compact and b_compact:
        if a_compact == b_compact:
            return True
        if abs(len(a_compact) - len(b_compact)) <= 2 and difflib.SequenceMatcher(None, a_compact, b_compact).ratio() >= 0.93:
            return True

    ta = _name_tokens(a)
    tb = _name_tokens(b)
    if not ta or not tb:
        return False

    common = set(ta).intersection(tb)
    same_ends = ta[0] == tb[0] and ta[-1] == tb[-1]
    if same_ends and len(common) >= max(2, min(len(ta), len(tb)) - 1):
        return True

    # Tolerancia para variacao ortografica leve no primeiro nome, mantendo
    # sobrenome final igual para evitar casar aluno incorreto.
    same_last = ta[-1] == tb[-1]
    first_ratio = difflib.SequenceMatcher(None, ta[0], tb[0]).ratio()
    if same_last and first_ratio >= 0.72 and len(common) >= max(1, min(len(ta), len(tb)) - 2):
        return True

    # Ultimo sobrenome pode variar (ex.: nome composto adicional no SGE).
    # Nesse caso exigimos maior sobreposicao de tokens significativos.
    if first_ratio >= 0.85 and len(common) >= 2:
        return True

    return False


def _pick_best_student_slot(expected: str, slots: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    alvo = _normalize_loose(expected)
    if not alvo:
        return None

    # 1) Match deterministico primeiro.
    for slot in slots:
        atual = str(slot.get("aluno", ""))
        if _student_name_matches(expected, atual):
            return slot

    # 2) Fallback por similaridade com guardrails para evitar aluno errado.
    alvo_tokens = _name_tokens(alvo)
    if not alvo_tokens:
        return None
    alvo_first = alvo_tokens[0]
    alvo_first_prefix = alvo_first[:3]
    alvo_last = alvo_tokens[-1]

    best: Optional[Dict[str, str]] = None
    best_score = 0.0
    best_first_ratio = 0.0
    best_last_matches = False

    for slot in slots:
        atual_raw = str(slot.get("aluno", ""))
        atual = _normalize_loose(atual_raw)
        if not atual:
            continue
        atual_tokens = _name_tokens(atual)
        if not atual_tokens:
            continue

        # Guardrails para evitar aluno errado em fallback aproximado.
        atual_first = atual_tokens[0]
        atual_last = atual_tokens[-1]
        first_ratio = difflib.SequenceMatcher(None, alvo_first, atual_first).ratio()
        if atual_first != alvo_first and not atual_first.startswith(alvo_first_prefix) and first_ratio < 0.72:
            continue

        overlap = len(set(alvo_tokens).intersection(atual_tokens))
        ratio = difflib.SequenceMatcher(None, alvo, atual).ratio()
        last_bonus = 0.06 if atual_last == alvo_last else 0.0
        score = ratio + (0.03 * overlap) + (0.04 * first_ratio) + last_bonus

        # Guardrail: sem ultimo sobrenome igual, precisa overlap forte.
        if atual_last != alvo_last and overlap < 2:
            continue

        if score > best_score:
            best_score = score
            best = slot
            best_first_ratio = first_ratio
            best_last_matches = atual_last == alvo_last

    if best is None:
        return None

    # Threshold conservador com pequena flexibilidade para nomes curtos.
    if best_score >= 0.90:
        return best

    if len(alvo_tokens) <= 2 and best_last_matches and best_first_ratio >= 0.72 and best_score >= 0.84:
        return best

    if not best_last_matches and best_first_ratio >= 0.85 and best_score >= 0.86:
        return best

    return None


def _find_student_suffix_by_html(scope, aluno: str) -> Optional[str]:
    alvo = _normalize_loose(aluno)
    if not alvo:
        return None

    try:
        html_text = scope.content()
    except Exception:  # noqa: BLE001
        return None

    for match in re.finditer(r'name="_ALUMATNOM_(\d{4})"\s+value="([^"]*)"', html_text, flags=re.IGNORECASE):
        suffix = match.group(1)
        nome_tela = html.unescape(match.group(2) or "").strip()
        if _student_name_matches(aluno, nome_tela):
            return suffix

    return None


def _safe_notion_call(fn):
    retry = 4
    wait = 1.2
    last = None
    for idx in range(1, retry + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "api token is invalid" in msg or "unauthorized" in msg:
                raise LancamentoError(
                    "NOTION_TOKEN invalido no ambiente de execucao. Atualize o secret NOTION_TOKEN no GitHub Actions."
                ) from exc
            last = exc
            if idx == retry:
                break
            time.sleep(wait * idx)
    raise last


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_rich_text(content: str) -> List[Dict]:
    text = (content or "")[:1900]
    if not text:
        return []
    return [{"type": "text", "text": {"content": text}}]


def atualizar_status_execucao_notion(
    page_id: str,
    status: str,
    logger: Optional[LogFn] = None,
    log_text: str = "",
    clear_request: bool = False,
) -> None:
    if not page_id:
        return
    if not NOTION_TOKEN:
        _log(logger, "Aviso: NOTION_TOKEN nao definido; nao foi possivel atualizar status no Notion.")
        return

    notion = Client(auth=NOTION_TOKEN)

    try:
        page = _safe_notion_call(lambda: notion.pages.retrieve(page_id=page_id))
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"Aviso: falha ao ler pagina de execucao no Notion: {exc}")
        return

    props = page.get("properties", {})
    payload: Dict[str, Dict] = {}

    if NOTION_STATUS_PROP in props and props[NOTION_STATUS_PROP].get("type") == "select":
        payload[NOTION_STATUS_PROP] = {"select": {"name": status}}
    else:
        _log(logger, f"Aviso: propriedade de status nao encontrada/compativel: {NOTION_STATUS_PROP}")

    if NOTION_LAST_RUN_PROP in props and props[NOTION_LAST_RUN_PROP].get("type") == "date":
        payload[NOTION_LAST_RUN_PROP] = {"date": {"start": _utc_now_iso()}}
    else:
        _log(logger, f"Aviso: propriedade de data nao encontrada/compativel: {NOTION_LAST_RUN_PROP}")

    if NOTION_LAUNCH_DATE_PROP in props and props[NOTION_LAUNCH_DATE_PROP].get("type") == "date":
        payload[NOTION_LAUNCH_DATE_PROP] = {"date": {"start": _utc_now_iso()}}

    if log_text and NOTION_LOG_PROP in props and props[NOTION_LOG_PROP].get("type") == "rich_text":
        payload[NOTION_LOG_PROP] = {"rich_text": _make_rich_text(log_text)}
    elif log_text:
        _log(logger, f"Aviso: propriedade de log nao encontrada/compativel: {NOTION_LOG_PROP}")

    if clear_request and NOTION_REQUEST_PROP in props and props[NOTION_REQUEST_PROP].get("type") == "checkbox":
        payload[NOTION_REQUEST_PROP] = {"checkbox": False}
    elif clear_request:
        _log(logger, f"Aviso: propriedade de solicitacao nao encontrada/compativel: {NOTION_REQUEST_PROP}")

    if not payload:
        return

    try:
        _safe_notion_call(lambda: notion.pages.update(page_id=page_id, properties=payload))
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"Aviso: falha ao atualizar status no Notion: {exc}")


def _find_pending_request_page_id(escola: str, logger: Optional[LogFn] = None) -> str:
    escola = (escola or "").strip()
    if not escola or not NOTION_TOKEN:
        return ""

    notion = Client(auth=NOTION_TOKEN)
    target_title = f"Solicitacoes SGE - {escola}"

    data_source_ids: List[str] = []
    cursor = None
    while True:
        response = _safe_notion_call(
            lambda: notion.search(
                query=target_title,
                filter={"property": "object", "value": "data_source"},
                start_cursor=cursor,
                page_size=100,
            )
        )

        for ds in response.get("results", []):
            title = "".join(x.get("plain_text", "") for x in ds.get("title", [])).strip()
            if _normalize(title) != _normalize(target_title):
                continue
            ds_id = ds.get("id", "")
            if ds_id:
                data_source_ids.append(ds_id)

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    if not data_source_ids:
        _log(logger, f"Aviso: nenhuma data source de solicitacao encontrada para {escola}.")
        return ""

    for ds_id in data_source_ids:
        cursor = None
        while True:
            query_resp = _safe_notion_call(
                lambda: notion.data_sources.query(
                    data_source_id=ds_id,
                    start_cursor=cursor,
                    page_size=100,
                )
            )

            for page in query_resp.get("results", []):
                props = page.get("properties", {})

                req_prop = props.get(NOTION_REQUEST_PROP, {})
                solicitar = req_prop.get("type") == "checkbox" and bool(req_prop.get("checkbox", False))

                status_prop = props.get(NOTION_STATUS_PROP, {})
                status_name = ""
                if status_prop.get("type") == "select":
                    status_name = ((status_prop.get("select") or {}).get("name") or "").strip()

                escola_prop = _extract_plain_text(props.get("Escola", {})).strip()

                if not solicitar:
                    continue
                if status_name not in {"", "Pendente"}:
                    continue
                if escola_prop and _normalize(escola_prop) != _normalize(escola):
                    continue

                page_id = page.get("id", "")
                if page_id:
                    return page_id

            if not query_resp.get("has_more"):
                break
            cursor = query_resp.get("next_cursor")

    _log(logger, f"Aviso: nenhuma solicitacao pendente encontrada para {escola}.")
    return ""


def _extract_plain_text(prop: Dict) -> str:
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if ptype == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    if ptype == "select":
        node = prop.get("select")
        return "" if not node else node.get("name", "")
    if ptype == "date":
        node = prop.get("date")
        if not node:
            return ""
        return node.get("start", "") or ""
    if ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type")
        return "" if not ftype else str(formula.get(ftype, ""))
    if ptype == "rollup":
        data = prop.get("rollup", {})
        if data.get("type") == "number":
            return "" if data.get("number") is None else str(data.get("number"))
        if data.get("type") == "array":
            arr = data.get("array", [])
            parts = []
            for item in arr:
                item_type = item.get("type")
                if item_type == "title":
                    parts.append("".join(x.get("plain_text", "") for x in item.get("title", [])))
                elif item_type == "rich_text":
                    parts.append("".join(x.get("plain_text", "") for x in item.get("rich_text", [])))
            return " ".join(x for x in parts if x)
    if ptype == "url":
        return prop.get("url", "") or ""
    return ""


def _database_title(database: Dict) -> str:
    titles = database.get("title", [])
    if not titles:
        return ""
    return "".join(x.get("plain_text", "") for x in titles).strip()


def _is_notas_database(title: str) -> bool:
    norm = _normalize(title)
    if norm.startswith("notas escolas -"):
        return True
    if any(kw in norm for kw in ("notas", "escola", "lancamento", "boletim", "avaliacao")):
        return True
    return False


def _page_title(page: Dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _extract_plain_text(prop).strip()
    return ""


def _list_children(notion: Client, block_id: str) -> List[Dict]:
    items = []
    cursor = None
    while True:
        response = _safe_notion_call(
            lambda: notion.blocks.children.list(block_id=block_id, start_cursor=cursor, page_size=100)
        )
        items.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return items


def _search_databases_by_name(
    query: str,
    exclude_ids: set,
    logger: Optional[LogFn] = None,
) -> List[Tuple[str, List[str], str]]:
    results = []
    cursor = None
    MAX_PAGES = 5  # Limita paginas de busca para nao demorar
    pages_searched = 0

    while pages_searched < MAX_PAGES:
        body = {"query": query, "filter": {"property": "object", "value": "database"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        response = _safe_notion_call(
            lambda: httpx.post(
                "https://api.notion.com/v1/search",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=30,
            ).json()
        )
        pages_searched += 1
        for item in response.get("results", []):
            db_id = item.get("id", "")
            if db_id in exclude_ids:
                continue
            title = "".join(x.get("plain_text", "") for x in item.get("title", []))
            results.append((db_id, [], title))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    if results:
        _log(logger, f"  -> {len(results)} database(s) encontrada(s) via busca por nome.")
    return results


_DISCOVERY_CACHE_FILE = os.path.join(os.path.expanduser("~"), ".sge_bot", "notion_discovery_cache.json")
_DISCOVERY_CACHE_MAX_AGE = 86400  # 24 horas em segundos


def _load_discovery_cache() -> Optional[List[Tuple[str, List[str], str]]]:
    """Carrega cache de descoberta do Notion se valido (menos de 24h)."""
    try:
        if not os.path.exists(_DISCOVERY_CACHE_FILE):
            return None
        mtime = os.path.getmtime(_DISCOVERY_CACHE_FILE)
        age = time.time() - mtime
        if age > _DISCOVERY_CACHE_MAX_AGE:
            return None
        with open(_DISCOVERY_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Valida formato
        if isinstance(data, list) and all(isinstance(item, list) and len(item) == 3 for item in data):
            return [tuple(item) for item in data]
    except Exception:
        pass
    return None


def _save_discovery_cache(databases: List[Tuple[str, List[str], str]]) -> None:
    """Salva cache de descoberta do Notion."""
    try:
        os.makedirs(os.path.dirname(_DISCOVERY_CACHE_FILE), exist_ok=True)
        with open(_DISCOVERY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([list(item) for item in databases], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _discover_databases(
    notion: Client,
    root_page_id: str,
    logger: Optional[LogFn] = None,
) -> List[Tuple[str, List[str], str]]:
    # Verificar cache primeiro
    cached = _load_discovery_cache()
    if cached is not None:
        _log(logger, f"[CACHE] Usando cache de descoberta: {len(cached)} databases (valido por 24h)")
        return cached

    queue: List[Tuple[str, List[str], int]] = [(root_page_id, ["ROOT"], 0)]
    visited_pages = set()
    databases: List[Tuple[str, List[str], str]] = []
    discovered_count = 0
    log_interval = 5
    MAX_DEPTH = 4  # Limita profundidade para evitar traversals infinitos

    while queue:
        page_id, breadcrumb, depth = queue.pop(0)
        if page_id in visited_pages:
            continue
        visited_pages.add(page_id)

        # Poda: nao atravessa paginas muito profundas (> 4 niveis)
        if depth > MAX_DEPTH:
            _log(logger, f"  [PRUNE] Pulando pagina no nivel {depth}: {' > '.join(breadcrumb[-2:])}")
            continue

        # Poda: ignora paginas cujo titulo sugere que nao contem databases de notas
        page_title = breadcrumb[-1] if len(breadcrumb) > 1 else ""
        title_lower = _normalize(page_title)
        skip_keywords = {"dashboard", "menu", "instrucoes", "tutorial", "config", "ajuda", "sobre"}
        if any(kw in title_lower for kw in skip_keywords):
            continue

        try:
            children = _list_children(notion, page_id)
        except Exception as exc:  # noqa: BLE001
            _log(
                logger,
                f"Aviso: pagina/bloco inacessivel no Notion durante descoberta ({page_id}): {exc}",
            )
            continue
        for block in children:
            btype = block.get("type")

            if btype == "child_page":
                title = block.get("child_page", {}).get("title", "")
                queue.append((block["id"], breadcrumb + [title], depth + 1))
                continue

            if btype == "link_to_page":
                link_data = block.get("link_to_page", {})
                if link_data.get("type") == "page_id":
                    queue.append((link_data.get("page_id", ""), breadcrumb + ["linked-page"], depth + 1))
                continue

            if btype == "child_database":
                db_title = block.get("child_database", {}).get("title", "")
                databases.append((block["id"], breadcrumb.copy(), db_title))
                discovered_count += 1
                if discovered_count % log_interval == 0:
                    _log(logger, f"  -> {discovered_count} databases encontradas ate agora...")
                continue

    _log(logger, f"Descoberta concluida: {len(databases)} databases encontradas ({len(visited_pages)} paginas visitadas)")
    # Salvar cache para proximas execucoes
    _save_discovery_cache(databases)
    return databases


def _extract_data_source_id(database_obj: Optional[Dict]) -> Optional[str]:
    if not database_obj:
        return None
    data_sources = database_obj.get("data_sources", [])
    if not data_sources:
        return None
    first = data_sources[0]
    if isinstance(first, dict):
        return first.get("id")
    return None


def _query_database_rows(notion: Client, database_id: str, database_obj: Optional[Dict] = None) -> List[Dict]:
    rows = []
    cursor = None

    query_databases = hasattr(notion, "databases") and hasattr(notion.databases, "query")
    query_data_sources = hasattr(notion, "data_sources") and hasattr(notion.data_sources, "query")

    data_source_id = _extract_data_source_id(database_obj)
    if not query_databases and query_data_sources and not data_source_id:
        db_obj = _safe_notion_call(lambda: notion.databases.retrieve(database_id=database_id))
        data_source_id = _extract_data_source_id(db_obj)

    if not query_databases and query_data_sources and not data_source_id:
        raise LancamentoError(
            "Nao foi possivel localizar data_source para consultar as linhas da database no Notion."
        )

    while True:
        if query_databases:
            response = _safe_notion_call(
                lambda: notion.databases.query(database_id=database_id, start_cursor=cursor, page_size=100)
            )
        elif query_data_sources:
            response = _safe_notion_call(
                lambda: notion.data_sources.query(data_source_id=data_source_id, start_cursor=cursor, page_size=100)
            )
        else:
            raise LancamentoError("Versao da biblioteca do Notion sem suporte para query de databases.")

        rows.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return rows


def _infer_context(parts: Iterable[str]) -> ContextoTurma:
    parts_clean = [p for p in (x.strip() for x in parts) if p]
    all_text = " | ".join(parts_clean)

    escola = ""
    turno = ""
    turma = ""
    trimestre = ""

    for p in parts_clean:
        if not turno:
            for t in TURNOS_KNOWN:
                if _normalize(t) in _normalize(p):
                    turno = t
                    break

        if not trimestre:
            for tr in TRIMESTRES_KNOWN:
                if _normalize(tr) in _normalize(p):
                    trimestre = tr
                    break

        if not turma:
            found = re.search(r"([6-9][oº]?\s*Ano(?:\s*\d+)?)", p, flags=re.IGNORECASE)
            if found:
                turma = found.group(1).replace("º", "o")

    if not escola:
        SKIP_PAGES = {"root", "linked-page"}
        SKIP_KEYWORDS = {"dashboard de lancamentos", "portal de gestao de avaliacoes", "acesso rapido"}
        for p in parts_clean:
            norm = _normalize(p)
            if p.lower() in SKIP_PAGES:
                continue
            if any(kw in norm for kw in SKIP_KEYWORDS):
                continue
            if any(_normalize(x) in norm for x in TURNOS_KNOWN + TRIMESTRES_KNOWN):
                continue
            if re.search(r"[6-9][oº]?\s*ano", p, flags=re.IGNORECASE):
                continue
            escola = p
            break

    if not escola or "nao identificad" in _normalize(escola):
        for p in parts_clean:
            partes = re.split(r"\s*[|]\s*", p)
            if len(partes) < 2:
                continue
            candidatas = [x for x in partes if x not in TURNOS_KNOWN + ["Matutino", "Vespertino", "Noturno", "Integral"]]
            for tr in TRIMESTRES_KNOWN:
                candidatas = [x for x in candidatas if _normalize(tr) not in _normalize(x)]
            candidatas = [x for x in candidatas if not re.search(r"[6-9][oº]?\s*ano", x, flags=re.IGNORECASE)]
            candidatas = [x for x in candidatas if not any(kw in _normalize(x) for kw in SKIP_KEYWORDS)]
            if candidatas:
                escola = candidatas[0].strip()
                break

    if not escola or "nao identificad" in _normalize(escola):
        escola = "Escola nao identificada"
    if not turno:
        turno = "Turno nao identificado"
    if not turma:
        turma = "Turma nao identificada"
    if not trimestre:
        trimestre = "Trimestre nao identificado"

    # Limpeza final de espacos para evitar divergencias no filtro
    escola = re.sub(r"\s+", " ", escola).strip()
    turno = re.sub(r"\s+", " ", turno).strip()
    turma = re.sub(r"\s+", " ", turma).strip()
    trimestre = re.sub(r"\s+", " ", trimestre).strip()

    _ = all_text
    return ContextoTurma(escola=escola, turno=turno, turma=turma, trimestre=trimestre)


_IGNORE_COLS_NORM = frozenset(_normalize(c) for c in IGNORE_COLS)


def _build_grade_status_map(props: Dict[str, Dict]) -> Dict[str, str]:
    """Mapeia colunas de nota para 'Status lancamento N' usando estrutura do Notion.

    Estrategia (por prioridade):
    1) Numero explicito no nome da coluna (ex: "Atividade 3" → 3)
    2) Encontra ancora "Data realização N" para cada coluna de nota (proximo no dict)
    3) Fallback: tenta extrair numero de padroes como "24 - Resolução 1" → 1
    4) Fallback: mapeia para a primeira Status lancamento disponivel (por ordem N)
    """
    prop_names = list(props.keys())

    # Pre-calcula quais Status lancamento N existem de fato
    existing_status_n = set()
    for p in prop_names:
        m = re.search(r"status\s*lancamento\s*(\d+)", _normalize(p))
        if m:
            existing_status_n.add(m.group(1))

    grade_status_map: Dict[str, str] = {}

    # 1) Numero explicito no nome da coluna (ex.: "Atividade 3" → "Status lancamento 3").
    #    Tem prioridade sobre a proximidade, que pode errar quando ha varias colunas de
    #    nota juntas (ex.: '24-Resolução de Problemas', 'Atividade 3', '17-Simulado'),
    #    mapeando a avaliacao para o Status lancamento errado (e mentindo no log).
    for idx, name in enumerate(prop_names):
        if not _is_probably_grade_column(name):
            continue
        num_match = re.search(r"(?:atividade|activity|avaliacao|prova|trabalho)\s*(\d+)", _normalize(name))
        if num_match and num_match.group(1) in existing_status_n:
            grade_status_map[name] = f"Status lancamento {num_match.group(1)}"

    # 2) Encontra ancora "Data realização N" → indice no dict
    ancora_por_n: Dict[str, int] = {}
    for idx, name in enumerate(prop_names):
        m = re.search(r"data\s*realiza[çc][ãa]o\s*(\d+)", _normalize(name))
        if m:
            ancora_por_n[m.group(1)] = idx

    # 3) Para cada coluna de nota sem numero no nome, encontra a ancora mais proxima
    #    (em caso de empate, menor N vence — garante mapeamento deterministico)
    for idx, name in enumerate(prop_names):
        if name in grade_status_map:
            continue
        if not _is_probably_grade_column(name):
            continue
        best_n = ""
        best_dist = len(prop_names) + 1
        for n in sorted(ancora_por_n.keys()):
            dist = abs(idx - ancora_por_n[n])
            if dist < best_dist:
                best_dist = dist
                best_n = n
        if best_n and best_n in existing_status_n:
            grade_status_map[name] = f"Status lancamento {best_n}"

    # 4) Fallback para colunas sem ancora: extrai numero do nome (ex: "Atividade 2")
    for idx, name in enumerate(prop_names):
        if name in grade_status_map:
            continue
        if not _is_probably_grade_column(name):
            continue
        num_match = re.search(r"(?:atividade|activity|avaliacao|prova|trabalho)\s*(\d+)", _normalize(name))
        if num_match:
            n = num_match.group(1)
            status_cand = f"Status lancamento {n}"
            if n in existing_status_n:
                grade_status_map[name] = status_cand

    # 4b) Fallback: tenta extrair ultimo digito de "XX - Nome Atividade N"
    for idx, name in enumerate(prop_names):
        if name in grade_status_map:
            continue
        if not _is_probably_grade_column(name):
            continue
        num_match = re.search(r"[-–]\s*\S+\s+(\d+)$", name.strip())
        if num_match:
            n = num_match.group(1)
            status_cand = f"Status lancamento {n}"
            if n in existing_status_n:
                grade_status_map[name] = status_cand

    # 5) Fallback final: colunas ainda sem mapeamento → primeira Status disponivel
    usados = set(grade_status_map.values())
    for idx, name in enumerate(prop_names):
        if name in grade_status_map:
            continue
        if not _is_probably_grade_column(name):
            continue
        for n in sorted(ancora_por_n.keys()):
            cand = f"Status lancamento {n}"
            if cand not in usados and n in existing_status_n:
                grade_status_map[name] = cand
                usados.add(cand)
                break

    return grade_status_map


def _is_probably_grade_column(col_name: str) -> bool:
    clean = col_name.strip()
    if not clean:
        return False
    # Normaliza (remove acentos, lower) para capturar variantes como "Média", "Observações", "Data realização"
    norm = _normalize(clean)
    if norm in _IGNORE_COLS_NORM:
        return False
    blacklist_long = {"status", "media", "coment", "nome", "name", "chamada", "frequencia", "observa", "data", "numero", "criado", "editado", "ultima", "realizacao"}
    blacklist_short = {"id", "obs"}
    for term in blacklist_long:
        if term in norm:
            return False
    for term in blacklist_short:
        if re.search(rf"(?:^|[\s\-_/]){re.escape(term)}(?:[\s\-_/]|$)", norm):
            return False
    return True


def _match_turma(expected: str, value: str) -> bool:
    """Compara ano/turma de forma tolerante.

    A database do Notion eh organizada por ano (ex.: '9o Ano') enquanto o filtro
    pode incluir o numero da turma (ex.: '9o ano1'). A comparacao bate quando o
    ano coincide e, se ambos informarem numero de turma, eles devem ser iguais.
    """
    exp = _normalize(expected)
    val = _normalize(value)
    if not exp:
        return True
    if exp in val:
        return True
    exp_ano = _extract_first_number(exp)
    val_ano = _extract_first_number(val)
    if not exp_ano or exp_ano != val_ano:
        return False
    exp_turma = _extract_turma_number(exp)
    val_turma = _extract_turma_number(val)
    if exp_turma and val_turma and exp_turma != val_turma:
        return False
    return True


def _context_matches_filter(context: ContextoTurma, filtro: Optional[Dict[str, str]]) -> bool:
    if not filtro:
        return True

    def match(value: str, key: str) -> bool:
        expected = (filtro.get(key) or "").strip()
        if not expected:
            return True
        if key == "turma":
            return _match_turma(expected, value)
        return _normalize(expected) in _normalize(value)

    return (
        match(context.escola, "escola")
        and match(context.turno, "turno")
        and match(context.turma, "turma")
        and match(context.trimestre, "trimestre")
    )


def carregar_notas_notion(
    logger: Optional[LogFn] = None,
    filtro: Optional[Dict[str, str]] = None,
) -> List[RegistroNota]:
    root_page_id = _normalize_notion_id(ROOT_PAGE_ID)

    if not NOTION_TOKEN or not root_page_id:
        raise LancamentoError("Defina NOTION_TOKEN e ROOT_PAGE_ID nas variaveis de ambiente.")
    if _is_placeholder_env(NOTION_TOKEN) or _is_placeholder_env(ROOT_PAGE_ID):
        raise LancamentoError("NOTION_TOKEN/ROOT_PAGE_ID estao com placeholders. Atualize com valores reais.")

    notion = Client(auth=NOTION_TOKEN)
    _log(logger, "Conectando ao Notion e descobrindo databases...")
    databases = _search_databases_by_name("Notas Escolas", set(), logger=logger)
    if not databases:
        _log(logger, "Nenhuma database encontrada via busca por nome, percorrendo arvore...")
        databases = _discover_databases(notion, root_page_id, logger=logger)

    if not databases:
        raise LancamentoError("Nenhuma database foi encontrada.")

    registros: List[RegistroNota] = []
    candidatos: List[Dict[str, Any]] = []

    escola_filtro = _normalize(filtro.get("escola", "")) if filtro else ""
    ignoradas_escola = 0

    for db_id, breadcrumb, db_title in databases:
        try:
            # Usa cache de metadata para evitar retrive redundante
            if db_id in _db_metadata_cache:
                db_obj = _db_metadata_cache[db_id]
                _log(logger, f"  [CACHE] Metadata da database '{db_title}' obtida do cache.")
            else:
                db_obj = _safe_notion_call(lambda: notion.databases.retrieve(database_id=db_id))
                _db_metadata_cache[db_id] = db_obj
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"Aviso: falha ao ler metadata da database {db_id}: {exc}")
            continue

        title = _database_title(db_obj) or db_title
        if not _is_notas_database(title):
            _log(logger, f"Aviso: database ignorada (nome nao reconhecido): '{title}' (breadcrumb: {' > '.join(breadcrumb)})")
            continue

        # Pre-filtro rapido por escola: se o filtro especifica uma escola e o
        # titulo/breadcrumb nao a mencionam, pula sem log verbose.
        if escola_filtro:
            full_path = f"{' '.join(breadcrumb)} {title}"
            if escola_filtro not in _normalize(full_path):
                ignoradas_escola += 1
                continue

        context = _infer_context([*breadcrumb, title])
        _log(logger, f"Database: '{title}' | contexto inferido: {context.escola} | {context.turno} | {context.turma} | {context.trimestre}")
        if not _context_matches_filter(context, filtro):
            _log(logger, f"  -> Ignorada: filtro {filtro} nao corresponde ao contexto")
            continue

        try:
            rows = _query_database_rows(notion, db_id, database_obj=db_obj)
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"Aviso: pulando database inacessivel {title or db_id}: {exc}")
            continue

        if not rows:
            _log(logger, f"  -> Database sem linhas: '{title}'")
            continue

        candidatos.append(
            {
                "db_id": db_id,
                "title": title,
                "context": context,
                "rows": rows,
            }
        )

    if ignoradas_escola:
        _log(logger, f"  -> {ignoradas_escola} database(s) de outras escolas ignoradas pelo filtro.")

    if not candidatos:
        return registros

    # Em caso de bases duplicadas com o mesmo titulo, processa apenas a com mais linhas.
    deduplicadas: Dict[str, Dict[str, Any]] = {}
    duplicadas_ignoradas = 0
    for candidato in candidatos:
        key = _normalize(candidato["title"])
        atual = deduplicadas.get(key)
        if atual is None:
            deduplicadas[key] = candidato
            continue

        if len(candidato["rows"]) > len(atual["rows"]):
            deduplicadas[key] = candidato
            duplicadas_ignoradas += 1
        else:
            duplicadas_ignoradas += 1

    if duplicadas_ignoradas:
        _log(logger, f"Aviso: {duplicadas_ignoradas} database(s) duplicada(s) foram ignoradas automaticamente.")

    for item in deduplicadas.values():
        title = item["title"]
        context = item["context"]
        rows = item["rows"]
        _log(logger, f"Database {title}: {len(rows)} alunos encontrados")

        if rows:
            sample_props = rows[0].get("properties", {})
            all_cols = list(sample_props.keys())
            grade_cols = [c for c in all_cols if _is_probably_grade_column(c)]
            _log(logger, f"  [diag] Colunas da database ({len(all_cols)}): {', '.join(all_cols)}")
            if grade_cols:
                _log(logger, f"  [diag] Colunas de nota detectadas: {', '.join(grade_cols)}")
            else:
                _log(logger, f"  [diag] NENHUMA coluna de nota detectada!")

        # Pre-computa mapeamento coluna_de_nota → Status lancamento N
        # usando "Data realização N" como ancora (ordem da API pode variar)
        grade_status_map = _build_grade_status_map(rows[0].get("properties", {})) if rows else {}
        if grade_status_map:
            _log(logger, f"  [diag] Mapeamento nota→status: {grade_status_map}")

        for row in rows:
            props = row.get("properties", {})

            aluno = ""
            if "Nome" in props:
                aluno = _extract_plain_text(props["Nome"]).strip()
            if not aluno:
                for prop in props.values():
                    if prop.get("type") == "title":
                        aluno = _extract_plain_text(prop).strip()
                        if aluno:
                            break

            if not _is_non_empty(aluno):
                continue

            # Mapeia colunas de nota para "Status lancamento N" usando ancora
            # "Data realização N" (ordem da API do Notion pode variar)
            for col_name, prop in props.items():
                if not _is_probably_grade_column(col_name):
                    continue

                atividade_nome = col_name.strip()

                # Usa mapeamento pre-computado; fallback para resolução por numero
                status_prop_nome = grade_status_map.get(col_name, "")
                if not status_prop_nome:
                    # Fallback: tenta extrair numero do nome da coluna.
                    # Preferencialmente usa o ultimo numero (ex.: "24 - Resolucao 1" → "1"),
                    # pois o primeiro pode ser parte do nome (ex.: "24").
                    all_nums = re.findall(r"(\d+)", col_name)
                    if all_nums:
                        last_num = all_nums[-1]
                        cand = f"Status lancamento {last_num}"
                        if any(
                            re.search(rf"status\s*lancamento\s*{re.escape(last_num)}", _normalize(p))
                            for p in props
                        ):
                            status_prop_nome = cand
                        else:
                            # Tenta o primeiro numero como ultimo recurso
                            first_num = all_nums[0]
                            cand_first = f"Status lancamento {first_num}"
                            if any(
                                re.search(rf"status\s*lancamento\s*{re.escape(first_num)}", _normalize(p))
                                for p in props
                            ):
                                status_prop_nome = cand_first
                            else:
                                continue
                    else:
                        continue

                # Verifica se a atividade ja foi lancada (Status lancamento N == "Lancada")
                status_prop_real = _resolve_existing_status_prop(props, status_prop_nome)
                status_val = ""
                if status_prop_real:
                    status_info = props.get(status_prop_real, {})
                    ptype = status_info.get("type", "")
                    if ptype == "select":
                        status_val = ((status_info.get("select") or {}).get("name") or "").strip()
                    elif ptype == "status":
                        status_val = ((status_info.get("status") or {}).get("name") or "").strip()
                    elif ptype == "rich_text":
                        rt = status_info.get("rich_text") or []
                        status_val = "".join(t.get("plain_text", "") for t in rt).strip() if isinstance(rt, list) else ""

                # Le a data de realizacao da atividade (Data realização N)
                data_realizacao = ""
                num_match_data = re.search(r"(\d+)", status_prop_nome)
                if num_match_data:
                    n_data = num_match_data.group(1)
                    for pname, pval in props.items():
                        if re.search(rf"data\s*realiza[çc][ãa]o\s*{re.escape(n_data)}", _normalize(pname)):
                            data_realizacao = _extract_plain_text(pval).strip()
                            break

                raw_val = _extract_plain_text(prop)
                nota = _to_float(raw_val)
                if nota is None:
                    if status_val == "Lancada":
                        _log(logger, f"  [skip] '{aluno}' - '{atividade_nome}' ja lancada (status Lancada, nota ausente)")
                    continue

                if status_val == "Lancada":
                    _log(logger, f"  [skip] '{aluno}' - '{atividade_nome}' ja lancada (status Lancada, nota={nota})")
                    continue

                registros.append(
                    RegistroNota(
                        escola=context.escola,
                        turno=context.turno,
                        turma=context.turma,
                        trimestre=context.trimestre,
                        aluno=aluno,
                        atividade=atividade_nome,
                        nota=nota,
                        notion_page_id=row.get("id", ""),
                        notion_status_prop=status_prop_nome,
                        data_realizacao=data_realizacao,
                    )
                )

    if not registros:
        raise LancamentoError("Nenhuma nota valida foi encontrada no Notion.")

    _log(logger, f"Total de notas carregadas do Notion: {len(registros)}")
    return registros


def listar_contextos_disponiveis(logger: Optional[LogFn] = None) -> List[Dict[str, str]]:
    try:
        registros = carregar_notas_notion(logger=logger)
        contextos = {
            (r.escola, r.turno, r.turma, r.trimestre)
            for r in registros
        }
        result = [
            {"escola": e, "turno": t, "turma": tu, "trimestre": tr}
            for e, t, tu, tr in sorted(contextos)
        ]
        return result
    except LancamentoError as exc:
        if "Nenhuma nota valida" not in str(exc):
            raise

    root_page_id = _normalize_notion_id(ROOT_PAGE_ID)

    if not NOTION_TOKEN or not root_page_id:
        raise LancamentoError("Defina NOTION_TOKEN e ROOT_PAGE_ID nas variaveis de ambiente.")

    notion = Client(auth=NOTION_TOKEN)
    _log(logger, "Nenhuma nota valida encontrada. Listando contextos pela estrutura das databases...")
    databases = _search_databases_by_name("Notas Escolas", set(), logger=logger)
    if not databases:
        databases = _discover_databases(notion, root_page_id, logger=logger)

    contextos = set()
    for db_id, breadcrumb, db_title in databases:
        try:
            db_obj = _safe_notion_call(lambda: notion.databases.retrieve(database_id=db_id))
            title = _database_title(db_obj) or db_title
        except Exception:  # noqa: BLE001
            title = db_title

        if not _is_notas_database(title):
            continue

        ctx = _infer_context([*breadcrumb, title])
        if "nao identificado" in ctx.turno.lower() or "nao identificado" in ctx.turma.lower():
            continue
        contextos.add((ctx.escola, ctx.turno, ctx.turma, ctx.trimestre))

    return [
        {"escola": e, "turno": t, "turma": tu, "trimestre": tr}
        for e, t, tu, tr in sorted(contextos)
    ]


def _filtrar_registros(registros: List[RegistroNota], filtro: Optional[Dict[str, str]], logger: Optional[LogFn] = None) -> List[RegistroNota]:
    if not filtro:
        return registros

    _log(logger, f"[FILTRO] Filtro aplicado: {filtro}")
    _log(logger, f"[FILTRO] Registros antes do filtro: {len(registros)}")

    def match(value: str, key: str) -> bool:
        expected = filtro.get(key)
        if not expected:
            return True
        if key == "turma":
            result = _match_turma(expected, value)
        else:
            result = _normalize(expected) in _normalize(value)
        if not result:
            _log(logger, f"[FILTRO] Descartado por '{key}': esperado='{expected}', valor='{value}'")
        return result

    def _normalize_date(date_str: str) -> str:
        """Normaliza data para formato AAAA-MM-DD para comparacao."""
        if not date_str:
            return ""
        d = date_str.strip()
        # Formato dd/mm/aaaa ou dd-mm-aaaa
        m = re.match(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", d)
        if m:
            day, month, year = m.group(1), m.group(2), m.group(3)
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        # Formato aaaa-mm-dd
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", d)
        if m:
            return d
        return _normalize(d)

    def match_date(value: str, key: str) -> bool:
        expected = filtro.get(key)
        if not expected:
            return True
        # Se o registro nao tem data, nao filtra por data (deixa passar)
        if not value:
            return True
        # Normaliza ambas as datas para formato AAAA-MM-DD
        expected_norm = _normalize_date(expected)
        value_norm = _normalize_date(value)
        # Tenta comparacao exata primeiro
        if expected_norm == value_norm:
            return True
        # Fallback: comparacao por substring apos normalizacao
        result = _normalize(expected) in _normalize(value)
        if not result:
            _log(logger, f"[FILTRO] Descartado por '{key}': esperado='{expected}' (norm='{expected_norm}'), valor='{value}' (norm='{value_norm}')")
        return result

    resultado = [
        r
        for r in registros
        if match(r.escola, "escola")
        and match(r.turno, "turno")
        and match(r.turma, "turma")
        and match(r.trimestre, "trimestre")
        and match(r.atividade, "atividade")
        and match_date(r.data_realizacao, "data_realizacao")
    ]
    _log(logger, f"[FILTRO] Registros apos filtro: {len(resultado)}")
    return resultado


def _first_visible(page, selectors: List[str]):
    for selector in selectors:
        loc = page.locator(selector)
        if loc.count() > 0:
            try:
                if loc.first.is_visible():
                    return loc.first
            except Exception:  # noqa: BLE001
                continue
    return None


def _iter_scopes(page):
    scopes = [page]
    for frame in page.frames:
        if frame != page.main_frame:
            scopes.append(frame)
    return scopes


def _pick_user_input(scope):
    # 1) Seletor direto de usuario/cpf quando existir.
    direct = _first_visible(
        scope,
        [
            "#_USUCOD",
            "input[name='_USUCOD']",
            "input[name*='cpf' i]",
            "input[id*='cpf' i]",
            "input[placeholder*='cpf' i]",
            "input[name*='usuario' i]",
            "input[id*='usuario' i]",
            "input[placeholder*='usuario' i]",
            "input[name*='login' i]",
            "input[id*='login' i]",
            "input[placeholder*='login' i]",
            "input[name*='user' i]",
            "input[id*='user' i]",
            "input[placeholder*='user' i]",
            "input[name*='email' i]",
            "input[id*='email' i]",
            "input[autocomplete='username']",
            "input[autocomplete='current-password']",
        ],
    )
    if direct is not None:
        return direct

    # 2) Heuristica para evitar cair no campo Ano.
    candidates = scope.locator("input[type='text'], input[type='tel']")
    best = None
    best_score = -999
    total = candidates.count()
    for idx in range(total):
        loc = candidates.nth(idx)
        try:
            if not loc.is_visible():
                continue
            name = (loc.get_attribute("name") or "").lower()
            iid = (loc.get_attribute("id") or "").lower()
            placeholder = (loc.get_attribute("placeholder") or "").lower()
            maxlength = int((loc.get_attribute("maxlength") or "0") or "0")
            size = int((loc.get_attribute("size") or "0") or "0")

            score = 0
            bag = f"{name} {iid} {placeholder}"
            if "ano" in bag:
                score -= 50
            if "cpf" in bag or "usuario" in bag:
                score += 40
            if maxlength >= 9:
                score += 10
            if size >= 9:
                score += 5

            if score > best_score:
                best = loc
                best_score = score
        except Exception:  # noqa: BLE001
            continue

    return best


def _find_login_inputs(page):
    password_selectors = [
        "#_USUSENHATELA",
        "input[name='_USUSENHATELA']",
        "input[name*='senha' i]",
        "input[id*='senha' i]",
        "input[placeholder*='senha' i]",
        "input[type='password']",
    ]

    for scope in _iter_scopes(page):
        user_input = _pick_user_input(scope)
        password_input = _first_visible(scope, password_selectors)
        if user_input is not None and password_input is not None:
            return scope, user_input, password_input
    return None, None, None


def _capture_login_debug(page, logger: Optional[LogFn]) -> None:
    try:
        os.makedirs(DEBUG_OUTPUT_DIR, exist_ok=True)
        screenshot_path = os.path.join(DEBUG_OUTPUT_DIR, "login_failure.png")
        html_path = os.path.join(DEBUG_OUTPUT_DIR, "login_failure.html")
        info_path = os.path.join(DEBUG_OUTPUT_DIR, "login_failure_info.txt")

        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())

        lines = [f"URL atual: {page.url}"]
        lines.append(f"Frames encontrados: {len(page.frames)}")
        for idx, frame in enumerate(page.frames):
            lines.append(f"- frame[{idx}] name={frame.name!r} url={frame.url}")

        for scope in _iter_scopes(page):
            try:
                kinds = {
                    "password": scope.locator("input[type='password']").count(),
                    "text": scope.locator("input[type='text']").count(),
                    "tel": scope.locator("input[type='tel']").count(),
                    "submit": scope.locator("button[type='submit'], input[type='submit']").count(),
                }
                lines.append(
                    "scope="
                    f"{getattr(scope, 'url', 'about:blank')} | "
                    f"inputs(password/text/tel)={kinds['password']}/{kinds['text']}/{kinds['tel']} | "
                    f"submit={kinds['submit']}"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"scope-inspect-error: {exc}")

        with open(info_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        _log(
            logger,
            "Diagnostico de login salvo em artifacts/sge-login (screenshot/html/info).",
        )
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"Aviso: falha ao salvar diagnostico de login: {exc}")


def _capture_stage_debug(page, stage: str, logger: Optional[LogFn]) -> None:
    if not DEBUG_LOGIN:
        return
    if stage in _DEBUG_CAPTURED_STAGES:
        return

    _DEBUG_CAPTURED_STAGES.add(stage)

    try:
        os.makedirs(DEBUG_OUTPUT_DIR, exist_ok=True)
        screenshot_path = os.path.join(DEBUG_OUTPUT_DIR, f"{stage}.png")
        html_path = os.path.join(DEBUG_OUTPUT_DIR, f"{stage}.html")
        info_path = os.path.join(DEBUG_OUTPUT_DIR, f"{stage}_info.txt")

        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())

        lines = [f"stage={stage}", f"url={page.url}", f"frames={len(page.frames)}"]
        for idx, frame in enumerate(page.frames):
            lines.append(f"frame[{idx}] name={frame.name!r} url={frame.url}")
            try:
                links = frame.locator("a")
                total_links = min(links.count(), 25)
                lines.append(f"frame[{idx}] sample_links={total_links}")
                for i in range(total_links):
                    txt = (links.nth(i).inner_text(timeout=200) or "").strip()
                    if txt:
                        lines.append(f"  - {txt}")
            except Exception:  # noqa: BLE001
                continue

        with open(info_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        _log(logger, f"Diagnostico da etapa '{stage}' salvo em {DEBUG_OUTPUT_DIR}.")
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"Aviso: falha ao salvar diagnostico da etapa {stage}: {exc}")


def _is_session_lost_page(page) -> bool:
    url = (page.url or "").lower()
    if "htelaperdeusessao.aspx" in url:
        return True
    try:
        return page.locator("input[name='BUTTON1'][type='submit']").count() > 0
    except Exception:  # noqa: BLE001
        return False


def _ensure_login_form_available(page, logger: Optional[LogFn]) -> None:
    _, cpf_input, senha_input = _find_login_inputs(page)
    if cpf_input is not None and senha_input is not None:
        return

    if _is_session_lost_page(page):
        _log(logger, "Sessao expirada detectada no SGE; tentando reconectar para tela de login...")
        try:
            page.locator("input[name='BUTTON1'][type='submit']").first.click(timeout=ACTION_TIMEOUT_MS)
            page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(250)
        except Exception:  # noqa: BLE001
            pass

    _, cpf_input, senha_input = _find_login_inputs(page)
    if cpf_input is not None and senha_input is not None:
        return

    current_url = (page.url or "").strip()
    for fallback_url in PORTAL_LOGIN_FALLBACK_URLS:
        if current_url.lower() == fallback_url.lower():
            continue
        _log(logger, f"Formulario de login nao encontrado em {page.url}; tentando {fallback_url}")
        try:
            page.goto(fallback_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(250)
        except Exception:  # noqa: BLE001
            continue
        _, cpf_input, senha_input = _find_login_inputs(page)
        if cpf_input is not None and senha_input is not None:
            return

    if ai_is_enabled():
        _log(logger, "[AI] Fallbacks exauridos. Tentando encontrar formulario de login via IA...")
        try:
            screenshot = page.screenshot()
            ai_result = analyze_login_screen(screenshot, logger=logger)
            if ai_result.get("has_login_form") and ai_result.get("elements"):
                _log(logger, "[AI] IA identificou campos de login. Tentando preencher diretamente...")
                for elem in ai_result["elements"]:
                    selector = elem.get("selector", "")
                    if not selector:
                        continue
                    try:
                        loc = page.locator(selector)
                        if loc.count() > 0:
                            _log(logger, f"[AI] Elemento visivel via IA: {elem.get('type')} -> {selector}")
                    except Exception:
                        continue
                return
        except Exception as exc:
            _log(logger, f"[AI] Erro na analise via IA: {exc}")

    _capture_login_debug(page, logger=logger)
    raise LancamentoError(
        f"Nao foi possivel encontrar formulario de login apos {len(PORTAL_LOGIN_FALLBACK_URLS)} fallbacks. "
        f"URL atual: {page.url}"
    )


def _click_text(page, text: str) -> bool:
    text = text.strip()
    if not text:
        return False

    candidates = [
        page.get_by_role("button", name=text),
        page.get_by_role("link", name=text),
        page.get_by_role("option", name=text),
        page.get_by_text(text, exact=True),
        page.get_by_text(text, exact=False),
    ]
    for loc in candidates:
        try:
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _click_text_any_scope(page, text: str) -> bool:
    text = text.strip()
    if not text:
        return False

    for scope in _iter_scopes(page):
        candidates = [
            scope.get_by_role("button", name=text),
            scope.get_by_role("link", name=text),
            scope.get_by_role("option", name=text),
            scope.get_by_text(text, exact=True),
            scope.get_by_text(text, exact=False),
        ]
        for loc in candidates:
            try:
                if loc.count() > 0:
                    loc.first.click(timeout=2000)
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _click_any_selector_any_scope(page, selectors: List[str]) -> bool:
    for scope in _iter_scopes(page):
        for selector in selectors:
            try:
                loc = scope.locator(selector)
                total = min(loc.count(), 8)
            except Exception:  # noqa: BLE001
                continue

            for idx in range(total):
                node = loc.nth(idx)
                try:
                    if not node.is_visible():
                        continue
                    node.click(timeout=ACTION_TIMEOUT_MS)
                    return True
                except Exception:  # noqa: BLE001
                    continue
    return False


def _dismiss_cookie_banner(page, logger: Optional[LogFn]) -> None:
    # Banner de consentimento pode sobrepor a tela de login no CI.
    labels = ["Concordo", "Aceitar", "OK", "Entendi"]
    for label in labels:
        try:
            if _click_text_any_scope(page, label):
                _log(logger, f"Banner de cookies detectado; clicado em '{label}'.")
                page.wait_for_timeout(250)
                return
        except Exception:  # noqa: BLE001
            continue


def _is_login_page(page) -> bool:
    url = (page.url or "").lower()
    if "hlogin8147.aspx" in url:
        return True
    try:
        # Marcadores de pagina POS-login (dashboard do professor / selecao de escolas).
        # O SGE mantem o formulario de login (colapsado) no DOM mesmo depois de logar,
        # portanto a presenca de _NMRCPFSRV/_SENHAWEB NAO basta para dizer que e tela de login.
        # Verificados empiricamente: na pagina de login pura esses elementos nao existem (=0).
        if page.locator("input[name='W0019_SERNOM']").count() > 0:
            return False
        if page.locator("input[name^='W0019_UECODNOM_']").count() > 0:
            return False
        if page.locator("#W0019REFRESH1").count() > 0:
            return False
        if page.locator("select[name='W0019_SECNUMFILTRODISC']").count() > 0:
            return False
        if page.locator("input[name='W0019_TURNUMFILTRODISC']").count() > 0:
            return False
    except Exception:  # noqa: BLE001
        pass
    try:
        if page.locator("input[name='_USUCOD']").count() > 0:
            return True
        # SGE: formulario de login fica em hportalprofessor.aspx (sem _USUCOD).
        if page.locator("input[name='_NMRCPFSRV']").count() > 0:
            return True
        if page.locator("input[name='_SENHAWEB']").count() > 0:
            return True
        if page.locator("input[name='BTNLOGIN']").count() > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _is_school_selection_page(page) -> bool:
    """Retorna True se a pagina mostra a lista de escolas para selecionar (pos-login)."""
    url = (page.url or "").lower()
    if "hlogin8147" in url:
        return False
    if "hportalprofperiodos" in url:
        return False
    if _is_login_page(page):
        return False
    try:
        if page.locator("input[name='_USUCOD']").count() > 0:
            return False
        if page.locator("select[name='W0019_SECNUMFILTRODISC']").count() > 0:
            return False
        # Pos-login: lista de escolas do professor (W0019_UECODNOM_nnn) e nome do
        # professor logado (W0019_SERNOM) sao marcadores diretos da tela de escolas.
        if page.locator("input[name^='W0019_UECODNOM_']").count() > 0:
            return True
        if page.locator("input[name='W0019_SERNOM']").count() > 0:
            return True
        # Procura links com nomes de escola ou texto indicativo
        links = page.locator("a")
        total = min(links.count(), 40)
        found_school = False
        for idx in range(total):
            texto = (links.nth(idx).inner_text(timeout=200) or "").strip()
            if not texto:
                continue
            if any(p in texto.lower() for p in ["escola", "professor", "selecion", "acessar", "entrar"]):
                found_school = True
            if texto.lower().startswith("escola"):
                return True
        return found_school and total > 2
    except Exception:  # noqa: BLE001
        pass
    return False


def _select_school(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> None:
    """Clica no nome da escola na tela de selecao de escolas."""
    escola = contexto.escola
    if not escola:
        return
    _log(logger, f"Selecionando escola: {escola}")
    if _click_text_any_scope(page, escola):
        _clear_slots_cache()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(200)
        _log(logger, f"Escola '{escola}' selecionada.")
    else:
        _log(logger, f"Aviso: nao foi possivel clicar na escola '{escola}'.")


def _is_period_selection_page(page) -> bool:
    """Retorna True se a pagina e a tela de selecao de periodo/trimestre."""
    url = (page.url or "").lower()
    if "hportalprofperiodos" in url:
        return True
    try:
        # Exclusoes: pagina de login ou dashboard do professor
        if page.locator("input[name='_USUCOD']").count() > 0:
            return False
        if page.locator("select[name='W0019_SECNUMFILTRODISC']").count() > 0:
            return False
        # Exclusao: grade de alunos (Nome Estudante presente)
        if _is_student_grid_visible(page):
            return False
        # Exclusao: pagina contem campos de nota (ja estamos na grade)
        if page.locator("input[name*='_NOTA_' i]").count() > 0:
            return False
        # Procura por trimestres como links/botoes + indicador de tela de periodo
        if page.get_by_text("Período Letivo", exact=False).count() > 0:
            return True
        # Só considera periodo se houver multiplas opcoes de trimestre visiveis
        opcoes = 0
        for periodo in ["1o", "2o", "3o"]:
            if page.get_by_text(periodo, exact=False).count() > 0:
                opcoes += 1
        if opcoes >= 2:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _select_period(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> None:
    """Seleciona o trimestre na tela de selecao de periodo e confirma."""
    trimestre = contexto.trimestre
    if not trimestre:
        return
    _log(logger, f"Selecionando periodo: {trimestre}")

    # Tenta clicar no texto do trimestre (caso seja um link)
    clicked = _click_text_any_scope(page, trimestre)
    if clicked:
        _clear_slots_cache()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(200)
        _log(logger, f"Periodo '{trimestre}' selecionado.")
        return

    # Se ja estiver pre-selecionado, procura botao de confirmar/visualizar
    _log(logger, "Periodo pode ja estar pre-selecionado. Procurando botao de confirmar...")
    for texto_botao in ["Continuar", "Visualizar", "Prosseguir", "Visualisar", "Confirmar", "OK", "Acessar", "Selecionar", "Abrir"]:
        if _click_text_any_scope(page, texto_botao):
            _clear_slots_cache()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(200)
            _log(logger, f"Botao '{texto_botao}' clicado para confirmar periodo.")
            return

    _log(logger, f"Aviso: nao foi possivel selecionar o periodo '{trimestre}'.")


def _handle_assessment_period_page(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> bool:
    """Apos clicar no icone de avaliacao, confirma o trimestre se a tela de periodo aparecer."""
    page.wait_for_timeout(200)

    if not _is_period_selection_page(page):
        return False

    _log(logger, "Tela de selecao de trimestre detectada apos icone de avaliacao.")
    _select_period(page, contexto, logger=logger)

    # Apos confirmar, aguarda navegacao e verifica se chegou na grade de alunos
    _clear_slots_cache()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(200)

    # Se chegou na grade, consideramos periodo resolvido com sucesso
    if _is_student_grid_visible(page):
        _log(logger, "Grade de alunos detectada apos confirmar periodo.")
        return False  # False = nao precisa de retry, ja estamos na grade

    return True


def _wait_for_manual_login(page, logger: Optional[LogFn]) -> bool:
    deadline = time.time() + max(30, MANUAL_LOGIN_TIMEOUT_SEC)
    while time.time() < deadline:
        if not _is_login_page(page):
            return True
        page.wait_for_timeout(250)
    _log(logger, "Timeout aguardando login manual no SGE.")
    return False


def _read_login_error_message(page) -> str:
    try:
        err_loc = page.locator(".ErrorViewer")
        if err_loc.count() > 0:
            return (err_loc.first.inner_text(timeout=1200) or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _is_dashboard_page(page) -> bool:
    """Retorna True se a pagina atual parece ser o painel do professor (pos-login)."""
    url = (page.url or "").lower()
    if "hlogin8147" in url:
        return False
    # Nao confundir com a tela de login (que tem titulo "PORTAL DO PROFESSOR").
    if _is_login_page(page):
        return False
    try:
        # Elementos tipicos do dashboard do professor no SGE
        if page.locator("select[name='W0019_SECNUMFILTRODISC']").count() > 0:
            return True
        if page.locator("input[name='W0019_TURNUMFILTRODISC']").count() > 0:
            return True
        if page.locator("#W0019REFRESH1").count() > 0:
            return True
        # Fallback por texto (somente apos descartar a tela de login).
        if page.get_by_text("Professor", exact=False).count() > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _confirm_logged_in(page, logger: Optional[LogFn]) -> None:
    """Apos o login, verifica se entrou no dashboard, selecao de escolas ou periodo."""
    for _ in range(15):
        if _is_dashboard_page(page):
            _log(logger, "Dashboard do professor detectado.")
            return
        if _is_school_selection_page(page):
            _log(logger, "Tela de selecao de escolas detectada.")
            return
        if _is_period_selection_page(page):
            _log(logger, "Tela de selecao de periodo detectada.")
            return
        page.wait_for_timeout(250)
    _capture_stage_debug(page, stage="post_login_not_dashboard", logger=logger)
    url_atual = page.url
    raise LancamentoError(
        f"Login aparentemente falhou: pagina atual ({url_atual}) nao contem o painel do professor, "
        "selecao de escolas ou periodo. Verifique CPF/senha ou tente HEADLESS=0 para visualizar."
    )


def _wait_login_outcome(page, timeout_sec: float = 40.0):
    """Aguarda o resultado do login (postback AJAX do GeneXus).

    Retorna (ainda_na_tela_de_login, mensagem_de_erro). Se a tela de login
    sumiu (sucesso/redirect), retorna (False, ""). Se o .ErrorViewer apareceu
    (falha), retorna (True, texto_do_erro).
    """
    deadline = time.time() + timeout_sec
    err = ""
    while time.time() < deadline:
        if not _is_login_page(page):
            return False, ""
        err = _read_login_error_message(page)
        if err:
            return True, err
        page.wait_for_timeout(250)
    return True, err


def _login_sge_with_retry(page, cpf: str, senha: str, logger: Optional[LogFn], attempt: int = 1) -> None:
    login_url = _resolve_sge_login_url(logger=logger)
    _log(logger, f"URL de login SGE resolvida: {login_url}")
    _log(logger, f"Abrindo pagina de login do SGE (tentativa {attempt})...")
    page.goto(login_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    _ensure_login_form_available(page, logger=logger)
    _dismiss_cookie_banner(page, logger=logger)

    scope = None
    cpf_input = None
    senha_input = None
    deadline = time.time() + (NAV_TIMEOUT_MS / 1000)
    while time.time() < deadline:
        scope, cpf_input, senha_input = _find_login_inputs(page)
        if cpf_input is not None and senha_input is not None:
            break
        page.wait_for_timeout(200)

    if cpf_input is None or senha_input is None or scope is None:
        if ai_is_enabled():
            _log(logger, "[AI] Campos de login nao encontrados por seletores. Tentando IA...")
            try:
                screenshot = page.screenshot()
                ai_result = analyze_login_screen(screenshot, logger=logger)
                for elem in ai_result.get("elements", []):
                    selector = elem.get("selector", "")
                    etype = elem.get("type", "")
                    if not selector or not etype:
                        continue
                    try:
                        loc = page.locator(selector)
                        if loc.count() > 0 and loc.first.is_visible():
                            _log(logger, f"[AI] Elemento '{etype}' via IA: {selector}")
                            if etype == "cpf_input":
                                cpf_input = loc.first
                            elif etype == "password_input":
                                senha_input = loc.first
                            elif etype == "login_button":
                                pass
                            if cpf_input is not None and senha_input is not None:
                                scope = page
                                break
                    except Exception:
                        continue
            except Exception as exc:
                _log(logger, f"[AI] Erro: {exc}")

    if cpf_input is None or senha_input is None or scope is None:
        raise LancamentoError(
            f"Nao foi possivel localizar os campos de login no SGE. URL atual: {page.url}"
        )

    cpf_input.fill(cpf, timeout=ACTION_TIMEOUT_MS)
    senha_input.fill(senha, timeout=ACTION_TIMEOUT_MS)

    # Confere se o valor realmente ficou no campo usuario.
    try:
        cpf_current = (cpf_input.input_value(timeout=ACTION_TIMEOUT_MS) or "").strip()
    except Exception:  # noqa: BLE001
        cpf_current = ""

    if not cpf_current:
        # Fallback via JS para contornar overlays/handlers que limpam o campo.
        try:
            page.eval_on_selector(
                "input[name='_USUCOD'], #_USUCOD",
                "(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }",
                cpf,
            )
            page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            pass

    _submit_selectors = [
        "input[name='BTNLOGIN']",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Entrar')",
        "button:has-text('Acessar')",
        "button:has-text('Login')",
        "input[value*='Entrar' i]",
        "input[value*='Acessar' i]",
        "input[value*='Login' i]",
        "a:has-text('Entrar')",
        "a:has-text('Acessar')",
        "input[type='image'][src*='login' i]",
        "input[type='image'][alt*='entrar' i]",
    ]
    submit = _first_visible(scope, _submit_selectors)
    if submit is None:
        submit = _first_visible(page, _submit_selectors)
    if submit is None:
        raise LancamentoError("Nao foi possivel localizar botao de login no SGE.")

    _dismiss_cookie_banner(page, logger=logger)
    submit.click(timeout=ACTION_TIMEOUT_MS)

    on_login, err = _wait_login_outcome(page)

    if on_login:
        senha_upper = senha.upper()
        if "senha inval" in _normalize(err) and senha_upper != senha:
            _log(logger, "Senha invalida no primeiro envio; tentando novamente com senha em maiusculas...")
            scope2, cpf_input2, senha_input2 = _find_login_inputs(page)
            if scope2 is not None and cpf_input2 is not None and senha_input2 is not None:
                cpf_input2.fill(cpf, timeout=ACTION_TIMEOUT_MS)
                senha_input2.fill(senha_upper, timeout=ACTION_TIMEOUT_MS)
                _retry_submit_selectors = [
                    "input[name='BTNLOGIN']",
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Entrar')",
                    "button:has-text('Acessar')",
                    "button:has-text('Login')",
                    "input[value*='Entrar' i]",
                    "input[value*='Acessar' i]",
                    "input[value*='Login' i]",
                    "a:has-text('Entrar')",
                    "a:has-text('Acessar')",
                ]
                submit2 = _first_visible(scope2, _retry_submit_selectors)
                if submit2 is None:
                    submit2 = _first_visible(page, _retry_submit_selectors)
                if submit2 is not None:
                    _dismiss_cookie_banner(page, logger=logger)
                    submit2.click(timeout=ACTION_TIMEOUT_MS)
                    on_login, err = _wait_login_outcome(page)
                    if not on_login:
                        _log(logger, "Login realizado. Iniciando lancamento...")
                        _confirm_logged_in(page, logger=logger)
                        return

        _capture_stage_debug(page, stage="login_failed", logger=logger)
        _capture_login_debug(page, logger=logger)
        detalhe = err if err else "permaneceu na tela de login apos submeter credenciais"
        raise LancamentoError(f"Falha no login do SGE: {detalhe} (URL: {page.url})")

    _log(logger, "Login realizado. Iniciando lancamento...")
    _confirm_logged_in(page, logger=logger)


def _looks_like_placeholder_senha(senha: str) -> bool:
    return (senha or "").strip().lower() in {
        "123456",
        "12345678",
        "12345",
        "123",
        "senha",
        "sua_senha",
        "teste",
        "test",
        "password",
    }


def _login_sge(page, cpf: str, senha: str, logger: Optional[LogFn]) -> None:
    if MANUAL_LOGIN and os.environ.get("GITHUB_ACTIONS") != "true":
        login_url = _resolve_sge_login_url(logger=logger)
        _log(logger, f"URL de login SGE resolvida: {login_url}")
        _log(logger, "Abrindo pagina de login do SGE (modo manual)...")
        page.goto(login_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if HEADLESS:
            raise LancamentoError("MANUAL_LOGIN=1 exige HEADLESS=0 para abrir o navegador.")
        _log(
            logger,
            "MANUAL_LOGIN ativo: faça login manualmente no navegador aberto. O script continuara apos detectar autenticacao.",
        )
        if not _wait_for_manual_login(page, logger=logger):
            _capture_stage_debug(page, stage="manual_login_timeout", logger=logger)
            raise LancamentoError("Login manual nao concluido dentro do tempo limite.")
        _log(logger, "Login manual detectado. Iniciando lancamento...")
        return

    # Normaliza e valida credenciais em TODOS os fluxos (imagem, revisao,
    # chamada, sequencia). O portal 8147 espera CPF com 11 digitos e apenas
    # numeros; enviar CPF curto/quebrado faz o portal responder com a mensagem
    # generica "CPF nao cadastrado! Senha nao confere!". Aqui damos um erro
    # claro antes de submeter.
    cpf = _normalize_cpf_for_sge(cpf, logger=logger)
    senha = (senha or "").strip()
    if not cpf:
        raise LancamentoError("CPF do portal vazio. Informe o CPF completo (11 digitos) na barra lateral.")
    if not senha:
        raise LancamentoError("Senha do portal vazia. Informe a senha na barra lateral.")
    if _looks_like_placeholder_senha(senha):
        _log(logger, "AVISO: a senha parece ser de teste/placeholder. Confirme se e a senha REAL do portal (www.sge8147.com.br).")

    max_attempts = 4
    last_exception = None
    for attempt in range(1, max_attempts + 1):
        try:
            _login_sge_with_retry(page, cpf=cpf, senha=senha, logger=logger, attempt=attempt)
            return
        except LancamentoError as exc:
            last_exception = exc
            error_msg = str(exc)
            norm_msg = _normalize(error_msg)
            # Nao retenta se for erro de credencial (senha invalida / CPF nao cadastrado).
            if ("senha inval" in norm_msg
                    or "senha nao confere" in norm_msg
                    or "cpf nao cadastrado" in norm_msg):
                _log(logger, "Credencial invalida detectada; sem retentativa.")
                raise
            if attempt < max_attempts:
                wait_sec = 3 * attempt
                _log(logger, f"Tentativa {attempt} falhou: {exc}. Aguardando {wait_sec}s e recarregando pagina...")
                _capture_stage_debug(page, stage=f"login_retry_{attempt}", logger=logger)
                page.wait_for_timeout(wait_sec * 1000)
                try:
                    page.goto(_resolve_sge_login_url(logger=logger), wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001
                    pass

    _capture_stage_debug(page, stage="login_failed", logger=logger)
    raise LancamentoError(f"Falha no login do SGE apos {max_attempts} tentativas: {last_exception}")


# Cache de contexto atual (evita re-selecao desnecessaria)
_current_context: Optional[ContextoTurma] = None


def _select_context(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> None:
    global _current_context

    # Se ja estamos no mesmo contexto, pular
    if (_current_context and
        _current_context.escola == contexto.escola and
        _current_context.turno == contexto.turno and
        _current_context.turma == contexto.turma and
        _current_context.trimestre == contexto.trimestre):
        _log(logger, f"[CACHE] Contexto ja selecionado: {contexto.escola} | {contexto.turno} | {contexto.turma} | {contexto.trimestre}")
        return

    _log(logger, f"Selecionando contexto: {contexto.escola} | {contexto.turno} | {contexto.turma} | {contexto.trimestre}")

    textos = [contexto.escola, contexto.turno, contexto.turma, contexto.trimestre]
    for item in textos:
        if item.startswith("Escola nao") or item.startswith("Turno nao"):
            continue
        _click_text_any_scope(page, item)

    _current_context = contexto


def _extract_first_number(text: str) -> str:
    match = re.search(r"(\d+)", text or "")
    return match.group(1) if match else ""


def _extract_turma_number(text: str) -> str:
    raw = text or ""
    # Formato "6º Ano|1" (ano|numero_turma)
    match = re.search(r"\|\s*(\d+)\s*$", raw)
    if match:
        return match.group(1)

    # Preferencial: "Turma 1"
    match = re.search(r"turma\s*(\d+)", raw, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    # Caso digitado como "6º Ano1".
    match = re.search(r"ano\s*(\d+)\s*$", raw, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _turno_code(turno: str) -> str:
    norm = _normalize(turno)
    if "matutino" in norm:
        return "1"
    if "vespertino" in norm:
        return "2"
    if "integral" in norm:
        return "4"
    return "0"


def _set_filters_on_portal(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> None:
    etapa = _extract_first_number(contexto.turma)
    turma = _extract_turma_number(contexto.turma)
    turno = _turno_code(contexto.turno)

    for scope in _iter_scopes(page):
        try:
            etapa_sel = scope.locator("select[name='W0019_SECNUMFILTRODISC']")
            if etapa_sel.count() > 0 and etapa:
                etapa_sel.first.select_option(value=etapa)

            turno_sel = scope.locator("select[name='W0019_TRNCODFILTRODISC']")
            if turno_sel.count() > 0 and turno != "0":
                turno_sel.first.select_option(value=turno)

            turma_in = scope.locator("input[name='W0019_TURNUMFILTRODISC']")
            if turma_in.count() > 0:
                turma_in.first.fill(turma or "0")

            if _click_any_selector_any_scope(
                page,
                [
                    "#W0019REFRESH1",
                    "a[onclick*='FILTRODISCIPLINA' i]",
                    "input[type='submit'][value*='Filtr' i]",
                    "button:has-text('Filtr')",
                ],
            ):
                _clear_slots_cache()
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(200)

            _log(logger, "Filtros de contexto aplicados na tela do professor.")
            return
        except Exception:  # noqa: BLE001
            continue


WRONG_ASSESSMENT_URLS = [
    "hconteudoperiodohtml.aspx",
    "hportalplanejamentoaula.aspx",
    "hdisturfrealunopaginado.aspx",
    "havaliacaoprofagendabim.aspx",
    "hportalprofturma.aspx",
    "hportalprofperiodos.aspx",
    "hselprofessormaterialapoioaluno.aspx",
]
CORRECT_ASSESSMENT_URLS = ["hdisciplinaturmaaluno.aspx", "hdiscturalunonota.aspx"]


def _is_wrong_assessment_page(page) -> bool:
    """Verifica se a pagina apos clicar no icone nao e a de lancamento de notas."""
    try:
        url = page.url.lower()
        for correct in CORRECT_ASSESSMENT_URLS:
            if correct in url:
                return False
        for wrong in WRONG_ASSESSMENT_URLS:
            if wrong in url:
                return True
        if "adaptacao" in url or "adapt" in url:
            return True
        if page.get_by_text("Adaptação Curricular", exact=False).count() > 0:
            return True
    except Exception:
        pass
    return False


def _open_assessment_for_context(page, contexto: ContextoTurma, logger: Optional[LogFn]) -> bool:
    _set_filters_on_portal(page, contexto, logger=logger)

    turma_num = _extract_turma_number(contexto.turma)
    trimestre_num = _extract_first_number(contexto.trimestre)
    turno_norm = _normalize(contexto.turno).upper()

    # Padroes de ID do ASP.NET (podem variar entre versoes do SGE)
    _id_prefixes = ["W0019W0075", "W0019W0076", "W0019W0080", "W0019W0060"]

    for scope in _iter_scopes(page):
        # Aguarda o grid responder ao filtro antes de procurar a linha.
        for _ in range(8):
            for prefix in _id_prefixes:
                hidden_rows = scope.locator(f"input[name^='{prefix}_TURNUMSTR_']")
                if hidden_rows.count() > 0:
                    break
            else:
                hidden_rows = scope.locator("input[name*='_TURNUMSTR_']")
            if hidden_rows.count() > 0:
                break
            page.wait_for_timeout(150)

        total = hidden_rows.count()
        for idx in range(total):
            cell = hidden_rows.nth(idx)
            try:
                label = (cell.input_value(timeout=400) or "").strip()
            except Exception:  # noqa: BLE001
                continue

            norm = _normalize(label)
            ok_turno = bool(turno_norm and _normalize(turno_norm) in norm)
            ok_turma = True if not turma_num else bool(re.search(rf"\bturma\s*{re.escape(turma_num)}\b", norm))
            ok_trim = bool(trimestre_num and f"{trimestre_num}o trimestre" in norm)
            if not (ok_turno and ok_turma and ok_trim):
                continue

            try:
                # Sobe para a linha <tr> da turma
                row = cell.locator("xpath=ancestor::tr[1]")
                if row.count() == 0:
                    continue

                # Estrategia 1: procura link/imagem com alt/title/texto contendo "avalia" ou "nota"
                # Pula "Agenda Avaliações" e "Adaptação Curricular"
                def _has_texto_valido(texto: str) -> bool:
                    return "agenda" not in texto and "adaptação" not in texto and "adapt" not in texto

                def _preferir_avaliacao(texto: str) -> bool:
                    return "avaliação" in texto or "avaliacao" in texto

                for sel in [
                    "a img[alt*='Avalia' i], a img[title*='Avalia' i]",
                    "a img[alt*='Nota' i], a img[title*='Nota' i]",
                    "a img[alt*='Lan' i], a img[title*='Lan' i]",
                    "input[type='image'][alt*='Avalia' i], input[type='image'][title*='Avalia' i]",
                    "input[type='image'][alt*='Nota' i], input[type='image'][title*='Nota' i]",
                ]:
                    assessment_icon = row.locator(sel)
                    count = assessment_icon.count()
                    if count == 0:
                        continue
                    # Primeira passada: prefere icones com "avaliação" (exclui adaptacao curricular)
                    for idx_icon in range(count):
                        icon = assessment_icon.nth(idx_icon)
                        try:
                            alt_text = (icon.get_attribute("alt") or "").lower()
                            title_text = (icon.get_attribute("title") or "").lower()
                        except Exception:  # noqa: BLE001
                            alt_text = title_text = ""
                        texto_icone = f"{alt_text} {title_text}"
                        if not _has_texto_valido(texto_icone):
                            continue
                        if not _preferir_avaliacao(texto_icone):
                            continue
                        try:
                            icon.click(timeout=ACTION_TIMEOUT_MS)
                            page.wait_for_timeout(200)
                            if _is_wrong_assessment_page(page):
                                _log(logger, f"Icone errado (adaptacao), tentando proximo...")
                                continue
                            _log(logger, f"Avaliacao aberta (por atributo): {label}")
                            _learning_store.registrar_sucesso("abrir_icone_avaliacao", {"metodo": "atributo", "label": label})
                            return True
                        except Exception:  # noqa: BLE001
                            continue
                    # Segunda passada: qualquer icone valido (excluindo agenda e adaptacao)
                    for idx_icon in range(count):
                        icon = assessment_icon.nth(idx_icon)
                        try:
                            alt_text = (icon.get_attribute("alt") or "").lower()
                            title_text = (icon.get_attribute("title") or "").lower()
                        except Exception:  # noqa: BLE001
                            alt_text = title_text = ""
                        texto_icone = f"{alt_text} {title_text}"
                        if not _has_texto_valido(texto_icone):
                            continue
                        try:
                            icon.click(timeout=ACTION_TIMEOUT_MS)
                            page.wait_for_timeout(200)
                            if _is_wrong_assessment_page(page):
                                _log(logger, f"Icone errado (adaptacao), tentando proximo...")
                                continue
                            _log(logger, f"Avaliacao aberta (por atributo): {label}")
                            return True
                        except Exception:  # noqa: BLE001
                            continue

                # Estrategia 2: ultimo link da linha (comum no SGE)
                links = row.locator("a")
                if links.count() > 0:
                    links.last.click(timeout=ACTION_TIMEOUT_MS)
                    page.wait_for_timeout(200)
                    _log(logger, f"Avaliacao aberta (ultimo link): {label}")
                    _learning_store.registrar_sucesso("abrir_icone_avaliacao", {"metodo": "ultimo_link", "label": label})
                    return True

                # Estrategia 3: ultimo input[type='image']
                imgs = row.locator("input[type='image']")
                if imgs.count() > 0:
                    imgs.last.click(timeout=ACTION_TIMEOUT_MS)
                    page.wait_for_timeout(200)
                    return True

                # Estrategia 4: penultimo link da linha (se o ultimo for navegacao)
                if links.count() > 1:
                    links.nth(links.count() - 2).click(timeout=ACTION_TIMEOUT_MS)
                    page.wait_for_timeout(200)
                    _log(logger, f"Avaliacao aberta (penultimo link): {label}")
                    return True
            except Exception:  # noqa: BLE001
                continue

    # Fallback: procura a linha correta por texto e tenta achar o icone dentro dela
    _log(logger, "Tentando fallback para abrir avaliacao (busca por texto)...")
    for scope in _iter_scopes(page):
        all_rows = scope.locator("tr")
        total_rows = all_rows.count()
        for idx_row in range(total_rows):
            row = all_rows.nth(idx_row)
            try:
                row_text = _normalize(row.inner_text(timeout=400))
            except Exception:  # noqa: BLE001
                continue
            if turno_norm and turno_norm not in row_text:
                continue
            if turma_num and f"turma {turma_num}" not in row_text:
                continue
            if trimestre_num and f"{trimestre_num}o" not in row_text:
                continue
            for palavras in ["Avaliacao", "Avaliação", "Notas", "Lancar", "Lançar"]:
                try:
                    icone = row.locator(f"img[alt*='{palavras}' i], img[title*='{palavras}' i], button:has-text('{palavras}'), a:has-text('{palavras}')")
                    icount = icone.count()
                    if icount == 0:
                        continue
                    for idx_ic in range(icount):
                        ic = icone.nth(idx_ic)
                        try:
                            alt_ic = (ic.get_attribute("alt") or "").lower()
                            title_ic = (ic.get_attribute("title") or "").lower()
                        except Exception:
                            alt_ic = title_ic = ""
                        texto_ic = f"{alt_ic} {title_ic}"
                        if "agenda" in texto_ic or "adaptação" in texto_ic or "adapt" in texto_ic:
                            continue
                        ic.click(timeout=ACTION_TIMEOUT_MS)
                        page.wait_for_timeout(200)
                        if _is_wrong_assessment_page(page):
                            _log(logger, f"Icone errado via fallback (adaptacao), tentando proximo...")
                            continue
                        _log(logger, f"Avaliacao aberta via fallback: '{palavras}'")
                        _learning_store.registrar_sucesso("abrir_icone_avaliacao", {"metodo": "fallback_texto", "palavras": palavras})
                        return True
                except Exception:  # noqa: BLE001
                    continue
            try:
                links = row.locator("a")
                if links.count() > 0:
                    links.last.click(timeout=ACTION_TIMEOUT_MS)
                    page.wait_for_timeout(200)
                    _log(logger, f"Avaliacao aberta via fallback (ultimo link da linha)")
                    _learning_store.registrar_sucesso("abrir_icone_avaliacao", {"metodo": "fallback_ultimo_link"})
                    return True
            except Exception:  # noqa: BLE001
                continue

    _capture_stage_debug(page, stage="assessment_icon_not_found", logger=logger)
    # Salva screenshot mesmo sem DEBUG_LOGIN para diagnostico
    try:
        debug_dir = "artifacts/sge-login"
        os.makedirs(debug_dir, exist_ok=True)
        page.screenshot(path=os.path.join(debug_dir, "assessment_icon_not_found.png"), full_page=True)
        with open(os.path.join(debug_dir, "assessment_icon_not_found_url.txt"), "w") as f:
            f.write(f"url={page.url}\n")
            f.write(f"title={page.title()}\n")
    except Exception:  # noqa: BLE001
        pass
    _log(logger, "Aviso: nao foi possivel abrir icone de avaliacao pela linha da turma.")
    _learning_store.registrar_falha("abrir_icone_avaliacao", {"motivo": "icone_nao_encontrado"})
    return False


def _is_student_grid_visible(page) -> bool:
    for scope in _iter_scopes(page):
        try:
            if scope.get_by_text("Nome Estudante", exact=False).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _extract_date_from_gridagenda_row(page, matched_element) -> str:
    """Extrai a data de avaliacao do GRIDAGENDA a partir do elemento clicado (link/td).

    Procura o <tr> pai e busca o input hidden _AVALIACAOPROFDTSTR_ ou um <td>
    com data no formato DD/MM/AA.
    Retorna a data como string (ex.: '29/06/2026') ou string vazia.
    """
    try:
        row = matched_element.locator("xpath=ancestor::tr[1]")
        if row.count() == 0:
            return ""

        # Estrategia 1: input hidden _AVALIACAOPROFDTSTR_NNNN
        date_input = row.locator("input[name*='_AVALIACAOPROFDTSTR_']")
        if date_input.count() > 0:
            raw = (date_input.first.input_value(timeout=300) or "").strip()
            if raw and not raw.startswith("-"):
                return _normalize_sge_date(raw)

        # Estrategia 2: percorre todos os <td> e busca padrao de data
        tds = row.locator("td")
        for i in range(tds.count()):
            try:
                texto = (tds.nth(i).inner_text(timeout=200) or "").strip()
                if re.match(r"\d{2}/\d{2}/\d{2,4}$", texto):
                    return _normalize_sge_date(texto)
            except Exception:
                continue

        # Estrategia 3: JS para buscar qualquer input com data na row
        js_date = row.evaluate("""
            (tr) => {
                const inputs = tr.querySelectorAll('input');
                for (const inp of inputs) {
                    const name = (inp.getAttribute('name') || '').toLowerCase();
                    if (name.includes('avaliacaoprofdtstr') || name.includes('_dtstr_')) {
                        return (inp.value || '').trim();
                    }
                }
                const tds = tr.querySelectorAll('td');
                for (const td of tds) {
                    const txt = (td.textContent || '').trim();
                    if (/^\\d{2}\\/\\d{2}\\/\\d{2,4}$/.test(txt)) {
                        return txt;
                    }
                }
                return '';
            }
        """)
        if js_date:
            return _normalize_sge_date(js_date)

    except Exception:
        pass
    return ""


def _normalize_sge_date(raw: str) -> str:
    """Normaliza data do SGE (DD/MM/AA ou DD/MM/AAAA) para DD/MM/AAAA."""
    raw = (raw or "").strip()
    if not raw or raw.startswith("-"):
        return ""
    m = re.match(r"(\d{2})/(\d{2})/(\d{2,4})", raw)
    if not m:
        return ""
    dia, mes, ano = m.group(1), m.group(2), m.group(3)
    if len(ano) == 2:
        ano_int = int(ano)
        ano = f"20{ano}" if ano_int <= 50 else f"19{ano}"
    return f"{dia}/{mes}/{ano}"


def _dates_match(sge_date: str, notion_date: str) -> bool:
    """Compara data do SGE (DD/MM/AAAA) com data do Notion (YYYY-MM-DD ou DD/MM/AAAA).

    Retorna True se as datas representam o mesmo dia.
    Retorna True se qualquer uma estiver vazia (sem validacao).
    """
    if not sge_date or not notion_date:
        return True

    sge_dt = _parse_date(sge_date)
    notion_dt = _parse_date(notion_date)

    if sge_dt is None or notion_dt is None:
        return True

    return sge_dt.date() == notion_dt.date()


def _activity_match(target: str, link_text: str) -> bool:
    """Verifica se o texto do link corresponde a atividade desejada."""
    t = _normalize(target)
    l = _normalize(link_text)
    if not t or not l:
        return False
    if t in l or l in t:
        return True
    tl = _normalize_loose(target)
    ll = _normalize_loose(link_text)
    if tl in ll or ll in tl:
        return True

    def _strip_trailing_num(s: str) -> str:
        return re.sub(r"\s+\d+\s*$", "", s).strip()

    def _collapse_hyphens(s: str) -> str:
        return re.sub(r"\s*[-–—]\s*", " - ", s)

    t_stripped = _strip_trailing_num(_collapse_hyphens(t))
    l_stripped = _strip_trailing_num(_collapse_hyphens(l))
    if t_stripped and l_stripped and (t_stripped in l_stripped or l_stripped in t_stripped):
        return True
    t_stripped_loose = _strip_trailing_num(tl)
    l_stripped_loose = _strip_trailing_num(ll)
    if t_stripped_loose and l_stripped_loose and (
        t_stripped_loose in l_stripped_loose or l_stripped_loose in t_stripped_loose
    ):
        return True
    t_parts = re.split(r"[\s]*[-–—]\s*", tl, maxsplit=1)
    l_parts = re.split(r"[\s]*[-–—]\s*", ll, maxsplit=1)
    if len(t_parts) == 2 and len(l_parts) == 2:
        t_num, t_txt = t_parts[0].strip(), t_parts[1].strip()
        l_num, l_txt = l_parts[0].strip(), l_parts[1].strip()
        if t_num == l_num and (t_txt in l_txt or l_txt in t_txt):
            return True
        if t_num == l_txt and l_num == t_txt:
            return True
    t_num_m = re.match(r"^(\d+)\s*", tl)
    l_num_m = re.match(r"^(\d+)\s*", ll)
    if t_num_m and l_num_m and t_num_m.group(1) == l_num_m.group(1):
        t_txt = tl[t_num_m.end():].strip()
        l_txt = ll[l_num_m.end():].strip()
        if t_txt and l_txt and (t_txt in l_txt or l_txt in t_txt):
            return True
    return False


def _find_gridagenda_scope(page, timeout_ms: int = 9000):
    """Retorna o scope (pagina principal ou iframe) onde table#GRIDAGENDA esta presente."""
    for scope in _iter_scopes(page):
        try:
            scope.wait_for_selector("table#GRIDAGENDA", timeout=timeout_ms)
            return scope
        except Exception:  # noqa: BLE001
            continue
    return None


def _grade_entry_indicators_visible(page) -> bool:
    """True se algum sinal da grade de lancamento estiver visivel em qualquer frame."""
    for scope in _iter_scopes(page):
        try:
            if scope.locator("table#GRIDAGENDA").count() > 0:
                return True
            if scope.locator("input[name*='_POSICAO_0001']").count() > 0:
                return True
            if scope.locator("input[name='_AVALIACAOPROFDT']").count() > 0:
                return True
            if scope.locator("#span__AVALIACAO").count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _select_activity(page, atividade: str, logger: Optional[LogFn]) -> Tuple[bool, str, int]:
    _log(logger, f"Selecionando avaliacao: {atividade}")

    max_grid_retries = 2
    agenda_scope = None
    for grid_attempt in range(1, max_grid_retries + 1):
        # GRIDAGENDA pode estar na pagina principal OU em um iframe do portal.
        agenda_scope = _find_gridagenda_scope(page, timeout_ms=9000)
        if agenda_scope is not None:
            _log(logger, "GRIDAGENDA visivel.")
            break
        _log(logger, f"GRIDAGENDA nao encontrado em 9s (tentativa {grid_attempt}/{max_grid_retries}).")

        # Pre-check: a atividade pode ja estar aberta (grid de lancamento na tela).
        for scope in _iter_scopes(page):
            try:
                span_atual = scope.locator("#span__AVALIACAO")
                if span_atual.count() > 0:
                    texto_atual = (span_atual.first.inner_text(timeout=2000) or "").strip()
                    if texto_atual and _activity_match(atividade, texto_atual):
                        _log(logger, f"[PRE-CHECK] Atividade '{atividade}' ja esta aberta.")
                        posicao = 0
                        try:
                            posicao_input = scope.locator("input[name*='_POSICAO_0001']")
                            if posicao_input.count() > 0:
                                posicao = int(posicao_input.first.input_value(timeout=500) or "0")
                        except Exception:
                            pass
                        data_sge = ""
                        try:
                            dt_input = scope.locator("input[name='_AVALIACAOPROFDT']")
                            if dt_input.count() > 0:
                                data_sge = _normalize_sge_date(dt_input.first.input_value(timeout=500) or "")
                        except Exception:
                            pass
                        return True, data_sge, posicao
            except Exception:
                pass

        if grid_attempt < max_grid_retries:
            _log(logger, "Recarregando pagina para tentar encontrar GRIDAGENDA...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(1500)
            except Exception:
                pass

    def _esperar_grade_lancamento() -> bool:
        try:
            page.wait_for_url("**/hdiscturalunonota.aspx**", timeout=6000)
            return True
        except Exception:
            pass
        deadline = time.time() + 8
        while time.time() < deadline:
            if _grade_entry_indicators_visible(page):
                return True
            page.wait_for_timeout(250)
        return False

    if agenda_scope is None:
        agenda_scope = _find_gridagenda_scope(page, timeout_ms=3000)

    # OTIMIZACAO: Uma unica avaliacao JS para extrair TODOS os elementos clicaveis da GRIDAGENDA
    agenda = None
    if agenda_scope is not None:
        agenda = agenda_scope.locator("table#GRIDAGENDA")
    if agenda is not None and agenda.count() > 0:
        js_elements = agenda.evaluate("""
            (table) => {
                const out = [];
                let posicao = 0;
                // Links
                for (const a of table.querySelectorAll('a')) {
                    const text = (a.textContent || '').trim();
                    if (text) {
                        posicao++;
                        out.push({tag: 'a', text, posicao, rowIdx: a.closest('tr')?.rowIndex ?? -1});
                    }
                }
                // Clickable tds
                for (const td of table.querySelectorAll('td[onclick], td[style*="cursor:pointer"], td[style*="cursor: pointer"]')) {
                    const text = (td.textContent || '').trim();
                    if (text) {
                        posicao++;
                        out.push({tag: 'td', text, posicao, rowIdx: td.closest('tr')?.rowIndex ?? -1});
                    }
                }
                // Inputs/buttons
                for (const el of table.querySelectorAll('input[type="image"], input[type="submit"], button')) {
                    const text = (el.value || el.alt || el.title || '').trim();
                    if (text) {
                        posicao++;
                        out.push({tag: el.tagName.toLowerCase(), text, posicao, rowIdx: el.closest('tr')?.rowIndex ?? -1});
                    }
                }
                return out;
            }
        """)
        _log(logger, f"[GRID-SCAN] {len(js_elements)} elemento(s) encontrados na GRIDAGENDA via JS.")

        # Matching em Python (rapido, sem chamadas ao DOM)
        for item in js_elements:
            texto = item["text"]
            if not texto:
                continue
            _log(logger, f"[GRID-SCAN] {item['tag']}[pos={item['posicao']}] texto={texto!r}")
            if _activity_match(atividade, texto):
                _log(logger, f"[GRID-SCAN] MATCH encontrado: {texto!r}")
                # Clique direto no elemento por seletor
                posicao = item["posicao"]
                selector = None
                if item["tag"] == "a":
                    selector = f"table#GRIDAGENDA tr:nth-child({item['rowIdx'] + 1}) a"
                elif item["tag"] == "td":
                    selector = f"table#GRIDAGENDA tr:nth-child({item['rowIdx'] + 1}) td[onclick], table#GRIDAGENDA tr:nth-child({item['rowIdx'] + 1}) td[style*='cursor:pointer']"
                else:
                    selector = f"table#GRIDAGENDA input[type='image'], table#GRIDAGENDA input[type='submit'], table#GRIDAGENDA button"

                if selector:
                    clicked = False
                    try:
                        loc = agenda_scope.locator(selector).first
                        if loc.count() > 0:
                            loc.click(timeout=ACTION_TIMEOUT_MS)
                            clicked = True
                            page.wait_for_timeout(250)
                            if _esperar_grade_lancamento():
                                _log(logger, f"[GRID-SCAN] Posicao: {posicao} → Status lancamento {posicao}")
                                return True, "", posicao
                    except Exception:
                        pass
                    # Fallback: clique via JS
                    if not clicked:
                        try:
                            el_js = agenda_scope.locator(selector).first
                            if el_js.count() > 0:
                                el_js.evaluate("el => el.click()")
                                page.wait_for_timeout(300)
                                if _esperar_grade_lancamento():
                                    _log(logger, f"[GRID-SCAN-JS] Posicao: {posicao} → Status lancamento {posicao}")
                                    return True, "", posicao
                        except Exception:
                            pass

                # Fallback: clicar por texto
                if _click_text_any_scope(page, texto):
                    page.wait_for_timeout(250)
                    if _esperar_grade_lancamento():
                        return True, "", posicao

    # Fallback: tentar clicar no texto da atividade diretamente
    if _click_text_any_scope(page, atividade):
        page.wait_for_timeout(250)
        if _esperar_grade_lancamento():
            return True, "", 0

    if _normalize(atividade) == "avaliacao" and _is_student_grid_visible(page):
        return True, "", 0

    _capture_stage_debug(page, stage="activity_not_found", logger=logger)
    try:
        debug_dir = "artifacts/sge-login"
        os.makedirs(debug_dir, exist_ok=True)
        page.screenshot(path=os.path.join(debug_dir, "activity_not_found.png"), full_page=True)
        with open(os.path.join(debug_dir, "activity_not_found_url.txt"), "w", encoding="utf-8") as f:
            f.write(f"url={page.url}\n")
            f.write(f"title={page.title()}\n")
            for idx, frame in enumerate(page.frames):
                f.write(f"frame[{idx}] name={frame.name!r} url={frame.url}\n")
    except Exception:  # noqa: BLE001
        pass
    _log(logger, f"Aviso: avaliacao nao encontrada na tela: {atividade}")
    return False, "", 0


def _find_student_row(page, aluno: str):
    alvo_norm = _normalize(aluno)
    if not alvo_norm:
        return None

    for scope in _iter_scopes(page):
        # Tentativa rapida por texto exato.
        direct = scope.locator("tr", has_text=aluno)
        if direct.count() > 0:
            return direct.first

        # Fallback tolerante a acentos/case/espacos.
        rows = scope.locator("tr")
        total_rows = rows.count()
        for idx in range(total_rows):
            row = rows.nth(idx)
            try:
                texto_row = row.inner_text(timeout=400)
            except Exception:  # noqa: BLE001
                continue
            row_norm = _normalize(texto_row)
            if alvo_norm in row_norm:
                return row
    return None


def _go_to_first_grade_page(page) -> bool:
    moved = _click_any_selector_any_scope(
        page,
        [
            "input[type='submit'][value='|<']",
            "input[type='button'][value='|<']",
            "button:has-text('|<')",
            "a:has-text('|<')",
        ],
    )
    if moved:
        _clear_slots_cache()
        page.wait_for_timeout(200)
    return moved


def _go_to_next_grade_page(page) -> bool:
    moved = _click_any_selector_any_scope(
        page,
        [
            "input[type='submit'][value='>>']",
            "input[type='button'][value='>>']",
            "button:has-text('>>')",
            "a:has-text('>>')",
            "input[type='submit'][value='>']",
            "input[type='button'][value='>']",
            "button:text-is('>')",
            "a:text-is('>')",
            "input[type='submit'][value*='Prox' i]",
            "input[type='button'][value*='Prox' i]",
            "input[type='submit'][name*='PROX' i]",
            "input[type='button'][name*='PROX' i]",
            "a[title*='Próx' i]",
            "a[title*='Prox' i]",
            "a[aria-label*='Próx' i]",
            "a[aria-label*='Prox' i]",
            "a:has-text('Próximo')",
            "button:has-text('Próximo')",
            "a:has-text('Seguinte')",
            "button:has-text('Seguinte')",
        ],
    )
    if moved:
        _clear_slots_cache()
        page.wait_for_timeout(200)
    return moved


def _find_student_row_with_pagination(page, aluno: str, max_pages: int = 5):
    row = _find_student_row(page, aluno)
    if row is not None:
        return row

    # Cache de posicao de aluno: tentar ultima pagina conhecida primeiro
    aluno_norm = _normalize_loose(aluno)
    last_known_page = _student_page_cache.get(aluno_norm, 0)
    if last_known_page > 0:
        # Ir para pagina conhecida primeiro
        _go_to_first_grade_page(page)
        for _ in range(last_known_page):
            if not _go_to_next_grade_page(page):
                break
        row = _find_student_row(page, aluno)
        if row is not None:
            _student_page_cache[aluno_norm] = last_known_page
            return row

    _go_to_first_grade_page(page)
    row = _find_student_row(page, aluno)
    if row is not None:
        _student_page_cache[aluno_norm] = 0
        return row

    for page_num in range(1, max_pages):
        if not _go_to_next_grade_page(page):
            break
        row = _find_student_row(page, aluno)
        if row is not None:
            _student_page_cache[aluno_norm] = page_num
            return row

    return None


# Cache de posicao de aluno por pagina (evita busca repetida)
_student_page_cache: Dict[str, int] = {}

# Casamento progressivo por primeiro nome (busca pelo 1o nome e desambigua com
# 2o/3o nome). Habilitado por executar_lancamento(buscar_por_primeiro_nome=True).
_PRIMEIRO_NOME_MATCH_ENABLED: bool = False


def _collect_student_slots(scope) -> List[Dict[str, str]]:
    """Coleta os 'slots' de alunos da grade (suffix de 4 digitos + nome).

    Cadeia de fallback (PONTO 3.1):
      1. Override local salvo pelo usuario via 'Remodelar' (seletor custom).
      2. Seletores CSS padrao do SGE (_ALUMATNOM_<suffix>).
      3. Varredura JS ampla: qualquer input/span cujo name|id termine em _\d{4}
         e cujo valor pareca um nome (contem letras) — absorve renames como
         _NOMEALUNO_<suffix>, _ALUNO_<suffix>, span__NOME_<suffix>, etc.
    """
    override = _load_estrutura_override()
    override_selector = override.get("slot_selector", "")
    try:
        if override_selector:
            slots = scope.eval_on_selector_all(
                override_selector,
                r"""
                (els) => {
                  const out = [];
                  const seen = new Set();
                  for (const el of els) {
                    const attr = (el.getAttribute('name') || el.getAttribute('id') || '').trim();
                    const m = attr.match(/_(\d{4})$/);
                    if (!m) continue;
                    const suffix = m[1];
                    if (seen.has(suffix)) continue;
                    const raw = (el.value ?? el.textContent ?? '').trim();
                    if (!raw) continue;
                    seen.add(suffix);
                    out.push({ suffix, aluno: raw });
                  }
                  return out;
                }
                """,
            )
            if isinstance(slots, list):
                slots = [s for s in slots if isinstance(s, dict)]
                if slots:
                    return slots
    except Exception:  # noqa: BLE001
        pass

    try:
        slots = scope.eval_on_selector_all(
            "input[name^='_ALUMATNOM_'], span[id^='span__ALUMATNOM_']",
                        r"""
            (els) => {
              const out = [];
              const seen = new Set();
              for (const el of els) {
                const attr = (el.getAttribute('name') || el.getAttribute('id') || '').trim();
                                const m = attr.match(/_ALUMATNOM_(\d{4})$/);
                if (!m) continue;
                const suffix = m[1];
                if (seen.has(suffix)) continue;
                seen.add(suffix);
                const raw = (el.value ?? el.textContent ?? '').trim();
                if (!raw) continue;
                out.push({ suffix, aluno: raw });
              }
              return out;
            }
            """,
        )
        if isinstance(slots, list):
            slots = [s for s in slots if isinstance(s, dict)]
            if slots:
                return slots
    except Exception:  # noqa: BLE001
        pass

    # Fallback amplo: descobre os nomes por atributo alternativo + valor com letras.
    try:
        slots = scope.evaluate(
            r"""
            () => {
              const out = [];
              const seen = new Set();
              const nodes = Array.from(document.querySelectorAll(
                  'input[type="text"], input[type="search"], span, td[valign]'
              ));
              for (const el of nodes) {
                const attr = (el.getAttribute('name') || el.getAttribute('id') || '').trim();
                const m = attr.match(/(?:ALUMATNOM|ALUNO|NOME|NOM|ESTUDANTE|ESTU)[^_]*_(\d{4})$/i);
                if (!m) continue;
                const suffix = m[1];
                if (seen.has(suffix)) continue;
                const raw = (el.value ?? el.textContent ?? '').trim();
                if (!raw) continue;
                if (!/[A-Za-zÀ-ÖØ-öø-ÿ]/.test(raw)) continue;
                seen.add(suffix);
                out.push({ suffix, aluno: raw });
              }
              return out;
            }
            """
        )
        if isinstance(slots, list):
            return [s for s in slots if isinstance(s, dict)]
    except Exception:  # noqa: BLE001
        pass
    return []


def _wait_student_slots(scope, attempts: int = 4, delay_ms: int = 200) -> List[Dict[str, str]]:
    scope_id = id(scope)
    cached = _slots_cache.get(scope_id)
    if cached is not None:
        return cached

    slots = _collect_student_slots(scope)
    if slots:
        _slots_cache[scope_id] = slots
        return slots

    for _ in range(max(0, attempts - 1)):
        try:
            scope.wait_for_timeout(delay_ms)
        except Exception:  # noqa: BLE001
            pass
        slots = _collect_student_slots(scope)
        if slots:
            _slots_cache[scope_id] = slots
            return slots

    return []


def _score_student_candidates(expected: str, slots: List[Dict[str, str]]) -> List[Tuple[float, str]]:
    """Retorna os suffixs ordenados por pontuacao de casamento nome-a-nome.

    Prioriza matches deterministas (_student_name_matches = 2.0) e depois a
    combinacao de ratio difflib + sobreposicao de tokens significativos.
    """
    alvo = _normalize_loose(expected)
    if not alvo:
        return []

    scored: List[Tuple[float, str]] = []
    seen = set()

    for slot in slots:
        suffix = str(slot.get("suffix", "")).strip()
        atual = str(slot.get("aluno", "")).strip()
        if not suffix or not atual:
            continue

        atual_norm = _normalize_loose(atual)
        if not atual_norm:
            continue

        if _student_name_matches(expected, atual):
            score = 2.0
        else:
            overlap = len(set(_name_tokens(alvo)).intersection(_name_tokens(atual_norm)))
            ratio = difflib.SequenceMatcher(None, alvo, atual_norm).ratio()
            score = ratio + (0.04 * overlap)

        if suffix in seen:
            continue
        seen.add(suffix)
        scored.append((score, suffix))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _progressive_name_suffixes(expected: str, slots: List[Dict[str, str]]) -> List[str]:
    """Casamento progressivo por PRIMEIRO NOME, desambiguando com 2o/3o nome.

    Quando a IA le o nome da planilha, o primeiro nome costuma sair correto e o
    sobrenome pode vir corrompido. Esta estrategia procura primeiro pelo primeiro
    nome; se mais de um aluno do portal tiver o mesmo primeiro nome, refina com o
    segundo e, se preciso, o terceiro nome para diferenciar.

    Retorna a lista de suffixs na ordem de prioridade (1 candidato no caso ideal).
    """
    tokens = _name_tokens(_normalize_loose(expected))
    if not tokens:
        return []

    def _match_round(n_round: int) -> List[Dict[str, str]]:
        matched = []
        for slot in slots:
            atual = _name_tokens(_normalize_loose(str(slot.get("aluno", "")).strip()))
            if not atual:
                continue
            if atual[0] != tokens[0]:
                continue
            ok = True
            for i in range(1, n_round):
                if i >= len(atual) or i >= len(tokens) or atual[i] != tokens[i]:
                    ok = False
                    break
            if ok:
                matched.append(slot)
        return matched

    def _suffixes(items: List[Dict[str, str]]) -> List[str]:
        return [str(s.get("suffix", "")).strip() for s in items]

    r1 = _match_round(1)
    if not r1:
        return []
    if len(r1) == 1:
        return _suffixes(r1)

    # Mais de um aluno com o mesmo primeiro nome: refina com 2o/3o nome.
    if len(tokens) >= 2:
        r2 = _match_round(2)
        if len(r2) == 1:
            return _suffixes(r2)
        if len(r2) > 1 and len(tokens) >= 3:
            r3 = _match_round(3)
            if len(r3) == 1:
                return _suffixes(r3)
            if r3:
                return _suffixes(r3)
        if r2:
            return _suffixes(r2)

    # Sem como desambiguar: devolve todos os de primeiro nome igual (ambiguo).
    return _suffixes(r1)


def _names_exactly_equal(a: str, b: str) -> bool:
    na = _normalize_loose(a)
    nb = _normalize_loose(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ca = re.sub(r"[^a-z0-9]", "", na)
    cb = re.sub(r"[^a-z0-9]", "", nb)
    return bool(ca and cb and ca == cb)


def _candidate_suffixes_for_student(expected: str, slots: List[Dict[str, str]]) -> List[str]:
    if not _PRIMEIRO_NOME_MATCH_ENABLED:
        return [suffix for _, suffix in _score_student_candidates(expected, slots)]

    full = _score_student_candidates(expected, slots)
    prog = _progressive_name_suffixes(expected, slots)

    if not prog:
        return [suffix for _, suffix in full]

    # O match EXATO de nome completo vence; caso contrario, o casamento por
    # primeiro nome (progressivo) tem prioridade e os candidatos completos
    # ficam como fallback. NAO se usa o score 2.0 leniente do full aqui, pois
    # ele pode casar um homonimo (mesmo 1o+2o nome, sobrenome diferente).
    top_suffix = full[0][1] if full else ""
    exact_top = any(
        str(slot.get("suffix", "")).strip() == top_suffix
        and _names_exactly_equal(expected, str(slot.get("aluno", "")).strip())
        for slot in slots
    )
    if exact_top:
        return list(dict.fromkeys([suffix for _, suffix in full] + prog))
    return list(dict.fromkeys(prog + [suffix for _, suffix in full]))


def _grade_input_selectors_chain(suffix: str, coluna_sge: str = "") -> List[str]:
    """Cadeia de seletores CSS para o campo de nota do aluno (do mais especifico ao mais amplo).

    Ordem: nome exato -> id exato -> sufixo+coluna -> sufixo+NOTA/AVAL -> apenas sufixo.
    Override local (via 'Remodelar') entra como primeira tentativa.
    """
    chain: List[str] = []
    override = _load_estrutura_override()
    override_selectors = override.get("grade_selectors") or []
    if isinstance(override_selectors, list):
        chain.extend(
            s.replace("{suffix}", suffix)
            for s in override_selectors
            if isinstance(s, str) and s.strip()
        )

    if coluna_sge:
        chain.extend([
            f"input[name='_{coluna_sge}_{suffix}']",
            f"input[id='_{coluna_sge}_{suffix}']",
            f"input[name$='_{coluna_sge}_{suffix}']",
            f"input[id$='_{coluna_sge}_{suffix}']",
            f"input[name*='_{suffix}'][name*='{coluna_sge}'], input[id*='_{suffix}'][id*='{coluna_sge}']",
        ])
    else:
        chain.extend([
            f"input[name='_NOTA_{suffix}']",
            f"input[id='_NOTA_{suffix}']",
            f"input[name$='_{suffix}'][name*='NOTA' i]",
            f"input[id$='_{suffix}'][id*='NOTA' i]",
            f"input[name$='_{suffix}'][name*='AVAL' i]",
            f"input[id$='_{suffix}'][id*='AVAL' i]",
            f"input[name$='_{suffix}'], input[id$='_{suffix}']",
        ])
    return chain


def _discover_grade_input_attr(scope, suffix: str, coluna_sge: str = "") -> str:
    """Descobre o atributo real (name|id) do input de nota via varredura JS ampla.

    Retorna algo como 'name=_N1S_0001' ou 'id=_NOTA_0001'; vazio se nao achar.
    Absorve renames do SGE: qualquer input cujo name|id contenha o suffix (+ coluna).
    """
    js = """
    ({suffix, coluna}) => {
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        for (const el of candidates) {
            const name = (el.getAttribute('name') || '').trim();
            const id = (el.getAttribute('id') || '').trim();
            const attrs = name + ' ' + id;
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.toLowerCase().includes('_' + coluna.toLowerCase() + '_')) continue;
            if (el.disabled || el.readOnly) continue;
            return (name ? 'name' : 'id') + '=' + (name || id);
        }
        return '';
    }
    """
    try:
        return str(scope.evaluate(js, {"suffix": suffix, "coluna": coluna_sge}))
    except Exception:  # noqa: BLE001
        return ""


def _locate_grade_input_by_row_text(scope, aluno: str, coluna_sge: str = "") -> Optional[Any]:
    """Localiza o campo de nota ancorando na LINHA que contem o texto do aluno.

    Fallback por texto/relacao (PONTO 3.1): quando o atributo do campo mudou mas o
    nome do aluno continua na grade, acha o <tr> que contem o nome e procura o input
    da coluna dentro dele. Sem coluna definida, so usa o campo se a linha tiver
    EXATAMENTE um input numerico/texto visivel (nao arrisca coluna errada).
    """
    alvo_norm = _normalize(aluno)
    if not alvo_norm:
        return None
    try:
        for hit in scope.get_by_text(aluno, exact=False):
            try:
                row = hit.locator("xpath=ancestor::tr[1]")
                if row.count() == 0:
                    continue
                if coluna_sge:
                    cand = row.locator(
                        f"input[type='text'][name*='_{coluna_sge}_'], input[type='number'][name*='_{coluna_sge}_'], "
                        f"input[type='text'][id*='_{coluna_sge}_'], input[type='number'][id*='_{coluna_sge}_']"
                    )
                else:
                    cand = row.locator("input[type='text']:visible, input[type='number']:visible")
                if cand.count() > 0 and (coluna_sge or cand.count() == 1):
                    return cand.first
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _locate_grade_input(scope, suffix: str, coluna_sge: str = "", aluno: str = "") -> Optional[Any]:
    """Localiza o input de nota do aluno com cadeia de fallback completa (PONTO 3.1).

    1. CSS: nome exato -> id exato -> sufixo+coluna -> NOTA/AVAL -> so sufixo.
    2. Atributo real descoberto via JS (absorve rename do name/id).
    3. Ancoragem por texto na linha do aluno (coluna definida ou linha com 1 campo).

    Retorna Playwright Locator ou None.
    """
    for sel in _grade_input_selectors_chain(suffix, coluna_sge):
        try:
            loc = scope.locator(sel)
            if loc.count() > 0:
                return loc
        except Exception:  # noqa: BLE001
            continue
    attr = _discover_grade_input_attr(scope, suffix, coluna_sge)
    if attr:
        kind, _, val = attr.partition("=")
        if kind and val:
            try:
                loc = scope.locator(f"input[{kind}='{val}']")
                if loc.count() > 0:
                    return loc
            except Exception:  # noqa: BLE001
                pass
    if aluno:
        return _locate_grade_input_by_row_text(scope, aluno, coluna_sge)
    return None


def _try_fill_grade_by_suffix(scope, suffix: str, nota_texto: str, coluna_sge: str = "") -> bool:
    field = _locate_grade_input(scope, suffix, coluna_sge)
    if field is not None:
        try:
            total = min(field.count(), 6)
            for idx in range(total):
                target = field.nth(idx)
                try:
                    if target.is_disabled() or (target.get_attribute("readonly") is not None):
                        continue
                    target.click(timeout=ACTION_TIMEOUT_MS)
                    target.fill(nota_texto, timeout=ACTION_TIMEOUT_MS)
                    target.dispatch_event("input")
                    target.dispatch_event("change")
                    return True
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
    return bool(
        scope.evaluate(
            """
            ({ suffix, nota, coluna }) => {
              let selectors;
              if (coluna) {
                selectors = [
                  `input[name='_${coluna}_${suffix}']`,
                  `input[id='_${coluna}_${suffix}']`,
                ];
              } else {
                selectors = [
                  `input[name='_NOTA_${suffix}']`,
                  `input[id='_NOTA_${suffix}']`,
                  `input[name$='_${suffix}'][name*='NOTA' i]`,
                  `input[id$='_${suffix}'][id*='NOTA' i]`,
                  `input[name$='_${suffix}'][name*='AVAL' i]`,
                  `input[id$='_${suffix}'][id*='AVAL' i]`,
                ];
              }

              for (const sel of selectors) {
                const all = Array.from(document.querySelectorAll(sel));
                for (const el of all) {
                  if (!el || el.disabled || el.readOnly) continue;
                  el.value = nota;
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  return true;
                }
              }
              return false;
            }
            """,
            {"suffix": suffix, "nota": nota_texto, "coluna": coluna_sge},
        )
    )


def _try_fill_any_numeric_input_for_suffix(scope, suffix: str, nota_texto: str, coluna_sge: str = "") -> bool:
        # Fallback amplo: alguns layouts do SGE nao usam prefixo NOTA/AVAL no campo.
        js = """
        ({ suffix, nota, coluna }) => {
            const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
            const isVisible = (el) => {
                const st = window.getComputedStyle(el);
                return st && st.visibility !== 'hidden' && st.display !== 'none';
            };

            for (const el of candidates) {
                const name = (el.getAttribute('name') || '').trim();
                const id = (el.getAttribute('id') || '').trim();
                const attrs = `${name} ${id}`;
                if (!attrs.includes(`_${suffix}`)) continue;
                if (coluna && !attrs.includes(`_${coluna}_`)) continue;
                if (el.disabled || el.readOnly) continue;
                if (!isVisible(el)) continue;

                el.value = nota;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        }
        """

        try:
                return bool(scope.evaluate(js, {"suffix": suffix, "nota": nota_texto, "coluna": coluna_sge}))
        except Exception:  # noqa: BLE001
                return False


def _is_any_numeric_input_for_suffix_already_set(scope, suffix: str, nota_texto: str, coluna_sge: str = "") -> bool:
        js = """
        ({ suffix, coluna }) => {
            const out = [];
            const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
            for (const el of candidates) {
                const name = (el.getAttribute('name') || '').trim();
                const id = (el.getAttribute('id') || '').trim();
                const attrs = `${name} ${id}`;
                if (!attrs.includes(`_${suffix}`)) continue;
                if (coluna && !attrs.includes(`_${coluna}_`)) continue;
                out.push((el.value || '').trim());
            }
            return out;
        }
        """

        try:
                values = scope.evaluate(js, {"suffix": suffix, "coluna": coluna_sge})
        except Exception:  # noqa: BLE001
                return False

        if not isinstance(values, list):
                return False

        for raw in values:
                if _grade_value_matches_target(str(raw or ""), nota_texto):
                        return True
        return False


def _grade_value_matches_target(raw_value: str, nota_texto: str) -> bool:
    atual = (raw_value or "").strip().replace(" ", "")
    alvo = (nota_texto or "").strip().replace(" ", "")
    if not atual or not alvo:
        return False
    if atual == alvo:
        return True

    atual_norm = atual.replace(",", ".")
    alvo_norm = alvo.replace(",", ".")
    try:
        return abs(float(atual_norm) - float(alvo_norm)) < 1e-9
    except Exception:  # noqa: BLE001
        return False


def _classificar_leitura(existing: Optional[str], nota_esperada_texto: str) -> str:
    """Classifica uma releitura da celula de nota do SGE.

    Retorna 'ok' (valor confere com o esperado), 'divergente' (campo tem valor
    diferente do esperado) ou 'vazio' (campo sem valor / nao relido).
    """
    if existing is None:
        return "vazio"
    if _grade_value_matches_target(existing, nota_esperada_texto):
        return "ok"
    return "divergente"


def _verify_fill_just_made(page, aluno: str, nota_texto: str, logger: Optional[LogFn], coluna_sge: str = "", filled_suffix: str = "") -> bool:
    """Re-le os inputs do aluno apos o preenchimento e confere se o valor gravou.

    VERIFICACAO RIGIDA (ancora de linha): so retorna True quando o campo relido
    (a) esta dentro da LINHA que contem o nome do aluno e (b) tem exatamente UM
    campo do suffix na linha (sem ambiguidade de coluna) e (c) o valor bate com o
    esperado. Notas zero/0,0 NAO sao auto-confirmadas: precisam passar pela mesma
    leitura ancorada, porque 0,0 num campo errado nao pode ser tratado como sucesso.
    """
    def _try_verify(cols: str) -> bool:
        if filled_suffix:
            for scope in _iter_scopes(page):
                res = _read_grade_value_anchored_js(scope, aluno, filled_suffix, cols)
                if res is None:
                    continue
                val, count = res
                if count != 1:
                    continue
                if val and _grade_value_matches_target(val, nota_texto):
                    return True
            return False
        for scope in _iter_scopes(page):
            slots = _wait_student_slots(scope)
            if not slots:
                continue
            suffixes = _candidate_suffixes_for_student(aluno, slots)
            for suffix in suffixes[:3]:
                res = _read_grade_value_anchored_js(scope, aluno, suffix, cols)
                if res is None:
                    continue
                val, count = res
                if count != 1:
                    continue
                if val and _grade_value_matches_target(val, nota_texto):
                    return True
        return False

    if _try_verify(coluna_sge):
        return True
    return False


def _is_grade_already_set_for_suffix(scope, suffix: str, nota_texto: str, coluna_sge: str = "") -> bool:
    """Verifica se o campo de nota ja esta preenchido com o valor desejado (via JS, 1 round-trip)."""
    js = """
    ({suffix, nota, coluna}) => {
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        for (const el of candidates) {
            const name = (el.getAttribute('name') || '').trim();
            const id = (el.getAttribute('id') || '').trim();
            const attrs = (name + ' ' + id).toLowerCase();
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.includes('_' + coluna.toLowerCase() + '_')) continue;
            const val = (el.value || '').trim().replace(',', '.');
            const target = nota.trim().replace(',', '.');
            if (val === target) return true;
        }
        return false;
    }
    """
    try:
        return bool(scope.evaluate(js, {"suffix": suffix, "nota": nota_texto, "coluna": coluna_sge}))
    except Exception:  # noqa: BLE001
        return False


def _clear_slots_cache():
    """Limpa cache de slots apos navegacao de pagina."""
    _slots_cache.clear()


def _try_fill_and_verify_js(scope, suffix: str, nota_texto: str, coluna_sge: str = "", aluno: str = "") -> str:
    """Tenta preencher o campo de nota e retorna o resultado (1 round-trip JS).

    Com 'aluno' informado, so preenche o campo cuja LINHA contem o nome do aluno
    (ancora de linha): evita gravar a nota na coluna/linha de OUTRO aluno quando
    o mesmo suffix aparece em varios campos da pagina. Sem a ancora, 'not_found'.

    Retorna:
      'filled'    - campo preenchido com sucesso
      'already'   - campo ja continha o valor desejado
      'not_found' - campo nao encontrado (ou nao ancorado na linha do aluno)
      'error'     - erro ao preencher
    """
    js = """
    ({suffix, nota, coluna, alvo}) => {
        const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
        const tokenize = s => Array.from(new Set((norm(s).match(/[a-z0-9]{2,}/g) || [])));
        const alvoTokens = alvo ? tokenize(alvo) : [];
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        const matches = [];
        for (const el of candidates) {
            const name = (el.getAttribute('name') || '').trim();
            const id = (el.getAttribute('id') || '').trim();
            const attrs = norm(name + ' ' + id);
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.includes('_' + norm(coluna) + '_')) continue;
            let anchored = !alvoTokens.length;
            if (!anchored) {
                const row = el.closest('tr');
                if (row) {
                    const rowTokens = tokenize(row.innerText || '');
                    let hit = 0;
                    for (const t of alvoTokens) { if (rowTokens.includes(t)) hit += 1; }
                    anchored = hit >= Math.max(1, Math.ceil(alvoTokens.length * 0.6));
                }
            }
            if (!anchored) continue;
            matches.push({el: el, id: id, name: name});
        }
        const fill = (el) => {
            const currentVal = (el.value || '').trim().replace(',', '.');
            const target = nota.trim().replace(',', '.');
            if (currentVal === target) return 'already';
            try {
                el.value = nota;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                const updatePanel = el.closest('form');
                if (updatePanel && typeof __doPostBack === 'function') {
                    try { __doPostBack('', ''); } catch(e) {}
                }
                if (el.getAttribute('onchange')) {
                    try { el.getAttribute('onchange').call(el); } catch(e) {}
                }
                return 'filled';
            } catch (e) { return 'error'; }
        };
        if (!matches.length) return 'not_found';
        const byId = matches.find(m => m.id && norm(m.id).includes('_' + suffix));
        if (byId) return fill(byId.el);
        const byName = matches.find(m => m.name);
        if (byName) return fill(byName.el);
        return 'not_found';
    }
    """
    try:
        return str(scope.evaluate(js, {"suffix": suffix, "nota": nota_texto, "coluna": coluna_sge, "alvo": aluno}))
    except Exception:  # noqa: BLE001
        return "error"


def _verify_fill_js(scope, suffix: str, nota_texto: str, coluna_sge: str = "") -> bool:
    """Verifica se o campo de nota foi preenchido corretamente (1 round-trip JS)."""
    js = """
    ({suffix, nota, coluna}) => {
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        for (const el of candidates) {
            const name = (el.getAttribute('name') || '').trim();
            const id = (el.getAttribute('id') || '').trim();
            const attrs = (name + ' ' + id).toLowerCase();
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.includes('_' + coluna.toLowerCase() + '_')) continue;
            const val = (el.value || '').trim().replace(',', '.');
            const target = nota.trim().replace(',', '.');
            if (val === target) return true;
        }
        return false;
    }
    """
    try:
        return bool(scope.evaluate(js, {"suffix": suffix, "nota": nota_texto, "coluna": coluna_sge}))
    except Exception:  # noqa: BLE001
        return False


def _try_fill_grade_for_student_on_current_page(page, aluno: str, nota_texto: str, coluna_sge: str = "") -> str:
    """Tenta preencher a nota do aluno. Retorna o suffix preenchido ou '' se falhou."""
    if not _normalize_loose(aluno):
        return ""

    for scope in _iter_scopes(page):
        slots = _wait_student_slots(scope)
        if not slots:
            continue

        suffixes = _candidate_suffixes_for_student(aluno, slots)
        for suffix in suffixes:
            result = _try_fill_and_verify_js(scope, suffix, nota_texto, coluna_sge=coluna_sge, aluno=aluno)
            if result in ("filled", "already"):
                return suffix

    # NAO usa fallback SEM filtro de coluna quando coluna_sge esta definida:
    # escrever sem o filtro pode lancar a nota na coluna de OUTRA avaliacao
    # exibida na mesma pagina (mesmo problema do falso [SGE-JA]).
    return ""


def _fill_grade_for_student_by_indexed_inputs(page, aluno: str, nota_texto: str, max_pages: int = 5, coluna_sge: str = "") -> str:
    """Tenta preencher a nota. Retorna o suffix preenchido ou '' se falhou."""
    suffix = _try_fill_grade_for_student_on_current_page(page, aluno, nota_texto, coluna_sge=coluna_sge)
    if suffix:
        return suffix

    _go_to_first_grade_page(page)
    suffix = _try_fill_grade_for_student_on_current_page(page, aluno, nota_texto, coluna_sge=coluna_sge)
    if suffix:
        return suffix

    for _ in range(max_pages - 1):
        if not _go_to_next_grade_page(page):
            break
        suffix = _try_fill_grade_for_student_on_current_page(page, aluno, nota_texto, coluna_sge=coluna_sge)
        if suffix:
            return suffix

    return ""


def _sample_students_from_current_grade_page(page, limit: int = 12) -> List[str]:
    sample: List[str] = []
    for scope in _iter_scopes(page):
        for slot in _collect_student_slots(scope):
            nome = str(slot.get("aluno", "")).strip()
            if nome:
                sample.append(nome)
            if len(sample) >= limit:
                return sample
    return sample


def _check_estrutura_sge(
    page,
    logger: Optional[LogFn],
    contexto: Optional["ContextoTurma"] = None,
    atividade: str = "",
) -> Dict[str, Any]:
    """Verifica se a estrutura da grade de notas do SGE continua reconhecivel.

    Chamado a cada bloco, DEPOIS de abrir a atividade. Se nenhum slot de aluno
    nem coluna de nota for reconhecido (mesmo com a cadeia de fallback), salva
    evidencia em ESTRUTURA_DIR e retorna ok=False -> o chamador ABORTA sem gravar.

    Retorna: {"ok": bool, "slots": int, "colunas": [...], "inputs": int,
              "evidencia": {screenshot, html, info}, "sugestao_ia": "..." }
    """
    try:
        slots_total = 0
        inputs_total = 0
        for scope in _iter_scopes(page):
            slots_total += len(_collect_student_slots(scope))
            try:
                inputs_total += int(scope.evaluate(
                    "() => document.querySelectorAll('input[type=\"text\"], input[type=\"number\"]').length"
                ) or 0)
            except Exception:  # noqa: BLE001
                pass

        colunas = _distinct_grade_columns_on_page(page)
        if slots_total > 0 or colunas:
            _log(logger, f"[ESTRUTURA] ok: slots={slots_total} colunas={colunas} inputs={inputs_total}")
            return {"ok": True, "slots": slots_total, "colunas": colunas, "inputs": inputs_total}

        # Guarda contra falso alarme: so tratamos como mudanca de ESTRUTURA se
        # realmente estivermos na grade de lancamento (indicadores visiveis).
        if not _grade_entry_indicators_visible(page):
            _log(logger, f"[ESTRUTURA] Nao estamos na grade de lancamento (indicadores ausentes); sem alarme de estrutura.")
            return {"ok": True, "slots": slots_total, "colunas": colunas, "inputs": inputs_total}

        # Estrutura nao reconhecida -> captura evidencia e ABORTA.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            os.makedirs(ESTRUTURA_DIR, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        screenshot_path = os.path.join(ESTRUTURA_DIR, f"estrutura_changed_{timestamp}.png")
        html_path = os.path.join(ESTRUTURA_DIR, f"estrutura_changed_{timestamp}.html")
        info_path = os.path.join(ESTRUTURA_DIR, f"estrutura_changed_{timestamp}_info.txt")
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"[ESTRUTURA-CHANGED] Falha ao capturar screenshot: {exc}")
        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"[ESTRUTURA-CHANGED] Falha ao salvar HTML: {exc}")

        ctx = contexto if isinstance(contexto, ContextoTurma) else None
        info_lines = [
            f"evento=ESTRUTURA-CHANGED",
            f"data={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"url={getattr(page, 'url', '')}",
            f"escola={ctx.escola if ctx else ''}",
            f"turno={ctx.turno if ctx else ''}",
            f"turma={ctx.turma if ctx else ''}",
            f"trimestre={ctx.trimestre if ctx else ''}",
            f"atividade={atividade}",
            f"slots={slots_total}",
            f"colunas={colunas}",
            f"inputs={inputs_total}",
            f"dica=Clique em 'Remodelar' no painel para a IA sugerir novos seletores (gera artifacts/estrutura/estrutura_override.json).",
        ]
        try:
            amostra = page.evaluate(
                """() => Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'))
                    .slice(0, 20).map(el => (el.name || '') + '|' + (el.id || ''))"""
            )
            if amostra:
                info_lines.append(f"amostra_inputs={amostra}")
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(info_path, "w", encoding="utf-8") as f:
                f.write("\n".join(info_lines))
        except Exception:  # noqa: BLE001
            pass

        evidencia = {"screenshot": screenshot_path, "html": html_path, "info": info_path}
        sugestao_ia = ""
        if ai_is_enabled():
            try:
                with open(screenshot_path, "rb") as f:
                    shot = f.read()
                ai_result = analyze_portal_failure(
                    shot,
                    error="Estrutura da grade de notas nao reconhecida (nenhum slot/coluna encontrado).",
                    operation="lancar_notas",
                    context=f"{ctx.escola if ctx else ''}/{ctx.turma if ctx else ''}/{atividade}",
                    logger=logger,
                )
                sugestao_ia = json.dumps(ai_result, ensure_ascii=False, indent=2)
                with open(os.path.join(ESTRUTURA_DIR, f"estrutura_changed_{timestamp}_ia.json"), "w", encoding="utf-8") as f:
                    f.write(sugestao_ia)
            except Exception as exc:  # noqa: BLE001
                _log(logger, f"[ESTRUTURA-CHANGED] Falha na analise de IA: {exc}")

        _log(
            logger,
            f"[ESTRUTURA-CHANGED] Layout da grade mudou: slots={slots_total} colunas={colunas} inputs={inputs_total}. "
            f"NAO gravando nada. Evidencia em {ESTRUTURA_DIR}.",
        )
        return {
            "ok": False,
            "slots": slots_total,
            "colunas": colunas,
            "inputs": inputs_total,
            "evidencia": evidencia,
            "sugestao_ia": sugestao_ia,
        }
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"[ESTRUTURA] Aviso: check de estrutura falhou ({exc}); prosseguindo.")
        return {"ok": True, "slots": -1, "colunas": [], "inputs": -1}


def _fill_grade_for_student(page, aluno: str, nota: float, logger: Optional[LogFn], coluna_sge: str = "") -> str:
    """Preenche a nota do aluno. Retorna o suffix preenchido ou '' se falhou."""
    nota_texto = str(nota).replace(".", ",")

    if not coluna_sge and len(_distinct_grade_columns_on_page(page)) > 1:
        # Sem coluna alvo definida numa pagina com varias colunas de nota, o
        # preenchimento sem filtro poderia gravar na coluna de OUTRA avaliacao.
        # Nao arriscar: marca como nao preenchido (o aluno segue como ausente).
        _log(logger, f"[COLUNA-DETECT] Pagina com varias colunas e coluna alvo indefinida; NAO preenchendo '{aluno}' (evita escrever na coluna errada).")
        return ""

    suffix = _fill_grade_for_student_by_indexed_inputs(page, aluno, nota_texto, coluna_sge=coluna_sge)
    if suffix:
        return suffix

    _log(logger, f"[DEBUG] URL atual: {page.url}")
    _log(logger, f"[DEBUG] Titulo: {page.title()}")

    amostra = _sample_students_from_current_grade_page(page, limit=12)
    if amostra:
        _log(logger, f"Diagnostico: aluno alvo='{aluno}' nao casou via campos indexados. Amostra da pagina: {', '.join(amostra)}")

    # Debug: mostra nomes de input disponiveis na pagina
    try:
        input_info = page.evaluate("""
            () => Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'))
                .slice(0, 20)
                .map(el => ({ name: el.name || '', id: el.id || '', value: (el.value || '').trim() }))
        """)
        if input_info:
            _log(logger, f"[DEBUG] Inputs na pagina: {input_info}")
    except Exception:
        pass

    row = _find_student_row_with_pagination(page, aluno)
    if row is None:
        _capture_stage_debug(page, stage="student_not_found", logger=logger)
        _log(logger, f"Aviso: aluno nao localizado na grade: {aluno}")
        return ""

    # Tenta com coluna_sge primeiro; NAO cai em leitura sem filtro quando a
    # coluna esta definida (evita preencher a coluna de outra avaliacao).
    for col in ([coluna_sge] if coluna_sge else [""]):
        if col:
            inputs = row.locator(f"input[type='text'][name*='_{col}_'], input[type='number'][name*='_{col}_'], input[type='text'][id*='_{col}_'], input[type='number'][id*='_{col}_']")
        else:
            inputs = row.locator("input[type='text']:visible, input[type='number']:visible")
        if inputs.count() > 0:
            try:
                cell = inputs.first
                cell.click(timeout=ACTION_TIMEOUT_MS)
                cell.fill(nota_texto, timeout=ACTION_TIMEOUT_MS)
                if col:
                    _log(logger, f"[DEBUG] Preenchido via row_fallback com coluna '{col}' para '{aluno}'")
                else:
                    _log(logger, f"[DEBUG] Preenchido via row_fallback sem coluna para '{aluno}'")
                return "row_fallback"
            except Exception as exc:
                _log(logger, f"Erro ao preencher nota de {aluno} (coluna='{col}'): {exc}")

    _log(logger, f"Aviso: campo de nota nao encontrado para aluno: {aluno}")
    return ""


def _is_zero_like_value(value: str) -> bool:
    """Retorna True se o valor for um zero/vazio padrao do SGE (ex.: '0,0', '0')."""
    normalized = (value or "").strip().replace(",", ".").replace(" ", "")
    if not normalized:
        return True
    try:
        return abs(float(normalized)) < 1e-9
    except ValueError:
        return False


def _read_existing_grade_for_student(page, aluno: str, logger: Optional[LogFn], coluna_sge: str = "") -> Optional[str]:
    """Le o valor atual da celula de nota no SGE para o aluno (via JS, rapido).

    Retorna o valor como string se preenchido com valor != zero, ou None.
    Tenta com coluna_sge; se definida, NAO usa fallback sem filtro (evita ler
    o valor de outra avaliacao exibida na mesma pagina).
    """
    if not _normalize_loose(aluno):
        return None

    def _try_read(cols: str) -> Optional[str]:
        try:
            for scope in _iter_scopes(page):
                slots = _wait_student_slots(scope)
                if not slots:
                    continue

                suffixes = _candidate_suffixes_for_student(aluno, slots)
                for suffix in suffixes[:3]:
                    val = _read_grade_value_js(scope, suffix, cols, strict=True)
                    if val is not None:
                        return val
        except Exception:  # noqa: BLE001
            pass
        return None

    if coluna_sge:
        result = _try_read(coluna_sge)
        if result is not None:
            return result
        # IMPORTANTE: nao confiar em leitura sem filtro de coluna para decidir
        # "ja lancada". Ela pode retornar o valor de OUTRA avaliacao exibida na
        # mesma pagina (ex.: nota de avaliacao anterior), causando falso [SGE-JA]
        # e pulando a gravacao da nota correta na coluna alvo.
        other = _try_read("")
        if other is not None:
            _log(logger, f"[DEBUG] Coluna '{coluna_sge}' sem valor para '{aluno}' (outra coluna contem '{other}'; NAO tratado como ja lancado).")
        return None

    # Sem coluna definida: leitura sem filtro so e confiavel se a pagina tiver
    # no maximo UMA coluna de nota distinta (ex.: pagina 'Notas da Avaliacao'
    # com '_NOTA_<suffix>'). Paginas com varias colunas podem retornar o valor de
    # outra avaliacao (ex.: nota do 1o trimestre) no primeiro campo correspondente
    # ao suffix do aluno, causando [SGE-JA] falso (nota 2o=0,0 lida como 9,2).
    # Sem coluna definida: tenta primeiro a leitura ANCORADA na linha do aluno.
    # Ela resolve a ambiguidade de paginas com varias colunas/avaliacoes usando o
    # nome do aluno para isolar o campo certo (o mesmo suffix aparece em varias
    # linhas; a <tr> do aluno desambigua).
    try:
        for scope in _iter_scopes(page):
            slots = _wait_student_slots(scope)
            if not slots:
                continue
            suffixes = _candidate_suffixes_for_student(aluno, slots)
            for suffix in suffixes[:3]:
                res = _read_grade_value_anchored_js(scope, aluno, suffix, "")
                if res is None:
                    continue
                val, count = res
                if count != 1:
                    continue
                if val and not _is_zero_like_value(val):
                    _log(logger, f"[DEBUG] Leitura ancorada na linha encontrou nota '{val}' para '{aluno}'")
                    return val
    except Exception:  # noqa: BLE001
        pass

    distinct = _distinct_grade_columns_on_page(page)
    if len(distinct) > 1:
        _log(logger, f"[DEBUG] Leitura sem filtro ignorada para '{aluno}': pagina com varias colunas de nota ({distinct}).")
        return None
    result = _try_read("")
    if result is not None:
        _log(logger, f"[DEBUG] Leitura sem filtro de coluna encontrou nota '{result}' para '{aluno}'")
        return result
    return None


def _find_grade_input_for_student(page, aluno: str, coluna_sge: str = ""):
    """Localiza o input de nota do aluno na pagina (para screenshot/evidencia).

    Retorna um Playwright Locator do campo (ou None). Reusa o mecanismo de
    slots/suffixes usado na leitura/preenchimento e a cadeia de fallback
    (CSS -> atributo via JS -> linha do aluno por texto) do PONTO 3.1.
    """
    if not _normalize_loose(aluno):
        return None
    try:
        for scope in _iter_scopes(page):
            slots = _wait_student_slots(scope)
            if not slots:
                continue
            suffixes = _candidate_suffixes_for_student(aluno, slots)
            for suffix in suffixes[:3]:
                loc = _locate_grade_input(scope, suffix, coluna_sge, aluno=aluno)
                if loc is not None and loc.count() > 0:
                    return loc.first
        # Fallback final: aluno achado por texto mesmo sem suffix casar.
        for scope in _iter_scopes(page):
            loc = _locate_grade_input_by_row_text(scope, aluno, coluna_sge)
            if loc is not None:
                return loc
    except Exception:  # noqa: BLE001
        pass
    return None


def _capturar_evidencia_divergencia(page, aluno: str, coluna_sge: str, out_path: str, logger: Optional[LogFn] = None) -> None:
    """Salva screenshot do trecho da grade do aluno como evidencia da divergencia.

    Tenta recortar a linha/coluna do aluno; se nao localizar, captura a pagina
    inteira como fallback.
    """
    try:
        locator = _find_grade_input_for_student(page, aluno, coluna_sge)
        if locator is not None:
            row = locator.locator("xpath=ancestor::tr[1]")
            if row.count() > 0:
                row.screenshot(path=out_path)
                _log(logger, f"[EVIDENCIA] Screenshot da linha do aluno salvo em {out_path}")
                return
            locator.screenshot(path=out_path)
            _log(logger, f"[EVIDENCIA] Screenshot do campo salvo em {out_path}")
            return
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"[EVIDENCIA] Falha ao capturar trecho da grade: {exc}")
    try:
        page.screenshot(path=out_path, full_page=True)
        _log(logger, f"[EVIDENCIA] Screenshot da pagina salvo em {out_path}")
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"[EVIDENCIA] Falha ao capturar screenshot da pagina: {exc}")


def _read_grade_value_js(scope, suffix: str, coluna_sge: str = "", strict: bool = False) -> Optional[str]:
    """Le o valor de um campo de nota via JS (1 round-trip).

    strict=True: retorna o valor somente quando existe EXATAMENTE um campo
    casando com o suffix/coluna. Com mais de um (ex.: pagina com varias
    avaliacoes usando '_NOTA_<suffix>'/'_AVAL..._' duplicado) retorna None:
    leitura ambigua, que NAO pode decidir 'ja lancada' sem risco de [SGE-JA]
    falso. Usado em _read_existing_grade_for_student.

    strict=False: retorna o valor do PRIMEIRO campo que casar (comportamento da
    verificacao pos-preenchimento, quando o valor acabou de ser gravado ali).
    """
    js = """
    ({suffix, coluna, strict}) => {
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        const matches = [];
        for (const el of candidates) {
            const name = (el.getAttribute('name') || '').trim();
            const id = (el.getAttribute('id') || '').trim();
            const attrs = (name + ' ' + id).toLowerCase();
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.includes('_' + coluna.toLowerCase() + '_')) continue;
            matches.push((el.value || '').trim());
        }
        if (strict && matches.length !== 1) return null;
        return matches.length ? matches[0] : '';
    }
    """
    try:
        raw = scope.evaluate(js, {"suffix": suffix, "coluna": coluna_sge, "strict": strict})
        if raw is None:
            return None
        val = str(raw)
        if val and not _is_zero_like_value(val):
            return val
    except Exception:  # noqa: BLE001
        pass
    return None


def _read_grade_value_anchored_js(scope, aluno: str, suffix: str, coluna_sge: str = ""):
    """Le o valor do campo de nota ancorando na LINHA que contem o nome do aluno.

    Resolve a ambiguidade de paginas com varias colunas/avaliacoes (onde o mesmo
    suffix aparece em varios campos): o campo valido e o que esta dentro da <tr>
    cujo texto contem a maioria dos tokens do nome do aluno.

    Retorna (valor, num_campos_na_linha) ou None se nao conseguir ancorar. O valor
    e bruto (inclui '0,0' e vazio) para o chamador decidir; count>1 indica linha
    com mais de um campo do suffix (ambiguo -> chamador deve NAO confirmar).
    """
    js = """
    ({suffix, coluna, alvo}) => {
        const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
        const tokenize = s => Array.from(new Set((norm(s).match(/[a-z0-9]{2,}/g) || [])));
        const alvoTokens = alvo ? tokenize(alvo) : [];
        if (!alvoTokens.length) return null;
        const candidates = Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'));
        const hits = [];
        for (const el of candidates) {
            const attrs = norm((el.getAttribute('name') || '') + ' ' + (el.getAttribute('id') || ''));
            if (!attrs.includes('_' + suffix)) continue;
            if (coluna && !attrs.includes('_' + norm(coluna) + '_')) continue;
            const row = el.closest('tr');
            if (!row) continue;
            const rowTokens = tokenize(row.innerText || '');
            if (!rowTokens.length) continue;
            let hit = 0;
            for (const t of alvoTokens) { if (rowTokens.includes(t)) hit += 1; }
            if (hit < Math.max(1, Math.ceil(alvoTokens.length * 0.6))) continue;
            const rowInputs = Array.from(row.querySelectorAll('input[type="text"], input[type="number"]')).filter(i => {
                const a = norm((i.getAttribute('name') || '') + ' ' + (i.getAttribute('id') || ''));
                return a.includes('_' + suffix);
            });
            hits.push({value: (el.value || '').trim(), count: rowInputs.length, matched: hit});
        }
        if (!hits.length) return null;
        hits.sort((a, b) => b.matched - a.matched || a.count - b.count);
        return {value: hits[0].value, count: hits[0].count};
    }
    """
    try:
        raw = scope.evaluate(js, {"suffix": suffix, "coluna": coluna_sge, "alvo": aluno})
        if raw is None:
            return None
        return str(raw.get("value", "")), int(raw.get("count", 0))
    except Exception:  # noqa: BLE001
        return None


def _read_grade_value_for_student_raw(page, aluno: str, coluna_sge: str = "") -> Optional[str]:
    """Rele o valor BRUTO (inclui '0,0' e vazio) do campo de nota do aluno.

    Usa a ancora de linha para resolver ambiguidade. Retorna o valor quando ha
    exatamente UM campo do suffix na linha do aluno; None se nao ancorar.
    """
    if not _normalize_loose(aluno):
        return None
    try:
        for scope in _iter_scopes(page):
            slots = _wait_student_slots(scope)
            if not slots:
                continue
            suffixes = _candidate_suffixes_for_student(aluno, slots)
            for suffix in suffixes[:3]:
                res = _read_grade_value_anchored_js(scope, aluno, suffix, coluna_sge)
                if res is None:
                    continue
                val, count = res
                if count == 1:
                    return val
    except Exception:  # noqa: BLE001
        pass
    return None


def _revisao_item_id(escola: str, turma: str, trimestre: str, atividade: str, aluno: str) -> str:
    """Mesmo id de item da fila de revisao usado pelo painel (hash sha1)."""
    import hashlib
    chave = "|".join([
        str(escola).lower(), str(turma).lower(), str(trimestre).lower(),
        str(atividade).lower(), str(aluno).lower(),
    ])
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:12]


def _coletar_nao_confirmado(page, contexto, atividade: str, aluno: str, nota_esperada: str,
                            nota_lida: str, coluna_sge: str = "", logger: Optional[LogFn] = None) -> Dict[str, Any]:
    """Monta um item de NAO-CONFIRMADO (com screenshot de evidencia) para a fila do painel."""
    item_id = _revisao_item_id(contexto.escola, contexto.turma, contexto.trimestre, atividade, aluno)
    try:
        os.makedirs(REVISAO_DIR, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    shot = os.path.join(REVISAO_DIR, f"{item_id}.png")
    try:
        _capturar_evidencia_divergencia(page, aluno, coluna_sge, shot, logger=logger)
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            logger(f"[REVISAO] Falha ao capturar evidencia: {exc}")
    return {
        "id": item_id,
        "escola": contexto.escola,
        "turno": contexto.turno,
        "turma": contexto.turma,
        "trimestre": contexto.trimestre,
        "atividade": atividade,
        "aluno": aluno,
        "nota_esperada": nota_esperada,
        "nota_lida": str(nota_lida or ""),
        "screenshot": shot,
        "coluna_sge": coluna_sge,
        "decisao": None,
        "valor_corrigido": "",
        "resolvido": False,
    }


def _assessment_has_content(props: Dict[str, Dict], status_prop_real: str) -> bool:
    """True se a avaliacao correspondente a 'Status lancamento N' tem conteudo no Notion.

    A avaliacao N e considerada vazia quando a coluna 'Data realizacao N' esta sem data.
    Usa a data (e nao o mapeamento por proximidade de colunas) porque a ordem das
    propriedades retornada pela API do Notion e imprevisivel — o mapeamento por proximidade
    pode associar colunas de nota reais a um 'Status lancamento N' de avaliacao vazia,
    causando falso positivo. Isso evita marcar 'Lancada'/'Falha' em colunas de avaliacao
    que existem no schema da database mas estao completamente vazias.
    """
    m = re.search(r"lancamento\s*(\d+)", _normalize(status_prop_real))
    if not m:
        return True
    n = m.group(1)

    for k, v in props.items():
        if re.search(rf"data\s*realiza[çc][ãa]o\s*{re.escape(n)}", _normalize(k)):
            return bool(_extract_plain_text(v).strip())

    return False


def _update_launch_status_for_notes(registros: List[RegistroNota], logger: Optional[LogFn]) -> None:
    if not registros:
        return
    if not NOTION_TOKEN:
        _log(logger, "Aviso: NOTION_TOKEN ausente; status de lancamento nao foi atualizado.")
        return

    notion = Client(auth=NOTION_TOKEN)
    atualizados = 0
    falhas = 0
    ignorados = 0
    vistos = set()
    _diag_logged = False

    for reg in registros:
        page_id = _normalize_notion_id(reg.notion_page_id)
        status_prop = (reg.notion_status_prop or "").strip()
        if not page_id or not status_prop:
            ignorados += 1
            continue

        chave = (page_id, status_prop)
        if chave in vistos:
            continue
        vistos.add(chave)

        try:
            page = _safe_notion_call(lambda page_id=page_id: notion.pages.retrieve(page_id=page_id))
            props = page.get("properties", {})

            if not _diag_logged:
                _diag_logged = True
                status_candidates = [k for k in props if "status" in k.lower() and "lancamento" in k.lower()]
                _log(logger, f"[STATUS-DIAG] Propriedades com 'status'+'lancamento': {status_candidates}")
                _log(logger, f"[STATUS-DIAG] Buscando: '{status_prop}'")
                _log(logger, f"[STATUS-DIAG] Todas propriedades: {list(props.keys())}")

            status_prop_real = _resolve_existing_status_prop(props, status_prop)

            if status_prop_real != status_prop:
                _log(logger, f"[STATUS-DIAG] '{status_prop}' resolvido para '{status_prop_real}' para {reg.aluno}")

            prop_info = props.get(status_prop_real, {})
            ptype = prop_info.get("type")

            if not prop_info:
                _log(logger, f"Aviso: propriedade '{status_prop}' (resolvida: '{status_prop_real}') nao existe para {reg.aluno}. Pulando.")
                ignorados += 1
                continue

            if not _assessment_has_content(props, status_prop_real):
                _log(logger, f"  [PROTECAO] Avaliacao vazia no Notion ('{status_prop_real}') para {reg.aluno}. NAO marcando Lancada.")
                ignorados += 1
                continue

            if ptype == "select":
                payload = {status_prop_real: {"select": {"name": "Lancada"}}}
            elif ptype == "status":
                payload = {status_prop_real: {"status": {"name": "Lancada"}}}
            elif ptype == "checkbox":
                payload = {status_prop_real: {"checkbox": True}}
            elif ptype == "rich_text":
                payload = {status_prop_real: {"rich_text": _make_rich_text("Lancada")}}
            else:
                disp = [k for k, v in props.items() if v.get("type") in {"select", "checkbox", "rich_text", "status"} and "status" in k.lower()]
                _log(logger, f"Aviso: propriedade '{status_prop_real}' tem tipo '{ptype}' (nao suportado) para {reg.aluno}. Disponiveis: {disp}")
                falhas += 1
                continue

            resp = _safe_notion_call(
                lambda page_id=page_id, payload=payload: notion.pages.update(page_id=page_id, properties=payload)
            )

            if atualizados < 3:
                resp_status = resp.get("properties", {}).get(status_prop_real, {})
                _log(logger, f"[STATUS-RESP] #{atualizados+1} {reg.aluno}: payload={payload}, resp_type={resp_status.get('type')}, resp_val={resp_status.get(resp_status.get('type', ''), {})}")

            atualizados += 1
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            _log(logger, f"Aviso: falha ao atualizar status de lancamento ({reg.aluno}): {exc}")

    _log(logger, f"Status de lancamento atualizado em {atualizados} nota(s). Falhas: {falhas}. Ignorados: {ignorados}.")
    if ignorados and not falhas:
        _log(logger, "Dica: as propriedades de status podem nao existir no Notion. Verifique se existem colunas 'Status lancamento N' na database.")


def _mark_failed_launch_status_for_notes(registros: List[RegistroNota], logger: Optional[LogFn]) -> None:
    if not registros:
        return
    if not NOTION_TOKEN:
        return

    notion = Client(auth=NOTION_TOKEN)
    atualizados = 0
    falhas = 0
    vistos = set()

    for reg in registros:
        page_id = _normalize_notion_id(reg.notion_page_id)
        status_prop = (reg.notion_status_prop or "").strip()
        if not page_id or not status_prop:
            continue

        chave = (page_id, status_prop)
        if chave in vistos:
            continue
        vistos.add(chave)

        try:
            page = _safe_notion_call(lambda page_id=page_id: notion.pages.retrieve(page_id=page_id))
            props = page.get("properties", {})
            status_prop_real = _resolve_existing_status_prop(props, status_prop)
            prop_info = props.get(status_prop_real, {})
            ptype = prop_info.get("type")

            if not _assessment_has_content(props, status_prop_real):
                _log(logger, f"  [PROTECAO] Avaliacao vazia no Notion ('{status_prop_real}') para {reg.aluno}. NAO marcando Falha.")
                falhas += 1
                continue

            if ptype == "select":
                payload = {status_prop_real: {"select": {"name": "Falha"}}}
            elif ptype == "status":
                payload = {status_prop_real: {"status": {"name": "Falha"}}}
            elif ptype == "checkbox":
                payload = {status_prop_real: {"checkbox": False}}
            elif ptype == "rich_text":
                payload = {status_prop_real: {"rich_text": _make_rich_text("Falha")}}
            else:
                falhas += 1
                continue

            _safe_notion_call(
                lambda page_id=page_id, payload=payload: notion.pages.update(page_id=page_id, properties=payload)
            )
            atualizados += 1
        except Exception:  # noqa: BLE001
            falhas += 1

    try:
        _log(logger, f"Status de falha atualizado em {atualizados} nota(s). Falhas: {falhas}")
    except Exception:
        pass


def _confirm_save(page, logger: Optional[LogFn], data_realizacao: str = "") -> bool:
    """Confirma o salvamento e verifica se foi bem-sucedido. Retorna True se salvou."""
    # Preenche a data antes de confirmar: usa a data do Notion se disponivel, senao usa hoje
    data_para_usar = ""
    if data_realizacao:
        dt = _parse_date(data_realizacao)
        if dt:
            data_para_usar = dt.strftime("%d/%m/%Y")
    if not data_para_usar:
        data_para_usar = datetime.now().strftime("%d/%m/%Y")

    for scope in _iter_scopes(page):
        date_input = _first_visible(
            scope,
            [
                "input[name*='DATALANCAMENTO' i]",
                "input[name*='DATALAN' i]",
                "input[name*='_DATA' i]",
                "input[id*='DATALANCAMENTO' i]",
                "input[id*='DATALAN' i]",
            ],
        )
        if date_input is not None:
            try:
                date_input.fill(data_para_usar, timeout=ACTION_TIMEOUT_MS)
                _log(logger, f"Data preenchida: {data_para_usar}")
            except Exception:  # noqa: BLE001
                pass
            break

    submit = _first_visible(
        page,
        [
            "button:has-text('Confirma')",
            "input[type='submit'][value*='Confirma']",
            "button:has-text('Salvar')",
            "button:has-text('Confirmar')",
            "button:has-text('Lancar')",
            "button:has-text('Gravar')",
        ],
    )
    if submit is None:
        for scope in _iter_scopes(page):
            submit = _first_visible(
                scope,
                [
                    "button:has-text('Confirma')",
                    "input[type='submit'][value*='Confirma']",
                    "button:has-text('Salvar')",
                    "button:has-text('Confirmar')",
                    "button:has-text('Lancar')",
                    "button:has-text('Gravar')",
                ],
            )
            if submit is not None:
                break
    if submit is None:
        _log(logger, "Aviso: botao de confirmacao nao encontrado; seguindo para o proximo bloco.")
        return False

    try:
        submit.click(timeout=ACTION_TIMEOUT_MS, no_wait_after=True)
    except TypeError:
        submit.click(timeout=ACTION_TIMEOUT_MS)
    try:
        page.wait_for_timeout(500)
    except Exception:  # noqa: BLE001
        pass

    # Verificar se houve erro de validacao do ASP.NET
    try:
        error_indicators = page.locator(".validationSummary, .error, .erro, [id*='Error'], [id*='erro'], .alert-danger, .text-danger")
        if error_indicators.count() > 0:
            error_text = ""
            for i in range(min(error_indicators.count(), 3)):
                try:
                    txt = error_indicators.nth(i).inner_text(timeout=500)
                    if txt:
                        error_text += txt.strip() + "; "
                except Exception:
                    pass
            if error_text:
                _log(logger, f"[SAVE-ERROR] Erro de validacao detectado: {error_text}")
                return False
    except Exception:
        pass

    # Verificar se a pagina retornou para a grade (indicando sucesso)
    try:
        page.wait_for_selector("table#GRIDAGENDA", timeout=5000)
        _log(logger, "[SAVE-OK] Grade visivel apos salvamento.")
        return True
    except Exception:
        pass

    # Verificar se ha mensagem de sucesso
    try:
        success_indicators = page.locator(".success, .sucesso, .alert-success, .text-success, :has-text('Salvo com sucesso'), :has-text('Gravado')")
        if success_indicators.count() > 0:
            _log(logger, "[SAVE-OK] Mensagem de sucesso detectada.")
            return True
    except Exception:
        pass

    _log(logger, "[SAVE-UNKNOWN] Nao foi possivel confirmar salvamento. Continuando...")
    return True  # Assumir sucesso se nao detectou erro explicito


def _group_for_launch(registros: List[RegistroNota]):
    grouped: Dict[Tuple[str, str, str, str, str], List[RegistroNota]] = defaultdict(list)
    for reg in registros:
        key = (reg.escola, reg.turno, reg.turma, reg.trimestre, reg.atividade)
        grouped[key].append(reg)
    return grouped


def _revisar_blocos_apos_lancamento(
    page,
    blocos: List[Dict[str, Any]],
    logger: Optional[LogFn] = None,
) -> Dict[str, int]:
    """Re-auditoria final pos-save: reabre cada bloco e confere as notas.

    Para cada aluno lancado no bloco:
      1) Rela o campo via JS (mesmo mecanismo do lancamento) e compara com o esperado.
      2) Se divergir/nao encontrar, IA com visao (verify_grade_on_screen) confere
         se a nota esta correta na tela — pega casos que seletores nao pegam.
      3) Se a IA confirmar, conta como OK. Se NAO confirmar, apenas registra no
         log como nao confirmado (NAO regrava a nota e NAO marca 'Falha' no Notion:
         a regravacao nesta fase pode escrever na coluna/avaliacao errada).

    Retorna resumo de revisao: revisados, ok, corrigidos (sempre 0), falhas, ai_usada.
    """
    # Re-auditoria roda numa SEGUNDA sessao do navegador (novo login). Os caches
    # globais de navegacao podem estar marcados com o contexto/sessao anterior:
    # resetar garante que _select_context refaca a navegacao e que a busca de
    # alunos por paginacao comece do zero nesta pagina nova.
    global _current_context
    _current_context = None
    _student_page_cache.clear()

    resumo: Dict[str, Any] = {"revisados": 0, "ok": 0, "corrigidos": 0, "falhas": 0, "ai_usada": 0}
    resumo["itens_nao_confirmados"] = []
    MAX_AI_PER_BLOCO = 3

    for bloco in blocos:
        contexto = bloco.get("contexto")
        atividade = bloco.get("atividade", "")
        itens = bloco.get("itens", []) or []
        data_realizacao = bloco.get("data_realizacao", "")
        if not contexto or not itens:
            continue

        _log(logger, f"[REVISAO] Bloco: {contexto.escola} | {contexto.turma} | {atividade} ({len(itens)} aluno(s))")

        # Apos o login novo podem aparecer telas de selecao de escola/periodo
        # antes do dashboard. Trata aqui por bloco (a escola/periodo do bloco).
        try:
            if _is_school_selection_page(page):
                _log(logger, "[REVISAO] Tela de selecao de escola detectada. Selecionando escola do bloco...")
                ctx_temp = ContextoTurma(escola=contexto.escola, turno="", turma="", trimestre="")
                _select_school(page, ctx_temp, logger=logger)
            if _is_period_selection_page(page):
                _log(logger, "[REVISAO] Tela de selecao de periodo detectada. Selecionando periodo do bloco...")
                ctx_temp = ContextoTurma(escola="", turno="", turma="", trimestre=contexto.trimestre)
                _select_period(page, ctx_temp, logger=logger)
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"[REVISAO] Erro ao tratar telas pos-login: {exc}")

        try:
            _select_context(page, contexto, logger=logger)
        except Exception as exc:  # noqa: BLE001
            _log(logger, f"[REVISAO] Erro ao navegar para o contexto: {exc}")
            resumo["falhas"] += len(itens)
            continue

        try:
            avaliacao_abriu = _open_assessment_for_context(page, contexto, logger=logger)
        except Exception:  # noqa: BLE001
            avaliacao_abriu = False
        if _handle_assessment_period_page(page, contexto, logger=logger):
            try:
                avaliacao_abriu = _open_assessment_for_context(page, contexto, logger=logger)
            except Exception:  # noqa: BLE001
                avaliacao_abriu = False
            _handle_assessment_period_page(page, contexto, logger=logger)

        atividade_encontrada, _data_sge, posicao_grid = _select_activity(page, atividade, logger=logger)
        if not atividade_encontrada:
            _log(logger, f"[REVISAO] Atividade '{atividade}' nao reencontrada. Nao foi possivel re-auditar.")
            resumo["falhas"] += len(itens)
            continue

        coluna_sge = _detect_coluna_from_page(page, posicao_grid, logger=logger, atividade=atividade)
        ai_calls_bloco = 0

        for reg in itens:
            nota_texto = str(reg.nota).replace(".", ",")
            resumo["revisados"] += 1
            # Leitura com ANCORA na linha do aluno: confere mesmo sem coluna
            # detectada e consegue ler notas zero (0,0), que _read_existing_grade
            # descarta de proposito para nao tratar zero como 'ja lancado'.
            existing = _read_grade_value_for_student_raw(page, reg.aluno, coluna_sge=coluna_sge)
            if existing is not None and _grade_value_matches_target(existing, nota_texto):
                _log(logger, f"  [REVISAO-OK] {reg.aluno}: nota {nota_texto} confirmada (leitura ancorada na linha).")
                resumo["ok"] += 1
                continue

            if existing is not None:
                _log(logger, f"  [REVISAO-DIVERGENTE] {reg.aluno}: esperado {nota_texto}, leu {existing}.")
            else:
                _log(logger, f"  [REVISAO-NAO-ENCONTRADO] {reg.aluno}: campo nao relido com filtro de coluna '{coluna_sge}'.")

            confirmado_ia = False
            if ai_is_enabled() and ai_calls_bloco < MAX_AI_PER_BLOCO:
                ai_calls_bloco += 1
                resumo["ai_usada"] += 1
                try:
                    shot = page.screenshot()
                    ia = verify_grade_on_screen(shot, nota_texto, reg.aluno, logger=logger)
                    if ia.get("confirmed") is True:
                        confirmado_ia = True
                        _log(logger, f"  [REVISAO-IA] IA confirmou {reg.aluno} = {nota_texto} na tela ({ia.get('read_value', '')}).")
                        resumo["ok"] += 1
                        continue
                    _log(logger, f"  [REVISAO-IA] IA nao confirmou {reg.aluno}: {ia.get('notes', ia.get('error', ''))[:120]}")
                except Exception as exc:  # noqa: BLE001
                    _log(logger, f"  [REVISAO-IA] Erro ao consultar IA para {reg.aluno}: {exc}")

            if confirmado_ia:
                continue

            # A re-auditoria NAO regrava a nota nem marca "Falha" no Notion nesta fase:
            # roda numa sessao nova do navegador e a regravacao a partir de uma re-leitura
            # duvidosa pode escrever na coluna/avaliacao errada (corrompendo a nota).
            # O item entra na FILA DE CONFIRMACAO do painel (screenshot + esperado vs lido)
            # para o professor decidir manualmente.
            item = _coletar_nao_confirmado(
                page, contexto, atividade, reg.aluno, nota_texto, existing, coluna_sge, logger=logger
            )
            resumo["itens_nao_confirmados"].append(item)
            _log(logger, f"  [REVISAO-NAO-CONFIRMADO] {reg.aluno}: nota {nota_texto} nao confirmada na tela. "
                         f"Enviada para confirmacao manual (id={item['id']}).")
            resumo["falhas"] += 1

    return resumo


def executar_lancamento(
    filtro: Optional[Dict[str, str]] = None,
    logger: Optional[LogFn] = print,
    dry_run: bool = False,
    revisar_apos: Optional[bool] = None,
    buscar_por_primeiro_nome: bool = False,
) -> Dict[str, int]:
    _log(logger, f"Runtime ref/sha: {os.environ.get('GITHUB_REF_NAME', 'local')} / {os.environ.get('GITHUB_SHA', 'local')[:7]}")
    global _PRIMEIRO_NOME_MATCH_ENABLED
    _PRIMEIRO_NOME_MATCH_ENABLED = bool(buscar_por_primeiro_nome)
    if _PRIMEIRO_NOME_MATCH_ENABLED:
        _log(logger, "[NOME-MATCH] Casamento por primeiro nome ATIVADO (desambigua com 2o/3o nome).")
    cpf = _resolve_env_credential(SGE_CPF, "SGE_CPF", logger=logger, digits_only=True)
    cpf = _normalize_cpf_for_sge(cpf, logger=logger)
    senha = _resolve_env_credential(SGE_SENHA, "SGE_SENHA", logger=logger, digits_only=False)

    if not cpf or not senha:
        raise LancamentoError("Defina SGE_CPF e SGE_SENHA nas variaveis de ambiente.")
    if _is_placeholder_env(cpf) or _is_placeholder_env(senha):
        raise LancamentoError("SGE_CPF/SGE_SENHA estao com placeholders. Atualize com valores reais.")

    # Reseta caches de navegacao
    global _current_context
    _current_context = None
    _student_page_cache.clear()

    registros = carregar_notas_notion(logger=logger, filtro=filtro)
    _log(logger, f"Total de notas carregadas do Notion: {len(registros)}")
    if registros:
        for r in registros[:5]:
            _log(logger, f"  [DEBUG] Aluno='{r.aluno}' Atividade='{r.atividade}' Data='{r.data_realizacao}' Status='{r.notion_status_prop}' Nota={r.nota}")
    registros = _filtrar_registros(registros, filtro, logger=logger)

    if not registros:
        raise LancamentoError("Nenhuma nota encontrada para o filtro selecionado.")

    grouped = _group_for_launch(registros)
    total_blocos = len(grouped)
    total_notas = len(registros)
    _log(logger, f"Blocos para lancamento: {total_blocos} | notas: {total_notas}")

    if filtro and filtro.get("atividade"):
        _log(logger, f"[ATALHO] Modo avaliacao unica: '{filtro['atividade']}' — processo muito mais rapido!")

    # Prepara IA local (Ollama) SOMENTE quando IA esta habilitada
    if ai_is_enabled():
        _log(logger, "[Ollama] Verificando instalacao do Ollama e modelo de visao...")
        _log(logger, "[Ollama] Nota: download pode levar varios minutos na primeira execucao.")
        ollama_ok = ensure_ollama(logger=logger)
        if ollama_ok:
            os.environ["AI_PROVIDER"] = "ollama"
            _log(logger, "[Ollama] Ollama disponivel. Usando IA local.")
        else:
            provider = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
            _log(logger, f"[Ollama] Ollama nao disponivel. Usando provider: {provider}")
    else:
        _log(logger, "[AI] Assistencia IA desabilitada. Pulando configuracao do Ollama.")

    if dry_run:
        _log(logger, "Dry-run habilitado: nenhum dado sera enviado ao SGE.")
        return {
            "blocos": total_blocos,
            "notas": total_notas,
            "notas_preenchidas": 0,
            "ausentes": 0,
            "falhas": 0,
        }

    notas_ok = 0
    falhas = 0
    ausentes = 0

    blocos_lancados: List[Dict[str, Any]] = []
    falhas_verificacao: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(ACTION_TIMEOUT_MS)

        _login_sge(page, cpf=cpf, senha=senha, logger=logger)

        # Selecao de escola e periodo (telas pos-login que aparecem antes do dashboard)
        if _is_school_selection_page(page) and grouped:
            escola_primeiro = next(iter(grouped.keys()))[0]
            ctx_temp = ContextoTurma(escola=escola_primeiro, turno="", turma="", trimestre="")
            _select_school(page, ctx_temp, logger=logger)

        if _is_period_selection_page(page) and grouped:
            trimestre_primeiro = next(iter(grouped.keys()))[3]
            ctx_temp = ContextoTurma(escola="", turno="", turma="", trimestre=trimestre_primeiro)
            _select_period(page, ctx_temp, logger=logger)

        _notion_threads: List[threading.Thread] = []
        for idx, (key, itens) in enumerate(grouped.items(), start=1):
            escola, turno, turma, trimestre, atividade = key
            _log(logger, f"[{idx}/{total_blocos}] {escola} | {turno} | {turma} | {trimestre} | {atividade}")

            # Verificacao de datas: compara a data da atividade no Notion com a data atual
            datas_bloco = [r.data_realizacao for r in itens if r.data_realizacao]
            data_mais_comum = ""
            if datas_bloco:
                data_mais_comum = Counter(datas_bloco).most_common(1)[0][0]
                diff_dias = _date_diff_days(data_mais_comum)
                if diff_dias is not None:
                    if diff_dias > 0:
                        _log(logger, f"[DATA] Atividade com data futura ({data_mais_comum}, {diff_dias} dia(s) a frente). Pulando bloco.")
                        for reg in itens:
                            falhas += 1
                        t = threading.Thread(target=_mark_failed_launch_status_for_notes, args=(itens,), kwargs={"logger": logger}, daemon=True)
                        t.start()
                        _notion_threads.append(t)
                        continue
                    elif diff_dias < -90:
                        _log(logger, f"[DATA] Atencao: atividade com data antiga ({data_mais_comum}, {abs(diff_dias)} dias atras). Prosseguindo...")
                    else:
                        _log(logger, f"[DATA] Data da atividade: {data_mais_comum} ({abs(diff_dias)} dia(s) atras)")
            else:
                _log(logger, "[DATA] Nenhuma data de realizacao definida no Notion para esta atividade.")

            contexto = ContextoTurma(escola=escola, turno=turno, turma=turma, trimestre=trimestre)
            _select_context(page, contexto, logger=logger)

            # Fluxo hibrido assistido: abre o icone de avaliacao da linha da
            # turma/turno/trimestre antes de tentar localizar a atividade.
            avaliacao_abriu = _open_assessment_for_context(page, contexto, logger=logger)

            # Apos clicar no icone, pode aparecer tela de confirmacao de trimestre.
            # Se confirmou, volta pro dashboard e precisa clicar no icone de novo.
            if _handle_assessment_period_page(page, contexto, logger=logger):
                _log(logger, "Re-tentando abrir avaliacao apos confirmar periodo...")
                avaliacao_abriu = _open_assessment_for_context(page, contexto, logger=logger)
                # Segunda tela de periodo eh improvavel, mas verifica por seguranca
                _handle_assessment_period_page(page, contexto, logger=logger)

            if not avaliacao_abriu:
                _log(logger, f"Aviso: nao foi possivel abrir icone de avaliacao para {atividade}. Tentando navegacao direta...")

            atividade_encontrada, data_sge, posicao_grid = _select_activity(page, atividade, logger=logger)
            if not atividade_encontrada:
                _log(logger, f"Aviso: atividade '{atividade}' nao encontrada no SGE. Pulando bloco.")
                for reg in itens:
                    falhas += 1
                t = threading.Thread(target=_mark_failed_launch_status_for_notes, args=(itens,), kwargs={"logger": logger}, daemon=True)
                t.start()
                _notion_threads.append(t)
                continue

            if data_sge and data_mais_comum and not _dates_match(data_sge, data_mais_comum):
                _log(logger, f"[DATA] Validacao falhou: SGE {data_sge} ≠ Notion {data_mais_comum}. Pulando bloco.")
                for reg in itens:
                    falhas += 1
                t = threading.Thread(target=_mark_failed_launch_status_for_notes, args=(itens,), kwargs={"logger": logger}, daemon=True)
                t.start()
                _notion_threads.append(t)
                continue
            if data_sge and data_mais_comum:
                _log(logger, f"[DATA] Datas conferem: SGE {data_sge} = Notion {data_mais_comum}")
            elif not data_sge:
                _log(logger, f"[DATA] Data da atividade nao encontrada no SGE. Prosseguindo sem validacao de data.")

            if posicao_grid > 0:
                status_forcado = f"Status lancamento {posicao_grid}"
                _log(logger, f"[STATUS] Atividade '{atividade}' esta na posicao {posicao_grid} da GRIDAGENDA. Forçando {status_forcado} para todos os registros do bloco.")
                for reg in itens:
                    reg.notion_status_prop = status_forcado

            if AI_LEARN_MODE and idx == 1:
                record_demonstration_step(idx, page, f"navegou para {escola}/{turno}/{turma}/{trimestre}/{atividade}", logger=logger)

            regs_ok_bloco: List[RegistroNota] = []
            regs_fail_bloco: List[RegistroNota] = []
            regs_ausentes_bloco: List[RegistroNota] = []
            novos_preenchimentos = 0
            regs_ja_no_sge: List[RegistroNota] = []
            coluna_sge = _detect_coluna_from_page(page, posicao_grid, logger=logger, atividade=atividade)
            check_estrutura = _check_estrutura_sge(page, logger, contexto=contexto, atividade=atividade)
            if not check_estrutura["ok"]:
                _log(logger, f"[ESTRUTURA-CHANGED] Execucao ABORTADA sem gravar. Evidencia em {ESTRUTURA_DIR}.")
                return {
                    "blocos": total_blocos,
                    "notas": total_notas,
                    "notas_preenchidas": notas_ok,
                    "ausentes": ausentes,
                    "falhas": falhas,
                    "estrutura_changed": True,
                    "estrutura_evidencia": check_estrutura,
                }
            ai_calls_this_block = 0
            MAX_AI_CALLS_PER_BLOCK = 3
            for reg in itens:
                existing = _read_existing_grade_for_student(page, reg.aluno, logger=logger, coluna_sge=coluna_sge)
                if existing is not None:
                    nota_texto = str(reg.nota).replace(".", ",")
                    if _grade_value_matches_target(existing, nota_texto):
                        _log(logger, f"  [SGE-JA] Nota '{existing}' ja existe no SGE para '{reg.aluno}'. Status vazio no Notion → marcando Lancada.")
                        notas_ok += 1
                        regs_ok_bloco.append(reg)
                        regs_ja_no_sge.append(reg)
                        continue
                    _log(logger, f"  Nota existente '{existing}' difere da esperada '{nota_texto}' para '{reg.aluno}'. Atualizando...")

                filled_suffix = _fill_grade_for_student(page, reg.aluno, reg.nota, logger=logger, coluna_sge=coluna_sge)
                if not filled_suffix and ai_is_enabled() and ai_calls_this_block < MAX_AI_CALLS_PER_BLOCK:
                    _log(logger, f"[AI] Aluno '{reg.aluno}' nao encontrado. Tentando assistencia IA... (chamada {ai_calls_this_block+1}/{MAX_AI_CALLS_PER_BLOCK})")
                    ai_calls_this_block += 1
                    try:
                        ai_screenshot = page.screenshot()
                        ai_result = find_element_on_screen(ai_screenshot, f"campo de nota para o aluno {reg.aluno}", logger=logger)
                        raw_selector = ai_result.get("selector", "")
                        selector = _sanitize_ai_selector(raw_selector)
                        if ai_result.get("found") and selector:
                            loc = page.locator(selector)
                            if loc.count() > 0:
                                loc.first.fill(str(reg.nota).replace(".", ","))
                                filled_suffix = "ai_fallback"
                                _log(logger, f"[AI] Nota preenchida via IA para '{reg.aluno}'")
                    except Exception as exc:
                        _log(logger, f"[AI] Erro na assistencia: {exc}")
                elif not filled_suffix and ai_is_enabled() and ai_calls_this_block >= MAX_AI_CALLS_PER_BLOCK:
                    _log(logger, f"[AI] Limite de chamadas IA atingido no bloco ({MAX_AI_CALLS_PER_BLOCK}). Pulando IA para '{reg.aluno}'.")
                if filled_suffix:
                    nota_texto = str(reg.nota).replace(".", ",")
                    if _verify_fill_just_made(page, reg.aluno, nota_texto, logger=logger, coluna_sge=coluna_sge, filled_suffix=filled_suffix):
                        _log(logger, f"  [VERIFICADO] Nota {nota_texto} confirmada no campo para '{reg.aluno}'.")
                        notas_ok += 1
                        novos_preenchimentos += 1
                        regs_ok_bloco.append(reg)
                    else:
                        _log(logger, f"  [FALHA-VERIFICACAO] Nota {nota_texto} NAO confirmada no campo para '{reg.aluno}'. Pode ser campo errado.")
                        try:
                            item_falha = _coletar_nao_confirmado(
                                page, contexto, atividade, reg.aluno, nota_texto, None, coluna_sge, logger=logger
                            )
                            falhas_verificacao.append(item_falha)
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            nome_arq = re.sub(r"[^a-zA-Z0-9_-]", "_", reg.aluno)
                            ev_path = os.path.join(ESTRUTURA_DIR, f"verificacao_falhou_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{nome_arq}.png")
                            os.makedirs(ESTRUTURA_DIR, exist_ok=True)
                            _capturar_evidencia_divergencia(page, reg.aluno, coluna_sge, ev_path, logger=logger)
                        except Exception:  # noqa: BLE001
                            pass
                        falhas += 1
                        regs_fail_bloco.append(reg)
                else:
                    _log(logger, f"  [AUSENTE] Aluno '{reg.aluno}' nao localizado na grade. Pulando...")
                    ausentes += 1
                    regs_ausentes_bloco.append(reg)

            if novos_preenchimentos > 0:
                _confirm_save(page, logger=logger, data_realizacao=data_mais_comum)
                if AI_LEARN_MODE:
                    record_demonstration_step(999, page, f"confirmou salvamento do bloco {idx}", logger=logger)
                blocos_lancados.append({
                    "contexto": contexto,
                    "atividade": atividade,
                    "itens": [r for r in regs_ok_bloco if r not in regs_ja_no_sge],
                    "data_realizacao": data_mais_comum,
                })
            elif regs_ja_no_sge:
                _log(logger, f"[SGE-JA] {len(regs_ja_no_sge)} nota(s) ja existiam no SGE. Apenas status marcado como Lancada.")
            else:
                _log(logger, "Nenhum preenchimento novo neste bloco (todas notas ja estavam no SGE).")
            t_ok = threading.Thread(target=_update_launch_status_for_notes, args=(regs_ok_bloco,), kwargs={"logger": logger}, daemon=True)
            t_fail = threading.Thread(target=_mark_failed_launch_status_for_notes, args=(regs_fail_bloco,), kwargs={"logger": logger}, daemon=True)
            t_ok.start()
            t_fail.start()
            _notion_threads.extend([t_ok, t_fail])

            # Registro automatico de aprendizado
            if novos_preenchimentos > 0:
                _learning_store.registrar_sucesso(
                    "preencher_notas",
                    {"escola": escola, "turno": turno, "turma": turma, "trimestre": trimestre, "atividade": atividade}
                )
            if regs_ausentes_bloco:
                _learning_store.registrar_falha(
                    "encontrar_alunos",
                    {"turma": turma, "atividade": atividade, "ausentes": len(regs_ausentes_bloco)}
                )

        for t in _notion_threads:
            t.join(timeout=30)
        context.close()
        browser.close()

    if revisar_apos is None:
        revisar_apos = os.environ.get("SGE_REVISAR_APOS", "1") == "1"

    revisao_resumo = {"revisados": 0, "ok": 0, "corrigidos": 0, "falhas": 0, "ai_usada": 0}
    if not dry_run and revisar_apos and blocos_lancados:
        _log(logger, f"[REVISAO] Re-auditoria pos-lancamento de {len(blocos_lancados)} bloco(s)...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(ACTION_TIMEOUT_MS)
            _login_sge(page, cpf=cpf, senha=senha, logger=logger)
            # Telas pos-login (escola/periodo) antes da re-auditoria. O bloco
            # tambem trata por bloco dentro de _revisar_blocos_apos_lancamento;
            # aqui garante o caso em que nao ha blocos para revisar.
            if blocos_lancados:
                primeiro_ctx = blocos_lancados[0].get("contexto")
                if primeiro_ctx:
                    try:
                        if _is_school_selection_page(page):
                            ctx_temp = ContextoTurma(escola=primeiro_ctx.escola, turno="", turma="", trimestre="")
                            _select_school(page, ctx_temp, logger=logger)
                        if _is_period_selection_page(page):
                            ctx_temp = ContextoTurma(escola="", turno="", turma="", trimestre=primeiro_ctx.trimestre)
                            _select_period(page, ctx_temp, logger=logger)
                    except Exception as exc:  # noqa: BLE001
                        _log(logger, f"[REVISAO] Erro ao tratar telas pos-login: {exc}")
            revisao_resumo = _revisar_blocos_apos_lancamento(
                page, blocos_lancados, logger=logger,
            )
            context.close()
            browser.close()
        _log(logger, (
            f"[REVISAO] Fim. Revisados: {revisao_resumo['revisados']} | "
            f"Confirmados: {revisao_resumo['ok']} | Corrigidos: {revisao_resumo['corrigidos']} | "
            f"Falhas: {revisao_resumo['falhas']} | IA usada: {revisao_resumo['ai_usada']}"
        ))

    _log(logger, f"Finalizado. Notas preenchidas: {notas_ok} | Ausentes: {ausentes} | Falhas: {falhas}")

    if AI_LEARN_MODE and ai_is_available():
        _log(logger, "[AI] Modo aprendizado ativo. Gerando plano de automacao...")
        plan = learn_from_recording(logger=logger)
        if plan:
            _log(logger, f"[AI] Plano gerado: {plan.get('workflow_name', 'sem nome')} com {len(plan.get('steps', []))} passos.")
        else:
            _log(logger, "[AI] Nao foi possivel gerar plano.")

    if total_notas > 0 and notas_ok == 0:
        raise LancamentoError(
            "Nenhuma nota foi preenchida no SGE. Fluxo interrompido para evitar falso sucesso."
        )

    itens_nao_confirmados = list(revisao_resumo.get("itens_nao_confirmados") or [])
    itens_nao_confirmados.extend(falhas_verificacao)
    revisao_resumo["itens_nao_confirmados"] = itens_nao_confirmados
    if not revisao_resumo.get("falhas"):
        revisao_resumo["falhas"] = len(itens_nao_confirmados)

    return {
        "blocos": total_blocos,
        "notas": total_notas,
        "notas_preenchidas": notas_ok,
        "ausentes": ausentes,
        "falhas": falhas,
        "revisao": revisao_resumo,
        "itens_nao_confirmados": itens_nao_confirmados,
        "divergencias": len(itens_nao_confirmados),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lanca notas do Notion no SGE Indaial")
    parser.add_argument("--escola", default="")
    parser.add_argument("--turno", default="")
    parser.add_argument("--turma", default="")
    parser.add_argument("--trimestre", default="")
    parser.add_argument("--notion-page-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--listar-contextos", action="store_true")
    parser.add_argument("--lote", action="store_true", help="Modo lote: processa todas as escolas, turmas e trimestres do Notion")
    parser.add_argument("--ai-assist", action="store_true", help="Ativa assistencia por IA para navegacao no portal")
    parser.add_argument("--ai-learn", action="store_true", help="Ativa modo de aprendizado: grava acoes do usuario para gerar plano de automacao")
    parser.add_argument("--gemini-api-key", default="", help="Chave API do Gemini (alternativa a env var GEMINI_API_KEY)")
    return parser.parse_args()


def _build_filtro(args: argparse.Namespace) -> Dict[str, str]:
    # No modo lote, nao aplica filtros — processa tudo que o Notion retornar
    if getattr(args, "lote", False):
        return {}
    filtro = {
        "escola": args.escola,
        "turno": args.turno,
        "turma": args.turma,
        "trimestre": args.trimestre,
    }
    return {k: v for k, v in filtro.items() if _is_non_empty(v)}


def main() -> int:
    args = _parse_args()
    args.notion_page_id = _normalize_notion_id(args.notion_page_id)
    logs_execucao: List[str] = []

    def logger(msg: str) -> None:
        print(msg)
        logs_execucao.append(msg)

    if args.ai_assist or args.ai_learn:
        if args.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = args.gemini_api_key
        if args.ai_assist:
            os.environ["AI_ASSIST"] = "1"
        if args.ai_learn:
            os.environ["AI_ASSIST"] = "1"
            os.environ["AI_LEARN_MODE"] = "1"
        logger(f"[AI] Modo {'aprendizado' if args.ai_learn else 'assistido'} ativado.")
        if ai_is_available():
            logger("[AI] IA configurada e disponivel.")
        else:
            logger("[AI] ATENCAO: IA nao disponivel. Defina GEMINI_API_KEY ou configure Ollama.")

    if not args.notion_page_id and _is_non_empty(args.escola) and _normalize(args.escola) not in {"todas", "todos"}:
        try:
            auto_page_id = _find_pending_request_page_id(args.escola, logger=logger)
            if auto_page_id:
                args.notion_page_id = auto_page_id
                logger("Page ID de solicitacao identificado automaticamente.")
        except Exception as exc:  # noqa: BLE001
            logger(f"Aviso: falha ao buscar Page ID automaticamente: {exc}")

    if args.listar_contextos:
        contextos = listar_contextos_disponiveis(logger=logger)
        if not contextos:
            print("Nenhum contexto encontrado.")
            return 1
        for ctx in contextos:
            print(f"- {ctx['escola']} | {ctx['turno']} | {ctx['turma']} | {ctx['trimestre']}")
        return 0

    filtro = _build_filtro(args)
    if args.notion_page_id:
        atualizar_status_execucao_notion(
            page_id=args.notion_page_id,
            status="Em execucao",
            logger=logger,
            log_text="Execucao iniciada pelo dispatcher.",
            clear_request=False,
        )

    try:
        resultado = executar_lancamento(filtro=filtro, logger=logger, dry_run=args.dry_run)
    except LancamentoError as exc:
        if (
            "Nenhuma nota valida foi encontrada no Notion." in str(exc)
            or "Nenhuma nota encontrada para o filtro selecionado." in str(exc)
        ):
            aviso = "Sem notas validas para lancar no Notion. Encerrando sem alteracoes."
            print(f"Aviso: {aviso}")
            if args.notion_page_id:
                atualizar_status_execucao_notion(
                    page_id=args.notion_page_id,
                    status="Concluido",
                    logger=logger,
                    log_text=aviso,
                    clear_request=True,
                )
            return 0

        print(f"Erro: {exc}")
        if args.notion_page_id:
            atualizar_status_execucao_notion(
                page_id=args.notion_page_id,
                status="Erro",
                logger=logger,
                log_text=f"Erro: {exc}",
                clear_request=True,
            )
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Erro inesperado: {exc}")
        if args.notion_page_id:
            atualizar_status_execucao_notion(
                page_id=args.notion_page_id,
                status="Erro",
                logger=logger,
                log_text=f"Erro inesperado: {exc}",
                clear_request=True,
            )
        return 1

    print("Resumo:")
    print(f"- blocos: {resultado['blocos']}")
    print(f"- notas: {resultado['notas']}")
    print(f"- notas_preenchidas: {resultado['notas_preenchidas']}")
    print(f"- falhas: {resultado['falhas']}")

    if args.notion_page_id:
        resumo = (
            f"Concluido. blocos={resultado['blocos']} notas={resultado['notas']} "
            f"preenchidas={resultado['notas_preenchidas']} falhas={resultado['falhas']}"
        )
        log_text = "\n".join((logs_execucao + [resumo])[-20:])
        atualizar_status_execucao_notion(
            page_id=args.notion_page_id,
            status="Concluido",
            logger=logger,
            log_text=log_text,
            clear_request=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
