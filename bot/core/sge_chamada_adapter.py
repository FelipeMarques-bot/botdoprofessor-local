"""Adapter deterministico para lancamento de chamada diaria por foto no SGE.

Le a grade de frequencia (Frequencia por Turma - hdisturfrealunopaginado.aspx),
compara com a leitura IA da foto do diario de classe e preenche apenas os
alunos/dias ainda nao lancados (indicador _FEITA_ = Green.gif).

Estrutura conhecida da pagina (GeneXus):
  - Seletor do dia:     <select name="_DATA">   (option value = YYYY/MM/DD)
  - Linha do aluno i:   input hidden  _ALUNOM_XXXX        (nome)
                        input hidden  _ALUMAT_XXXX        (matricula)
                        select        _DISALUDIAFALTA_XXXX      (0=* .. 5)
                        select        _DISALUMOTIVOFALTA_XXXX   (0=Presente, 1=Atestado
                                                        Medico, 2=Injustificada, ...)
                        img           _FEITA_XXXX         (Red.gif = SEM registro,
                                                        Green.gif = COM registro)
                        link          _FALTA_XXXX         (Descrever Motivo da Falta)
  - Salvar:             BTNCONFIRMAR / BTNCONFIRMARVOLTAR / BTNVOLTAR
  - Paginacao:          BTNPRIMEIRO/BTNANTERIOR/BTNSEGUINTE/BTNULTIMO (_ATUAL/_FINAL)

Uso (foto ja lida pela IA em chamada_foto):
    adapter = SGEChamadaAdapter()
    adapter.login(cpf, senha)
    adapter.navegar_para_frequencia(contexto)
    grade = adapter.ler_grade()
    plano = montar_plano(grade, chamada_foto)
    resultado = adapter.aplicar_plano(plano)
    adapter.salvar()
"""

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from playwright.sync_api import Page
except ImportError:  # pragma: no cover
    Page = None

ACTION_TIMEOUT_MS = 5000
NAV_TIMEOUT_MS = 20000

# Codigos do select _DISALUMOTIVOFALTA_XXXX do SGE.
MOTIVO_FALTA: Dict[str, str] = {
    "0": "Presente",
    "1": "Atestado Medico",
    "2": "Injustificada",
    "3": "Atividade Extra Classe",
    "4": "Falta Justificada",
    "5": "Atendimento Especializado",
    "6": "Feriado",
    "7": "Atestado de Obituario",
    "8": "Declaracao Comparecimento",
    "9": "Atraso",
    "10": "Sem Registro",
    "11": "Suspensao Escolar",
    "96": "Atividade Remota (NC)",
    "97": "Aula Remota (NC)",
}

# Motivos de falta justificada suportados pelo leitor IA da foto.
# Chave -> codigo no select _DISALUMOTIVOFALTA.
MOTIVO_JUSTIFICADO: Dict[str, str] = {
    "atestado_medico": "1",
    "obito": "7",
    "suspensao": "11",
    "falta_justificada": "4",
    "atividade_extra_classe": "3",
}


@dataclass
class ChamadaContexto:
    escola: str = ""
    etapa: str = ""
    turno: str = ""
    disciplina: str = ""
    dia: str = ""  # YYYY/MM/DD


@dataclass
class RegistroAluno:
    indice: str
    nome: str
    matricula: str = ""
    situacao: str = ""
    faltas: str = "0"
    motivo: str = "0"
    motivo_nome: str = "Presente"
    ja_lancado: bool = False

    @property
    def chave(self) -> str:
        return f"{self.indice}_{self.nome}"


@dataclass
class ItemPlano:
    aluno: RegistroAluno
    acao: str = "pular"  # pular | presenca | falta
    motivo: str = ""     # codigo do motivo (somente acao=falta)
    motivo_nome: str = ""
    faltas: int = 1
    descricao: str = ""


@dataclass
class ResultadoLancamento:
    success: bool = True
    mensagem: str = ""
    ja_lancados: int = 0
    presentes: int = 0
    faltas: int = 0
    pulados: int = 0
    sem_match: List[str] = field(default_factory=list)
    nao_encontrados: List[str] = field(default_factory=list)


def _html_unescape(texto: str) -> str:
    return html.unescape(texto or "")


def normalizar_nome(nome: str) -> str:
    """Normaliza nome para comparacao tolerante (maiusculas, sem acentos)."""
    nome = _html_unescape(nome or "").upper()
    nome = unicodedata.normalize("NFD", nome)
    nome = "".join(c for c in nome if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", nome).strip()


def _valor_select(page: Page, seletor: str) -> str:
    try:
        loc = page.locator(seletor)
        if loc.count() == 0:
            return ""
        return (loc.first.input_value() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


class SGEChamadaAdapter:
    """Navegacao e manipulacao da grade de frequencia do SGE."""

    def __init__(self, page: Optional[Page] = None):
        self._page = page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Página do Playwright não foi fornecida")
        return self._page

    # ------------------------------------------------------------------ #
    # Contexto
    # ------------------------------------------------------------------ #
    def detectar_contexto(self) -> ChamadaContexto:
        """Le os campos ocultos de contexto da pagina de frequencia."""
        p = self.page
        ctx = ChamadaContexto()
        ctx.escola = _html_unescape(p.locator("input[name='_UENOM']").input_value() if p.locator("input[name='_UENOM']").count() else "")
        ctx.etapa = _html_unescape(p.locator("input[name='_ETAPADES']").input_value() if p.locator("input[name='_ETAPADES']").count() else "")
        ctx.turno = _html_unescape(p.locator("input[name='_TRNDESC']").input_value() if p.locator("input[name='_TRNDESC']").count() else "")
        ctx.disciplina = _html_unescape(p.locator("input[name='_DISCODNOM']").input_value() if p.locator("input[name='_DISCODNOM']").count() else "")
        try:
            dia = _valor_select(p, "select[name='_DATA']")
            if dia:
                ctx.dia = dia
        except Exception:  # noqa: BLE001
            pass
        return ctx

    # ------------------------------------------------------------------ #
    # Leitura da grade
    # ------------------------------------------------------------------ #
    def _ler_pagina_grade(self) -> List[RegistroAluno]:
        """Le todos os alunos visiveis na pagina atual (uma pagina da grade)."""
        p = self.page
        registros: List[RegistroAluno] = []
        nome_inputs = p.locator("input[name^='_ALUNOM_']")
        total = nome_inputs.count()
        for i in range(total):
            nome_el = nome_inputs.nth(i)
            name_attr = (nome_el.get_attribute("name") or "").strip()
            m = re.search(r"_ALUNOM_(\d+)$", name_attr)
            if not m:
                continue
            idx = m.group(1)
            nome = _html_unescape(nome_el.input_value() or "").strip()
            if not nome:
                continue

            matricula = ""
            loc = p.locator(f"input[name='_ALUMAT_{idx}']")
            if loc.count():
                matricula = (loc.first.input_value() or "").strip()

            situacao = ""
            loc = p.locator(f"input[name='_SITALUDD_{idx}']")
            if loc.count():
                situacao = _html_unescape(loc.first.input_value() or "").strip()

            faltas = _valor_select(p, f"select[name='_DISALUDIAFALTA_{idx}']")
            motivo = _valor_select(p, f"select[name='_DISALUMOTIVOFALTA_{idx}']")
            motivo_nome = MOTIVO_FALTA.get(motivo, "")

            ja_lancado = False
            img = p.locator(f"img[id='_FEITA_{idx}']")
            if img.count():
                src = (img.first.get_attribute("src") or "") + " " + (img.first.get_attribute("name") or "")
                if "green" in src.lower():
                    ja_lancado = True
            else:
                hidden = p.locator(f"input[name='GXimg_FEITA_{idx}']")
                if hidden.count() and "green" in (hidden.first.input_value() or "").lower():
                    ja_lancado = True

            registros.append(RegistroAluno(
                indice=idx, nome=nome, matricula=matricula,
                situacao=situacao, faltas=faltas, motivo=motivo,
                motivo_nome=motivo_nome, ja_lancado=ja_lancado,
            ))
        return registros

    def ler_grade(self) -> List[RegistroAluno]:
        """Le toda a grade, atravessando a paginacao quando existir."""
        registros: List[RegistroAluno] = []
        vistos: set = set()
        guarda_paginas = 0

        while True:
            pagina = self._ler_pagina_grade()
            novos = [r for r in pagina if r.chave not in vistos]
            registros.extend(novos)
            vistos.update(r.chave for r in novos)

            atual = _valor_select(self.page, "input[name='_ATUAL']")
            final = _valor_select(self.page, "input[name='_FINAL']")
            if not atual or not final or atual >= final or guarda_paginas >= 10:
                break
            guarda_paginas += 1
            btn = self.page.locator("input[name='BTNSEGUINTE']")
            if btn.count() == 0:
                break
            try:
                btn.first.click(timeout=ACTION_TIMEOUT_MS)
                self.page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                break

        return registros

    # ------------------------------------------------------------------ #
    # Selecao do dia
    # ------------------------------------------------------------------ #
    def selecionar_dia(self, dia: str) -> bool:
        """Seleciona o dia no select _DATA (valor YYYY/MM/DD) e recarrega."""
        p = self.page
        sel = p.locator("select[name='_DATA']")
        if sel.count() == 0:
            return False
        opcoes = sel.locator("option")
        existe = False
        for i in range(opcoes.count()):
            if (opcoes.nth(i).get_attribute("value") or "") == dia:
                existe = True
                break
        if not existe:
            return False
        sel.select_option(dia)
        try:
            p.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception:  # noa: BLE001
            pass
        p.wait_for_timeout(400)
        return True


# ---------------------------------------------------------------------- #
# Logica de diff: grade atual (SGE) vs leitura da foto (IA)
# ---------------------------------------------------------------------- #
def _score_aluno(sge: RegistroAluno, foto_nome: str) -> int:
    """Pontua o quanto o nome da foto casa com o aluno do SGE.

    Retorna >= 1 quando casa:
      - nome completo igual (score alto);
      - um nome contem o outro;
      - todos os tokens (palavras) do nome mais curto estao no mais longo
        (ex.: foto 'GUILHERME MAAS' vs SGE 'GUILHERME HENRIQUE MAAS').
    Retorna 0 quando nao casa.
    """
    a = normalizar_nome(sge.nome)
    b = normalizar_nome(foto_nome)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a in b or b in a:
        return 60
    ta, tb = a.split(), b.split()
    curto, longo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(curto) < 2:
        return 0
    if all(c in longo for c in curto):
        return 40 + len(curto)
    # Primeira e ultima palavra coincidem e o curto tem >= 3 tokens.
    if len(curto) >= 3 and curto[0] == longo[0] and curto[-1] == longo[-1]:
        return 20 + len(curto)
    return 0


def montar_plano(
    grade: List[RegistroAluno],
    chamada_foto: List[Dict[str, Any]],
) -> List[ItemPlano]:
    """Compara a leitura da foto com o estado atual do SGE e monta o plano.

    Regras:
      - Aluno com _FEITA_ = Green.gif (ja lancado) -> pular (nao repreenche).
      - Aluno da foto marcado presente -> presenca (nada a alterar, salvar abre o dia).
      - Aluno da foto marcado falta -> falta com motivo (padrao Injustificada).
      - Aluno da foto com falta justificada -> motivo especifico + descricao.
      - Nome da foto sem match na grade -> sem_match (lista para revisao).

    chamada_foto: lista de dicts com chaves:
        aluno, situacao (presente|falta|falta_justificada),
        motivo (chave de MOTIVO_JUSTIFICADO, opcional), faltas (int, default 1),
        descricao (opcional).
    """
    plano: List[ItemPlano] = []
    nao_encontrados: List[str] = []

    por_foto = list(chamada_foto or [])
    usados_foto: set = set()

    for sge in grade:
        if sge.ja_lancado:
            plano.append(ItemPlano(aluno=sge, acao="pular"))
            continue

        melhor: Optional[Dict[str, Any]] = None
        melhor_score = 0
        melhor_idx = -1
        for j, f in enumerate(por_foto):
            if j in usados_foto:
                continue
            score = _score_aluno(sge, f.get("aluno", ""))
            if score > melhor_score:
                melhor = f
                melhor_score = score
                melhor_idx = j
        if melhor is None or melhor_idx < 0:
            plano.append(ItemPlano(aluno=sge, acao="pular"))
            continue

        usados_foto.add(melhor_idx)
        situacao = (melhor.get("situacao") or "presente").strip().lower()
        if situacao in ("falta_justificada", "justificada"):
            motivo = str(melhor.get("motivo") or "falta_justificada")
            codigo = MOTIVO_JUSTIFICADO.get(motivo, MOTIVO_JUSTIFICADO["falta_justificada"])
            plano.append(ItemPlano(
                aluno=sge, acao="falta", motivo=codigo,
                motivo_nome=MOTIVO_FALTA.get(codigo, ""),
                faltas=int(melhor.get("faltas") or 1),
                descricao=str(melhor.get("descricao") or ""),
            ))
        elif situacao in ("falta", "ausente", "faltou"):
            plano.append(ItemPlano(
                aluno=sge, acao="falta", motivo="2",
                motivo_nome=MOTIVO_FALTA["2"],
                faltas=int(melhor.get("faltas") or 1),
                descricao=str(melhor.get("descricao") or ""),
            ))
        else:
            plano.append(ItemPlano(aluno=sge, acao="presenca"))

    # Nomes da foto que nao casaram com nenhum aluno da grade.
    for j, f in enumerate(por_foto):
        if j not in usados_foto:
            nao_encontrados.append(str(f.get("aluno") or "").strip())

    return plano


def _resumo_plano(plano: List[ItemPlano]) -> Dict[str, int]:
    resumo = {"ja_lancados": 0, "presentes": 0, "faltas": 0, "pulados": 0}
    for item in plano:
        if item.acao == "pular":
            if item.aluno.ja_lancado:
                resumo["ja_lancados"] += 1
            else:
                resumo["pulados"] += 1
        elif item.acao == "presenca":
            resumo["presentes"] += 1
        elif item.acao == "falta":
            resumo["faltas"] += 1
    return resumo


class SGEChamadaExecutor(SGEChamadaAdapter):
    """Executa o plano de lancamento na pagina de frequencia."""

    def aplicar_plano(self, plano: List[ItemPlano]) -> ResultadoLancamento:
        p = self.page
        res = ResultadoLancamento()

        for item in plano:
            idx = item.aluno.indice
            if item.acao == "pular":
                if item.aluno.ja_lancado:
                    res.ja_lancados += 1
                else:
                    res.pulados += 1
                continue
            if item.acao == "presenca":
                # Chamada total de presenca: nao altera selects; salvar abre o dia.
                res.presentes += 1
                continue
            if item.acao == "falta":
                faltas_sel = p.locator(f"select[name='_DISALUDIAFALTA_{idx}']")
                motivo_sel = p.locator(f"select[name='_DISALUMOTIVOFALTA_{idx}']")
                if faltas_sel.count():
                    faltas_sel.select_option(str(item.faltas))
                if motivo_sel.count():
                    motivo_sel.select_option(item.motivo)
                res.faltas += 1

                # Descricao do motivo (falta justificada). Requer o popup
                # capturado com gravar_chamada.py (TODO: preencher campos reais).
                if item.descricao:
                    self._preencher_descricao_motivo(idx, item.descricao)

        res.mensagem = (
            f"{res.presentes} presentes, {res.faltas} falta(s), "
            f"{res.ja_lancados} ja lancado(s), {res.pulados} sem registro na foto."
        )
        return res

    def _preencher_descricao_motivo(self, indice: str, descricao: str) -> None:
        """Abre o popup de descricao de motivo e grava a justificativa.

        NOTA: a estrutura do popup ainda nao foi capturada (clicar no link
        _FALTA_XXXX nao muda a URL). Capturar com gravar_chamada.py e
        preencher os seletores reais aqui.
        """
        p = self.page
        link = p.locator(f"a[name='_FALTA_{indice}']")
        if link.count() == 0:
            link = p.locator(f"img[name='_FALTA_{indice}']")
        if link.count() == 0:
            return
        try:
            link.first.click(timeout=ACTION_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            return

    def salvar(self, voltar: bool = False) -> bool:
        """Clica em Confirmar (ou Confirmar e Voltar)."""
        nome = "BTNCONFIRMARVOLTAR" if voltar else "BTNCONFIRMAR"
        btn = self.page.locator(f"input[name='{nome}']")
        if btn.count() == 0:
            return False
        try:
            btn.first.click(timeout=ACTION_TIMEOUT_MS)
            self.page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            return True
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------- #
# Helpers de navegacao (texto) reutilizados do lancar_notas_sge
# ---------------------------------------------------------------------- #
def _clicar_texto(p: Page, texto: str) -> bool:
    for loc in (
        p.get_by_role("button", name=texto),
        p.get_by_role("link", name=texto),
        p.get_by_text(texto, exact=False),
    ):
        try:
            if loc.count() > 0:
                loc.first.click(timeout=ACTION_TIMEOUT_MS)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def navegar_para_frequencia(p: Page, contexto: ChamadaContexto) -> bool:
    """Navega da posicao atual (logado) ate a pagina de frequencia da turma.

    Fluxo: escola -> turma/disciplina -> Frequencia.
    O passo turma->Frequencia depende da estrutura da lista de turmas, que
    ainda sera confirmada com a gravacao (gravar_chamada.py).
    """
    if contexto.escola:
        _clicar_texto(p, contexto.escola)
        try:
            p.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass

    for texto in ("Frequência", "Frequencia", "Chamada", "Diário", "Diario"):
        if _clicar_texto(p, texto):
            try:
                p.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                pass
            return True
    return False
