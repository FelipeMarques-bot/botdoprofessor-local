"""Parsing deterministico das telas GeneXus do Portal Professor Online (SED/SC).

As telas do portal sao GeneXus C# e serializam grids e estado da pagina em
hidden inputs:

- ``GXState`` (JSON): estado geral (chaves tipo ``_EventName``, ``vCPF``,
  ``GridfaltasContainerData``, ...).
- ``<Grid>ContainerDataV`` (JSON list): valores das linhas do grid.
- ``<Grid>ContainerData`` (JSON string dentro do GXState): metadados de cada
  linha (colunas/campos), incluindo o nome dos inputs editaveis por aluno
  (ex: ``vALUNONOTA_0001``).

Algumas telas nao serializam o metadata no HTML (ex: notas da atividade);
nesses casos a ordem das colunas e conhecida e usada como fallback posicional.

Este modulo expoe funcoes puras (recebem o HTML bruto e retornam estruturas
python) que sao usadas tanto pelo adapter (runtime) quanto pelos testes
(sobre os HTMLs capturados em ``tests/fixtures/professor_online/``).
"""

import html as _html
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

_FIELD_NAMES = re.compile(r'\["([A-Za-z][A-Za-z0-9_]*)(?:_(\d{4}))?"')

# Escapes invalidos (ex: \&gt; que vira \> apos unescape HTML) sao removidos.
_BAD_ESCAPE = re.compile(r'\\(?![\\"/bfnrtu])')


def _unescape(s: str) -> str:
    """Desescapa entidades HTML e remove escapes JSON invalidos.

    O GXState contem sequencias como ``\\&gt;`` (barra invertida + entidade
    HTML) que, apos o unescape, gerariam ``\\>`` — escape invalido para o
    ``json.loads``. A limpeza remove a barra invertida apenas quando seguida
    de um caractere que nao e escape JSON valido.
    """
    s = _html.unescape(s)
    return _BAD_ESCAPE.sub("", s)


def _loads(raw: str) -> Any:
    """json.loads tolerante a escapes invalidos."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_unescape(raw))


def parse_gxstate(html: str) -> Optional[Dict[str, Any]]:
    """Extrai o JSON do hidden input ``GXState``."""
    m = re.search(r'<input[^>]+name="GXState"[^>]+value=\'(?P<value>.*?)\'>', html)
    if not m:
        return None
    try:
        data = _loads(m.group("value"))
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def gxstate_value(html: str, key: str, default: str = "") -> str:
    state = parse_gxstate(html) or {}
    val = state.get(key, default)
    return str(val) if val is not None else default


def span_text(html: str, field: str) -> str:
    """Le o texto de um ReadonlyAttribute renderizado como span.

    Campos desabilitados do GeneXus sao exibidos como
    ``<span id="span_vNOME">valor</span>`` (o valor fica no texto, nao no
    GXState). Ex: tipo da atividade na tela cadatividadeturma.aspx.
    """
    m = re.search(
        r'<span[^>]+id="span_%s"[^>]*>(?P<value>.*?)</span>' % re.escape(field),
        html,
        re.S,
    )
    if not m:
        return ""
    return _html.unescape(m.group("value")).strip()


def form_action(html: str) -> str:
    """Retorna a action do formulario (ex: 'cadloginprofcaptchacopy1.aspx')."""
    m = re.search(r'<form[^>]+action="([^"]+)"', html)
    return m.group(1) if m else ""


def is_login_page(html: str) -> bool:
    """True se a pagina parece a tela de login do portal."""
    return bool(re.search(r'name="vCPF"', html)) and bool(re.search(r'name="vSENHA"', html))


def is_logged_in(html: str) -> bool:
    """True se a pagina pertence a uma sessao autenticada."""
    if is_login_page(html):
        return False
    return bool(
        re.search(r'name="BUTTONLOGOUT_MPAGE"', html)
        or re.search(r'id="TEXTBLOCK2_MPAGE"', html)
    )


def find_grid_values(html: str, grid_name: str) -> Optional[List[List[Any]]]:
    """Extrai as linhas (JSON list) de ``<grid>ContainerDataV`` do HTML."""
    pattern = rf'<input[^>]+name="{re.escape(grid_name)}ContainerDataV"[^>]+value=\'(?P<value>.*?)\'>'
    m = re.search(pattern, html)
    if not m:
        return None
    raw = _unescape(m.group("value"))
    try:
        data = _loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, list) else None


def find_grid_metadata(html: str, grid_name: str) -> Optional[Dict[str, Any]]:
    """Extrai o metadata de ``<grid>ContainerData`` (string JSON no GXState).

    A estrutura retornada e o JSON da string::
        {"GridName": "...", "0": {"Props": [[campo, valor, ...], ...]}, ...}
    """
    state = parse_gxstate(html)
    if state is None:
        return None
    raw = state.get(f"{grid_name}ContainerData")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = _loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _row_props(metadata: Optional[Dict[str, Any]], row_idx: int) -> List[Any]:
    if not metadata:
        return []
    row = metadata.get(str(row_idx))
    if not isinstance(row, dict):
        return []
    props = row.get("Props", []) or []
    return props if isinstance(props, list) else []


def _prop_field(prop: Any) -> Optional[str]:
    """Nome do campo do grid (com sufixo _NNNN) a partir de um Prop."""
    if not isinstance(prop, list) or not prop:
        return None
    name = prop[0]
    return name if isinstance(name, str) else None


def parse_grid(
    html: str,
    grid_name: str,
    fallback_fields: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Combina valores + metadados do grid em uma lista de linhas.

    Cada linha retorna um dict com as chaves dos campos (com sufixo _NNNN)
    mapeadas para os valores, alem de ``suffix`` (ex: ``0001``) e ``_fields``
    (lista dos nomes reais, na ordem). Quando o metadata nao esta disponivel
    ou uma coluna e combo (prop dict, sem nome de campo), usa
    ``fallback_fields`` posicionalmente.
    """
    values = find_grid_values(html, grid_name)
    if values is None:
        return None
    metadata = find_grid_metadata(html, grid_name)

    rows: List[Dict[str, Any]] = []
    for i, row_vals in enumerate(values):
        suffix = f"{i + 1:04d}"
        props = _row_props(metadata, i)
        row_list = row_vals if isinstance(row_vals, list) else []
        if props:
            field_names = []
            for j, prop in enumerate(props):
                name = _prop_field(prop)
                if not name:
                    if fallback_fields and j < len(fallback_fields):
                        name = f"{fallback_fields[j]}_{suffix}"
                    else:
                        name = f"col{j}"
                field_names.append(name)
                m = re.search(r"_(\d{4})$", name)
                if m:
                    suffix = m.group(1)
            entry: Dict[str, Any] = {"suffix": suffix}
            for j, val in enumerate(row_list):
                name = field_names[j] if j < len(field_names) else f"col{j}"
                entry[name] = val
            entry["_fields"] = field_names
        else:
            fields = fallback_fields or []
            entry = {"suffix": suffix}
            for j, val in enumerate(row_list):
                name = f"{fields[j]}_{suffix}" if j < len(fields) else f"col{j}"
                entry[name] = val
            entry["_fields"] = [f"{f}_{suffix}" for f in fields[: len(row_list)]]
        rows.append(entry)
    return rows


def _base(entry: Dict[str, Any], *keys: str) -> str:
    """Busca a chave sem sufixo (ex: 'vALUNONOTA') em uma linha do grid.

    A linha pode conter a chave pura ('vALUNONOTA') ou a chave com sufixo
    ('vALUNONOTA_0001'); o _fields guarda os nomes reais.
    """
    fields = entry.get("_fields", []) or []
    suffix = entry.get("suffix", "")
    for key in keys:
        if key in entry:
            return str(entry[key] or "")
        with_suffix = f"{key}_{suffix}"
        if with_suffix in entry:
            return str(entry[with_suffix] or "")
        if key in fields:
            return str(entry.get(key) or "")
    return ""


def extract_turmas(html: str) -> List[Dict[str, str]]:
    """Le as turmas/disciplinas da Tela Inicial.

    Cada linha do Grid1 vira um dict com escola, matricula da turma, serie,
    sigla, turma, disciplina (nome e codigo) e o suffix usado nos links.

    Campos do grid: vDTAUECOD, vDTAUENOM, vMATCOD, vTURSIG, vTURCOD_GRID,
    vMATETAPSQ (serie), vTRMCOD (turma), vTRMDISCOD, vTRMDISNOM.
    """
    rows = parse_grid(html, "Grid1") or []
    turmas = []
    for r in rows:
        turmas.append(
            {
                "suffix": r.get("suffix", ""),
                "escola": _base(r, "vDTAUENOM"),
                "escola_cod": _base(r, "vDTAUECOD"),
                "matricula_turma": _base(r, "vMATCOD"),
                "sigla": _base(r, "vTURSIG"),
                "turma_cod": _base(r, "vTURCOD_GRID"),
                "serie": _base(r, "vMATETAPSQ"),
                "turma": _base(r, "vTRMCOD"),
                "disciplina": _base(r, "vTRMDISNOM"),
                "disciplina_cod": _base(r, "vTRMDISCOD"),
            }
        )
    return turmas


def extract_atividades(html: str) -> List[Dict[str, str]]:
    """Le as avaliacoes da turma (cadmostraratividades.aspx).

    Cada linha vira: cod, descricao, tipo, data, bimestre, suffix.
    """
    rows = parse_grid(html, "Grid1") or []
    atividades = []
    for r in rows:
        atividades.append(
            {
                "suffix": r.get("suffix", ""),
                "cod": _base(r, "ATIVIDADESCOD"),
                "descricao": _base(r, "ATIVIDADESDESCRICAO"),
                "tipo": _base(r, "TIPOSATIVIDADEDESCRICAO"),
                "data": _base(r, "ATIVIDADESDATA"),
                "bimestre": _base(r, "ATIVIDADESBIMESTRE"),
            }
        )
    return atividades


_NOTAS_FIELDS = [
    "ALUNOCOD",
    "DISCIPLINACOD",
    "vALUNONOTA_ANT",
    "vATIVIDADENOTASITUACAOANT",
    "PESAPL",
    "vALUNONOTA",
    "vATIVIDADENOTASITUACAO",
]


def extract_notas(html: str) -> List[Dict[str, str]]:
    """Le as notas da atividade (cadnotasatividades.aspx).

    Retorna por aluno: matricula, nome, nota (vALUNONOTA), situacao
    (vATIVIDADENOTASITUACAO), nota_ant, situacao_ant, suffix, e os nomes dos
    inputs editaveis (input_nota / input_situacao).
    """
    rows = parse_grid(html, "Grid1", fallback_fields=_NOTAS_FIELDS) or []
    notas = []
    for r in rows:
        notas.append(
            {
                "suffix": r.get("suffix", ""),
                "matricula": _base(r, "ALUNOCOD"),
                "nome": _base(r, "PESAPL"),
                "nota": _base(r, "vALUNONOTA"),
                "nota_ant": _base(r, "vALUNONOTA_ANT"),
                "situacao": _base(r, "vATIVIDADENOTASITUACAO"),
                "situacao_ant": _base(r, "vATIVIDADENOTASITUACAOANT"),
                "input_nota": f"vALUNONOTA_{r.get('suffix', '')}",
                "input_situacao": f"vATIVIDADENOTASITUACAO_{r.get('suffix', '')}",
            }
        )
    return notas


def extract_chamada(html: str) -> List[Dict[str, str]]:
    """Le a grade de chamada do dia (cadfaltaschamadaemsala.aspx).

    Retorna por aluno: matricula, nome, faltas_ant (vFALTAANT), presenca
    (vD1), input_presenca (vD1_XXXX), suffix.
    """
    rows = parse_grid(html, "Gridfaltas") or []
    chamada = []
    for r in rows:
        chamada.append(
            {
                "suffix": r.get("suffix", ""),
                "matricula": _base(r, "ALUNOCOD"),
                "nome": _base(r, "PESAPL"),
                "faltas_ant": _base(r, "vFALTAANT"),
                "presenca": _base(r, "vD1"),
                "input_presenca": f"vD1_{r.get('suffix', '')}",
            }
        )
    return chamada


_DIARIO_FIELDS = [
    "DISCIPLINACOD",
    "DIACONTEUDO",
    "vIMAGE",
    "AULADADA",
    "vTOTAULAS",
    "CONTEUDODIADESCRICAO",
    "vEDITAR",
    "vEXCLUIR",
]


def extract_diario(html: str) -> List[Dict[str, str]]:
    """Le o diario de classe (cadmostrarconteudosdiarios.aspx).

    Retorna por dia: data (DIACONTEUDO), situacao (AULADADA), total_aulas
    (vTOTAULAS), conteudo (CONTEUDODIADESCRICAO), input_situacao
    (AULADADA_XXXX), suffix.
    """
    rows = parse_grid(html, "Grid2", fallback_fields=_DIARIO_FIELDS) or []
    diario = []
    for r in rows:
        diario.append(
            {
                "suffix": r.get("suffix", ""),
                "data": _base(r, "DIACONTEUDO"),
                "situacao": _base(r, "AULADADA"),
                "total_aulas": _base(r, "vTOTAULAS"),
                "conteudo": _base(r, "CONTEUDODIADESCRICAO"),
                "input_situacao": f"AULADADA_{r.get('suffix', '')}",
            }
        )
    return diario


def extract_faltas_mes(html: str) -> Dict[str, Any]:
    """Le as faltas do mes (cadfaltasmesnovo.aspx).

    Retorna dict com: periodo, data_inicio, data_fim, e uma lista de alunos
    onde cada entrada mapeia a coluna de data (vD1..vDN) para o valor
    ('C' presente, '1F'/'2F' falta, '1J'/'2J' justificada, '-' nao enturmado)
    e o total de faltas (vFALTAS).
    """
    state = parse_gxstate(html) or {}
    rows = parse_grid(html, "Gridfaltas") or []
    alunos = []
    for r in rows:
        fields = r.get("_fields", []) or []
        colunas = {}
        for fname in fields:
            m = re.match(r"^(vD\d+)_", fname)
            if m:
                colunas[m.group(1)] = str(r.get(fname, "") or "")
        alunos.append(
            {
                "suffix": r.get("suffix", ""),
                "matricula": _base(r, "ALUNOCOD"),
                "nome": _base(r, "PESAPL"),
                "colunas": colunas,
                "total_faltas": _base(r, "vFALTAS"),
            }
        )
    return {
        "periodo": str(state.get("vNOMEPERIODO", "") or ""),
        "data_inicio": str(state.get("vDATAINICIO", "") or ""),
        "data_fim": str(state.get("vDATAFIM", "") or ""),
        "alunos": alunos,
    }


_PLANEJAMENTO_FIELDS = [
    "PLANEJAMENTOSEMDATAINICIO",
    "PLANEJAMENTOSEMDATAFIM",
    "PLANEJSEMANALOBSERVACAO",
    "PLANEJSEMANALARQUIVOPDF",
    "PLANEJAMENTOSEMANALSEMARQUIVO",
    "vPLANEJAMENTOSEMANALVIGENTE",
    "vEDITAR",
    "vEXCLUIR",
    "vVIGENCIA",
    "PLANEJAMENTOSEMANALID",
    "PLANEJSEMANALEXTENSAO",
    "PLANEJSEMANALNOMEARQUIVO",
]


def extract_planejamentos(html: str) -> List[Dict[str, str]]:
    """Le os planejamentos semanais (cadmostrarplanejamentosemanal.aspx).

    Retorna por planejamento: data_inicio, data_fim, observacao, pdf_url,
    situacao (vPLANEJAMENTOSEMANALVIGENTE), sem_arquivo, suffix.
    """
    rows = parse_grid(html, "Grid1", fallback_fields=_PLANEJAMENTO_FIELDS) or []
    result = []
    for r in rows:
        result.append(
            {
                "suffix": r.get("suffix", ""),
                "data_inicio": _base(r, "PLANEJAMENTOSEMDATAINICIO"),
                "data_fim": _base(r, "PLANEJAMENTOSEMDATAFIM"),
                "observacao": _base(r, "PLANEJSEMANALOBSERVACAO"),
                "pdf_url": _base(r, "PLANEJSEMANALARQUIVOPDF"),
                "situacao": _base(r, "vPLANEJAMENTOSEMANALVIGENTE"),
                "sem_arquivo": _base(r, "PLANEJAMENTOSEMANALSEMARQUIVO"),
            }
        )
    return result


_PLANEJAMENTO_ANUAL_FIELDS = [
    "DATINCCONTEUDOPROGRAMATICO",
    "CONTEUDOPROGOBSERVACAO",
    "CONTEUDOPROGRAMATICOVERSAO",
    "CONTEUDOPROGVIGENTE",
    "CONTEUDOPROGARQUIVOPDF",
    "vEDITAR",
    "CONTEUDOPROGEXTENSAO",
    "CONTEUDOPROGNOMEARQUIVO",
]


def extract_planejamento_anual(html: str) -> List[Dict[str, str]]:
    """Le o planejamento anual (cadmostrarconteudoprog.aspx)."""
    rows = parse_grid(html, "Grid1", fallback_fields=_PLANEJAMENTO_ANUAL_FIELDS) or []
    result = []
    for r in rows:
        result.append(
            {
                "suffix": r.get("suffix", ""),
                "data": _base(r, "DATINCCONTEUDOPROGRAMATICO"),
                "observacao": _base(r, "CONTEUDOPROGOBSERVACAO"),
                "versao": _base(r, "CONTEUDOPROGRAMATICOVERSAO"),
                "situacao": _base(r, "CONTEUDOPROGVIGENTE"),
                "pdf_url": _base(r, "CONTEUDOPROGARQUIVOPDF"),
            }
        )
    return result


def atividade_matches(descricao: str, alvo: str) -> bool:
    """Compara descricao da atividade com o alvo ignorando acentos/caixa."""
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s or "")
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.replace("º", "o").replace("°", "o").replace("ª", "a")
        return re.sub(r"[^a-z0-9 ]", "", s.lower())

    alvo_norm = norm(alvo)
    if not alvo_norm:
        return False
    desc_norm = norm(descricao)
    return desc_norm == alvo_norm or alvo_norm in desc_norm or desc_norm in alvo_norm
