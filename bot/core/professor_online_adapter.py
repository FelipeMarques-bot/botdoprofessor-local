"""Adapter para o Portal Professor Online (SED/SC).

URL: https://professoronline.sed.sc.gov.br (login em CadLoginProfCaptchaCopy1.aspx)

As telas sao GeneXus C#: os grids sao serializados em hidden inputs
(``GXState``, ``<Grid>ContainerDataV``) e renderizados via JS. A navegacao
entre telas usa links ``javascript:gx.evt.execEvt('<EVENTO>.<suffix>',this)``
(clickevent de cada linha/campo) e itens de menu com URLs ``*.aspx``.

Fluxos suportados (parser em ``professor_online_parser.py``):

- Login (CPF + senha) com deteccao de sucesso/falha/captcha.
- Selecao da turma na Tela Inicial (Grid1, evento ``E'SELECIONA'.<suffix>``).
- Avaliacoes da turma (cadmostraratividades.aspx): encontrar atividade e
  abrir a tela de notas (evento ``E'NOTAS'.<suffix>``).
- Notas da atividade (cadnotasatividades.aspx): ler, preencher
  ``vALUNONOTA_<suffix>`` e confirmar (``CONFIRMAR``).
- Chamada diaria (cadfaltaschamadaemsala.aspx): ler e preencher
  ``vD1_<suffix>``, confirmar (``BTN_CONFIRMAR``).
- Diario de classe (cadmostrarconteudosdiarios.aspx): ler e ajustar
  ``AULADADA_<suffix>`` (situacao Confirmada/Agendada/Sem aula/Extra).
- Planejamentos semanal/anual: leitura (Grids).
"""

import os
import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Callable
from bot.core.portal_adapter import (
    PortalAdapter, PortalContext, LessonPlan,
)
from bot.core.portal_memory import PortalMemory
from bot.core import professor_online_parser as p

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    sync_playwright = None


class ProfessorOnlineAdapter(PortalAdapter):
    """Adapter para o Portal Professor Online (SED/SC)."""

    NAV_TIMEOUT = 25000
    ACTION_TIMEOUT = 6000
    BASE_URL = "https://professoronline.sed.sc.gov.br"
    LOGIN_PATH = "CadLoginProfCaptchaCopy1.aspx"
    HOME_PATH = "telainicial.aspx"
    AVALIACOES_PATH = "cadmostraratividades.aspx"
    NOTAS_PATH = "cadnotasatividades.aspx"
    CHAMADA_PATH = "cadfaltaschamadaemsala.aspx"
    FALTAS_MES_PATH = "cadfaltasmesnovo.aspx"
    DIARIO_PATH = "cadmostrarconteudosdiarios.aspx"
    PLANEJAMENTOS_PATH = "cadmostrarplanejamentosemanal.aspx"
    PLANEJAMENTO_ANUAL_PATH = "cadmostrarconteudoprog.aspx"

    # Situacoes do diario de classe: valor -> rotulo (fixture diarios_de_classe).
    DIARIO_SITUACOES = {"1": "Confirmada", "2": "Agendada", "3": "Sem aula", "4": "Extra"}

    def __init__(self, base_url: str = ""):
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        m = re.search(r"\.(?:aspx?|php|html?)$", self._base_url.rsplit("/", 1)[-1], re.IGNORECASE)
        if m:
            self._base_url = self._base_url.rsplit("/", 1)[0]
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._pw = None
        self._headless = False
        self.memory = PortalMemory("ProfessorOnline")
        self._logged_in = False
        self._current_url = ""
        self._turmas: List[Dict[str, str]] = []

    # ------------------------------------------------------------------ #
    #  Navegador                                                          #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "Professor Online"

    @property
    def url(self) -> str:
        return self._base_url

    def start(self, headless: bool = False):
        if sync_playwright is None:
            raise RuntimeError("Playwright nao instalado")
        self._headless = headless
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.NAV_TIMEOUT)

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            self.start()
        return self._page

    def _goto(self, path: str) -> None:
        url = path if path.startswith("http") else f"{self._base_url}/{path}"
        self.page.goto(url, timeout=self.NAV_TIMEOUT, wait_until="domcontentloaded")
        self._current_url = self.page.url

    def _html(self) -> str:
        try:
            return self.page.content()
        except Exception:
            return ""

    def _wait_settle(self, ms: int = 1200) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:
            pass

    def _wait_network_idle(self, ms: int = 8000) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=ms)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Login                                                              #
    # ------------------------------------------------------------------ #

    def login(self, cpf: str, senha: str, log: Optional[Callable[[str], None]] = None) -> bool:
        p_ = self.page
        try:
            self._goto(self.LOGIN_PATH)
        except Exception:
            pass
        self._wait_settle(800)

        html = self._html()
        if p.is_login_page(html):
            try:
                cpf_f = p_.locator("input[name='vCPF']")
                senha_f = p_.locator("input[name='vSENHA']")
                cpf_f.fill(cpf, timeout=self.ACTION_TIMEOUT)
                senha_f.fill(senha, timeout=self.ACTION_TIMEOUT)
                cpf_f.dispatch_event("change")
                cpf_f.dispatch_event("blur")
                senha_f.dispatch_event("change")
                senha_f.dispatch_event("blur")
                self._wait_settle(700)
                if log:
                    v_cpf = cpf_f.input_value()
                    log(f"[ProfessorOnline] CPF preenchido: {len(v_cpf)} digitos")
                btn = p_.locator("input[name='BUTTON1']")
                if btn.count() == 0:
                    btn = p_.locator("input[value*='Entrar' i]")
                if btn.count() > 0:
                    btn.first.click(timeout=self.ACTION_TIMEOUT)
            except Exception as exc:
                self.memory.record_failure("login", cpf, f"erro_preenchimento={exc}")
                return False

        self._wait_network_idle()
        self._wait_settle(1500)

        html = self._html()
        self._logged_in = p.is_logged_in(html)

        if self._logged_in:
            self._current_url = self.page.url
            self._turmas = p.extract_turmas(html)
            self.memory.record_success("login", self._base_url)
            if log:
                log(f"[ProfessorOnline] Login OK. Turmas no grid: {len(self._turmas)}. {self._resumo_pagina()}")
            return True

        # Falhou: identifica motivo (captcha, credenciais, sessao).
        motivo = self._login_failure_reason(html)
        if motivo == "captcha":
            msg = (
                "Captcha detectado no login. Se o navegador estiver VISIVEL, "
                "complete o captcha e clique em Entrar dentro de 5 minutos."
            )
            if log:
                log(f"[ProfessorOnline] {msg}")
            else:
                print(f"[ProfessorOnline] {msg}")
            if not self._headless:
                for i in range(150):
                    time.sleep(2)
                    html = self._html()
                    if p.is_logged_in(html):
                        self._logged_in = True
                        self._turmas = p.extract_turmas(html)
                        self.memory.record_success("login", self._base_url)
                        return True
                    if i % 15 == 0 and log:
                        log(f"[ProfessorOnline] Aguardando voce completar o captcha... ({(i + 1) * 2}s)")
                if log:
                    log("[ProfessorOnline] Tempo esgotado aguardando o captcha manual.")
                motivo = "captcha_tempo_esgotado"
        self.memory.record_failure("login", cpf, f"{motivo} url={self._current_url}")
        try:
            shot = self._capture()
            if shot and log:
                log(f"[ProfessorOnline] Screenshot: {shot}")
        except Exception:
            pass
        return False

    def _capture(self) -> Optional[str]:
        """Salva um screenshot da pagina atual em artifacts/screenshots."""
        try:
            base = os.path.join(
                os.path.expanduser("~"), ".bot_local", "artifacts", "screenshots"
            )
            os.makedirs(base, exist_ok=True)
            path = os.path.join(
                base, f"po_login_falha_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
            )
            self.page.screenshot(path=path)
            return path
        except Exception:
            return None

    def _login_failure_reason(self, html: str) -> str:
        if p.is_login_page(html):
            err = re.search(r"id=\"gxErrorViewer\"[^>]*>(.*?)</span>", html, re.S)
            msg = re.sub(r"<[^>]+>", "", err.group(1)) if err else ""
            msg = msg.strip()
            if re.search(r"recaptcha|hcaptcha|g-recaptcha|name=\"vCAPTCHA\"|id=\"g-recaptcha\"", html, re.I):
                return "captcha"
            if msg:
                return f"erro_apresentado={msg[:120]}"
            return "nao_logado"
        return "sessao_indeterminada"

    def _resumo_pagina(self) -> str:
        """Texto visivel + URL da pagina atual (para diagnosticos)."""
        try:
            url = self.page.url
            txt = self.page.locator("body").inner_text(timeout=3000)
            txt = re.sub(r"\s+", " ", txt or "").strip()
            return f"url={url} texto='{txt[:220]}'"
        except Exception:
            return f"url={getattr(self, '_current_url', '')} texto='<erro ao ler>'"

    def is_logged_in(self) -> bool:
        return self._logged_in and p.is_logged_in(self._html())

    def _logout(self) -> None:
        try:
            btn = self.page.locator("input[name='BUTTONLOGOUT_MPAGE']")
            if btn.count() > 0:
                btn.first.click(timeout=self.ACTION_TIMEOUT)
                self._wait_settle(1000)
        except Exception:
            pass
        self._logged_in = False

    # ------------------------------------------------------------------ #
    #  Navegacao                                                          #
    # ------------------------------------------------------------------ #

    def _confirmar_periodo(self) -> bool:
        """Se a pagina for 'Selecao de Periodo', clica em Continuar (BTNCONFIRMAR)."""
        try:
            html = self._html()
            if "Grid1ContainerDataV" in html:
                return False
            btn = self.page.locator("input[name='BTNCONFIRMAR']")
            if btn.count() == 0:
                return False
            btn.first.click(timeout=self.ACTION_TIMEOUT)
            self._wait_network_idle()
            self._wait_settle(1500)
            return True
        except Exception:
            return False

    def navigate_to(self, context: PortalContext) -> bool:
        """Seleciona a turma (escola/turma) na Tela Inicial.

        Entra na telainicial.aspx, le as turmas do Grid1 e clica no link
        ``E'SELECIONA'.<suffix>`` da linha que corresponde a escola e turma
        informadas. Depois navega para a tela de avaliacoes da turma.
        """
        p_ = self.page
        if not self._logged_in:
            return False

        try:
            self._goto(self.HOME_PATH)
            self._wait_network_idle()
            self._wait_settle(1200)
        except Exception:
            pass

        html = self._html()
        turmas = p.extract_turmas(html)
        self._turmas = turmas
        if not turmas:
            if self._confirmar_periodo():
                html = self._html()
                turmas = p.extract_turmas(html)
                self._turmas = turmas
        if not turmas:
            self.memory.record_failure(
                "navigate_to", context.turma,
                f"grid_sem_turmas {self._resumo_pagina()} "
                f"grid_no_html={'Grid1ContainerDataV' in html}",
            )
            return False

        alvo = self._match_turma(turmas, context)
        if alvo is None:
            self.memory.record_failure(
                "navigate_to", context.turma,
                f"turma_nao_encontrada turmas={[t['turma'] for t in turmas]}",
            )
            return False

        suffix = alvo["suffix"]
        if not self._fire_event("SELECIONA", suffix):
            self.memory.record_failure("navigate_to", context.turma, f"click_event_sufixo={suffix}")
            return False

        self._wait_network_idle()
        self._wait_settle(1500)

        self.memory.record_navigation(
            f"{context.escola}/{context.turma}",
            self.page.url,
        )
        return True

    @staticmethod
    def _match_turma(turmas: List[Dict[str, str]], context: PortalContext) -> Optional[Dict[str, str]]:
        """Encontra a linha do Grid1 correspondente ao contexto.

        Casa por escola + turma. A turma pode vir como codigo (ex: "201")
        ou como ano/serie (ex: "3º Ano", "3 - SÉRIE"). Retorna a primeira
        linha (disciplina) que casa.
        """
        norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731

        def num(s: str) -> str:
            m = re.search(r"\d+", s or "")
            return m.group(0) if m else ""

        alvo_norm = norm(context.turma)
        alvo_num = num(context.turma)
        escola_alvo = norm(context.escola)
        cands = []
        for t in turmas:
            serie = norm(t.get("serie", ""))
            turma = norm(t.get("turma", ""))
            ok_turma = (not alvo_norm) or (
                alvo_norm in turma
                or alvo_norm in serie
                or (alvo_num and alvo_num in serie)
                or (alvo_num and alvo_num in turma)
            )
            ok_escola = not escola_alvo or escola_alvo in norm(t.get("escola", ""))
            if ok_turma and ok_escola:
                cands.append(t)
        if not cands:
            return None
        # Prefere linha cuja escola casa exatamente, senao a primeira.
        if escola_alvo:
            for t in cands:
                if escola_alvo == norm(t.get("escola", "")):
                    return t
        return cands[0]

    def _navigate_menu_path(self, path: str) -> bool:
        """Navega para uma tela do menu por URL direta."""
        if not self._logged_in:
            return False
        try:
            self._goto(path)
            self._wait_network_idle()
            self._wait_settle(1200)
            return p.is_logged_in(self._html())
        except Exception as exc:
            self.memory.record_failure("navigate", path, str(exc))
            return False

    # ------------------------------------------------------------------ #
    #  Avaliacoes / Notas                                                 #
    # ------------------------------------------------------------------ #

    def find_assessment(self, atividade: str) -> Optional[Dict]:
        """Abre a tela de notas da atividade que casa com ``atividade``.

        Navega para as avaliacoes da turma, localiza a atividade pela
        descricao (ignorando acentos/caixa) e clica no evento ``E'NOTAS'``
        da linha, que abre cadnotasatividades.aspx direto.
        """
        if not self._navigate_menu_path(self.AVALIACOES_PATH):
            return None

        html = self._html()
        atividades = p.extract_atividades(html)
        alvo = None
        for a in atividades:
            if p.atividade_matches(a.get("descricao", ""), atividade):
                alvo = a
                break
        if alvo is None:
            descs = [a.get("descricao", "") for a in atividades]
            self.memory.record_failure("find_assessment", atividade, f"nao_achou descs={descs}")
            return None

        if not self._fire_event("NOTAS", alvo["suffix"]):
            self.memory.record_failure("find_assessment", atividade, f"click_NOTAS_sufixo={alvo['suffix']}")
            return None

        self._wait_network_idle()
        self._wait_settle(1500)
        self.memory.record_success("find_assessment", atividade)
        return alvo

    def detect_columns(self) -> Dict[str, str]:
        return {"1": "vALUNONOTA", "2": "vATIVIDADENOTASITUACAO"}

    def read_grades(self) -> List[Dict]:
        html = self._html()
        return [dict(r) for r in p.extract_notas(html)]

    def get_student_sample(self, limit: int = 10) -> List[str]:
        sample = []
        for r in p.extract_notas(self._html()):
            nome = (r.get("nome") or "").strip()
            if nome:
                sample.append(nome)
            if len(sample) >= limit:
                break
        return sample

    def fill_grade(self, aluno: str, nota: str, coluna: str = "") -> bool:
        """Preenche a nota (vALUNONOTA_<suffix>) do aluno na pagina de notas."""
        if not self.is_logged_in():
            return False
        rows = p.extract_notas(self._html())
        best = None
        best_score = 0.0
        for r in rows:
            score = self._name_similarity(aluno, r.get("nome", ""))
            if score > best_score:
                best_score = score
                best = r
        if best is None or best_score <= 0:
            self.memory.record_failure("fill_grade", aluno, "aluno_nao_encontrado")
            return False

        input_name = best["input_nota"]
        valor = self._format_nota(nota)
        try:
            loc = self.page.locator(f"input[name='{input_name}']")
            if loc.count() == 0:
                self.memory.record_failure("fill_grade", aluno, f"input_ausente={input_name}")
                return False
            loc.first.fill(valor, timeout=self.ACTION_TIMEOUT)
            self.memory.record_success("fill_grade", f"{aluno}->{valor}")
            return True
        except Exception as exc:
            self.memory.record_failure("fill_grade", aluno, str(exc))
            return False

    @staticmethod
    def _format_nota(nota: str) -> str:
        """Converte a nota para o formato esperado (virgula decimal)."""
        v = str(nota or "").strip()
        if not v:
            return ""
        v = v.replace(" ", "")
        try:
            f = float(v.replace(",", "."))
            s = f"{f:.2f}".replace(".", ",")
            return s
        except ValueError:
            return v

    def save(self) -> bool:
        """Confirma as notas (botao CONFIRMAR)."""
        return self._click_button(["input[name='CONFIRMAR']", "button:has-text('Confirmar')", "input[value*='Confirmar' i]"])

    # ------------------------------------------------------------------ #
    #  Chamada diaria                                                     #
    # ------------------------------------------------------------------ #

    def open_chamada(self) -> bool:
        return self._navigate_menu_path(self.CHAMADA_PATH)

    def read_chamada(self) -> List[Dict]:
        return [dict(r) for r in p.extract_chamada(self._html())]

    def fill_presenca(self, aluno: str, valor: str) -> bool:
        """Marca a presenca (vD1_<suffix>) de um aluno na chamada do dia."""
        if not self.is_logged_in():
            return False
        rows = p.extract_chamada(self._html())
        best = None
        best_score = 0.0
        for r in rows:
            score = self._name_similarity(aluno, r.get("nome", ""))
            if score > best_score:
                best_score = score
                best = r
        if best is None or best_score <= 0:
            return False
        input_name = best["input_presenca"]
        try:
            loc = self.page.locator(f"input[name='{input_name}']")
            if loc.count() == 0:
                return False
            loc.first.fill(valor, timeout=self.ACTION_TIMEOUT)
            return True
        except Exception:
            return False

    def save_chamada(self) -> bool:
        return self._click_button(["input[name='BTN_CONFIRMAR']", "input[value*='Confirmar' i]"])

    def set_chamada_dia(self, dia: str) -> bool:
        """Ajusta a data (vDATA) da chamada. ``dia`` no formato DD/MM/AAAA."""
        if not self.is_logged_in():
            return False
        try:
            loc = self.page.locator("input[name='vDATA']")
            if loc.count() == 0:
                return False
            loc.first.fill(dia, timeout=self.ACTION_TIMEOUT)
            loc.first.blur()
            self._wait_settle(800)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Faltas do mes                                                      #
    # ------------------------------------------------------------------ #

    def open_faltas_mes(self) -> bool:
        """Abre a tela de faltas do mes (cadfaltasmesnovo.aspx) da turma."""
        return self._navigate_menu_path(self.FALTAS_MES_PATH)

    def read_faltas_mes(self) -> Dict:
        """Le as faltas do mes da turma atual (tela de leitura)."""
        return dict(p.extract_faltas_mes(self._html()))

    # ------------------------------------------------------------------ #
    #  Turmas / escolas                                                   #
    # ------------------------------------------------------------------ #

    @property
    def turmas(self) -> List[Dict[str, str]]:
        """Turmas conhecidas (grid da Tela Inicial)."""
        return list(self._turmas)

    def detectar_escolas(self) -> List[str]:
        """Escolas unicas (por nome) presentes nas turmas do professor."""
        escolas: List[str] = []
        vistos = set()
        for t in self._turmas:
            nome = (t.get("escola") or "").strip()
            if not nome:
                continue
            chave = re.sub(r"[^a-z0-9]", "", nome.lower())
            if chave not in vistos:
                vistos.add(chave)
                escolas.append(nome)
        return escolas

    # ------------------------------------------------------------------ #
    #  Diario de classe                                                   #
    # ------------------------------------------------------------------ #

    def open_diario(self) -> bool:
        return self._navigate_menu_path(self.DIARIO_PATH)

    def read_diario(self) -> List[Dict]:
        return [dict(r) for r in p.extract_diario(self._html())]

    def set_diario_situacao(self, data: str, situacao: str) -> bool:
        """Ajusta a situacao (AULADADA_<suffix>) do dia no diario de classe.

        ``situacao`` pode ser o rotulo ('Confirmada', 'Agendada', 'Sem aula',
        'Extra') ou o codigo ('1'..'4').
        """
        if not self.is_logged_in():
            return False
        rotulo_alvo = situacao.strip()
        codigo_alvo = ""
        for k, v in self.DIARIO_SITUACOES.items():
            if v.lower() == rotulo_alvo.lower():
                codigo_alvo = k
                break
            if k == rotulo_alvo:
                codigo_alvo = k
                rotulo_alvo = v
                break
        if not codigo_alvo:
            return False

        rows = p.extract_diario(self._html())
        alvo = None
        for r in rows:
            if data and data in (r.get("data") or ""):
                alvo = r
                break
        if alvo is None:
            return False

        input_name = alvo["input_situacao"]
        try:
            sel = self.page.locator(f"select[name='{input_name}']")
            if sel.count() > 0:
                sel.first.select_option(value=codigo_alvo, timeout=self.ACTION_TIMEOUT)
            else:
                inp = self.page.locator(f"input[name='{input_name}']")
                if inp.count() == 0:
                    return False
                inp.first.fill(rotulo_alvo, timeout=self.ACTION_TIMEOUT)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Planejamentos                                                      #
    # ------------------------------------------------------------------ #

    def supports_lesson_plan(self) -> bool:
        return True

    def navigate_to_lesson_plan(self, context: PortalContext) -> bool:
        return self._navigate_menu_path(self.PLANEJAMENTOS_PATH)

    def read_planejamentos(self) -> List[Dict]:
        return [dict(r) for r in p.extract_planejamentos(self._html())]

    def read_planejamento_anual(self) -> List[Dict]:
        if not self._navigate_menu_path(self.PLANEJAMENTO_ANUAL_PATH):
            return []
        return [dict(r) for r in p.extract_planejamento_anual(self._html())]

    def create_lesson_plan(self, plan: LessonPlan) -> bool:
        """Cria um planejamento semanal na turma atual.

        Fluxo: lista (cadmostrarplanejamentosemanal.aspx) -> botao INCLUIR
        (abre planejamentosemanal.aspx em popup) -> preenche datas, PDF e
        observacao -> Confirmar (BTN_ENTER) -> verifica na lista.
        """
        if not self.is_logged_in():
            return False
        try:
            self._goto(self.PLANEJAMENTOS_PATH)
            self._wait_network_idle()
            self._wait_settle(1200)
        except Exception:
            pass
        if not p.is_planejamentos_list(self._html()):
            self.memory.record_failure("create_lesson_plan", plan.titulo, "nao_abriu_lista_planejamentos")
            return False

        criado = self._create_planejamento_form(plan)
        if not criado:
            return False

        if plan.data_inicio:
            # Confirma lendo a lista principal apos o fechamento do popup.
            try:
                self._goto(self.PLANEJAMENTOS_PATH)
                self._wait_network_idle()
                self._wait_settle(1200)
                for e in self.read_planejamentos():
                    if plan.data_inicio in (e.get("data_inicio") or "") and plan.data_fim in (e.get("data_fim") or ""):
                        self.memory.record_success("create_lesson_plan", f"{plan.data_inicio}..{plan.data_fim}")
                        return True
            except Exception:
                pass
            self.memory.record_failure(
                "create_lesson_plan", plan.titulo,
                f"nao_encontrado_apos_criar {plan.data_inicio}",
            )
            return False

        self.memory.record_success("create_lesson_plan", plan.titulo)
        return True

    def upload_lesson_plan_pdf(self, titulo: str, pdf_path: str) -> bool:
        """Anexa um PDF ao planejamento semanal.

        No Professor Online o anexo e feito DENTRO do formulario de criacao/
        edicao (planejamentosemanal.aspx) — nao ha upload avulso. Para anexar
        em criacao use ``create_lesson_plan`` com ``plan.pdf_path``.
        """
        self.memory.record_failure("upload_lesson_plan_pdf", titulo, "anexo_so_no_formulario")
        return False

    def create_planejamento_anual(self, plan: LessonPlan) -> bool:
        """Atualiza o conteudo programatico (plano anual) na turma atual.

        Fluxo: lista (cadmostrarconteudoprog.aspx) -> INCLUIR (abre
        conteudoprogramaticodisciplina.aspx em popup) -> observacao + PDF ->
        Confirmar. O plano anual nao tem periodo: versao/vigente sao fixos.
        """
        if not self.is_logged_in():
            return False
        try:
            self._goto(self.PLANEJAMENTO_ANUAL_PATH)
            self._wait_network_idle()
            self._wait_settle(1200)
        except Exception:
            pass
        if p.is_conteudo_prog_form(self._html()):
            return self._fill_conteudo_prog_form(plan) and self._confirm_planejamento()

        popup = self._open_form_popup(self._click_incluir)
        if popup is None:
            self.memory.record_failure("create_planejamento_anual", plan.titulo, "nao_abriu_formulario_anual")
            return False
        main = self._page
        eh_outra = popup is not main
        if eh_outra:
            self._page = popup
        try:
            ok = self._fill_conteudo_prog_form(plan) and self._confirm_planejamento()
        finally:
            if eh_outra:
                self._page = main
                try:
                    popup.close()
                except Exception:
                    pass
                self._wait_settle(800)
        return bool(ok)

    # ------------------------------------------------------------------ #
    #  Helpers do formulario de planejamento (popup GeneXus)              #
    # ------------------------------------------------------------------ #

    def _click_incluir(self) -> None:
        """Clica no botao INCLUIR da lista (nova versao). Fallback via evento."""
        btn = self.page.locator("input[name='INCLUIR']")
        try:
            if btn.count() > 0:
                btn.first.click(timeout=self.ACTION_TIMEOUT)
                return
        except Exception:
            pass
        self._trigger_event("E'INCLUIR'.")

    def _trigger_event(self, event_expr: str) -> bool:
        """Dispara um evento GeneXus por expressao (ex: ``E'INCLUIR'.``)."""
        try:
            return bool(self.page.evaluate(
                """
                (args) => {
                    if (!window.gx || !gx.evt || !gx.evt.execEvt) return false;
                    try { gx.evt.execEvt(args.event, null); return true; }
                    catch (e) { return false; }
                }
                """,
                {"event": event_expr},
            ))
        except Exception:
            return False

    def _open_form_popup(self, open_fn: Callable[[], None]) -> Optional[Page]:
        """Executa open_fn e retorna a Page do formulario.

        O formulario de planejamento abre em popup (GeneXus, botao Fechar usa
        ``gx.fn.closeWindow``) — por isso memo usa ``expect_popup``. Se abrir
        na mesma aba (fallback), retorna a pagina atual.
        """
        try:
            with self.page.expect_popup(timeout=4000) as pop_info:
                open_fn()
            popup = pop_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=self.NAV_TIMEOUT)
            try:
                popup.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            popup.wait_for_timeout(1500)
            return popup
        except Exception:
            pass
        # fallback: mesma aba
        self._wait_network_idle()
        self._wait_settle(1800)
        return self.page

    def _create_planejamento_form(self, plan: LessonPlan) -> bool:
        """Abre o formulario semanal (popup ou mesma aba), preenche e confirma."""
        popup_ref = None
        if p.is_planejamento_semanal_form(self._html()):
            contender = self.page
        else:
            contender = self._open_form_popup(self._click_incluir)
            if contender is None:
                self.memory.record_failure("create_planejamento", plan.titulo, "form_nao_abriu")
                return False
        main = self._page
        if contender is not main:
            popup_ref = contender
        if popup_ref is not None:
            self._page = popup_ref
        try:
            if not p.is_planejamento_semanal_form(self._html()):
                self.memory.record_failure("create_planejamento", plan.titulo, "pagina_nao_e_formulario")
                return False
            if not self._fill_planejamento_form(plan):
                return False
            return self._confirm_planejamento()
        finally:
            if popup_ref is not None:
                self._page = main
                try:
                    popup_ref.close()
                except Exception:
                    pass
                self._wait_settle(800)

    def _fill_planejamento_form(self, plan: LessonPlan) -> bool:
        """Preenche datas, PDF e observacao no formulario semanal."""
        p_ = self.page
        try:
            if plan.data_inicio:
                di = p_.locator("input[name='PLANEJAMENTOSEMDATAINICIO']")
                if di.count() > 0:
                    di.first.fill(plan.data_inicio)
                    di.first.dispatch_event("change")
                    di.first.dispatch_event("blur")
            if plan.data_fim:
                df = p_.locator("input[name='PLANEJAMENTOSEMDATAFIM']")
                if df.count() > 0:
                    df.first.fill(plan.data_fim)
                    df.first.dispatch_event("change")
                    df.first.dispatch_event("blur")
            if plan.pdf_path and os.path.exists(plan.pdf_path):
                fu = p_.locator("input[name='PLANEJSEMANALARQUIVOPDF']")
                if fu.count() > 0:
                    fu.first.set_input_files(plan.pdf_path)
                    self._wait_settle(1200)
            obs_texto = (plan.titulo or "").strip()
            if obs_texto:
                obs = p_.locator("textarea[name='PLANEJSEMANALOBSERVACAO']")
                if obs.count() > 0:
                    obs.first.fill(obs_texto)
            self._wait_settle(800)
            self.memory.record_success("fill_planejamento_form", f"{plan.data_inicio}..{plan.data_fim}")
            return True
        except Exception as exc:
            self.memory.record_failure("fill_planejamento_form", plan.titulo, str(exc))
            return False

    def _fill_conteudo_prog_form(self, plan: LessonPlan) -> bool:
        """Preenche observacao e PDF no formulario do plano anual."""
        p_ = self.page
        try:
            if plan.pdf_path and os.path.exists(plan.pdf_path):
                fu = p_.locator("input[name='CONTEUDOPROGARQUIVOPDF']")
                if fu.count() > 0:
                    fu.first.set_input_files(plan.pdf_path)
                    self._wait_settle(1200)
            obs_texto = (plan.titulo or "").strip()
            if obs_texto:
                obs = p_.locator("textarea[name='CONTEUDOPROGOBSERVACAO']")
                if obs.count() > 0:
                    obs.first.fill(obs_texto)
            self._wait_settle(800)
            return True
        except Exception as exc:
            self.memory.record_failure("fill_conteudo_prog_form", plan.titulo, str(exc))
            return False

    def _confirm_planejamento(self) -> bool:
        """Clica em Confirmar (BTN_ENTER) e valida a ausencia de erro."""
        btn = self.page.locator("input[name='BTN_ENTER']")
        if btn.count() == 0:
            self.memory.record_failure("confirm_planejamento", "BTN_ENTER", "botao_ausente")
            return False
        try:
            btn.first.click(timeout=self.ACTION_TIMEOUT)
            self._wait_network_idle()
            self._wait_settle(1800)
        except Exception:
            return True
        try:
            html = self._html()
        except Exception:
            return True
        err = p.find_error_message(html)
        if err:
            self.memory.record_failure("confirm_planejamento", "BTN_ENTER", err)
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Helpers genericos                                                  #
    # ------------------------------------------------------------------ #

    def _fire_event(self, event_name: str, suffix: str) -> bool:
        """Clique no link do grid cujo clickevent contem event_name e o suffix.

        Os links renderizados pelo GeneXus ficam no formato
        ``javascript:gx.evt.execEvt('E\\'SELECIONA\\'.0001',this)``.
        Primeiro tenta clicar no link real; se nao achar, chama o evento
        diretamente via ``gx.evt.execEvt``.
        """
        p_ = self.page
        try:
            found = p_.evaluate(
                """
                (args) => {
                    const name = args.name;
                    const suffix = args.suffix;
                    const links = Array.from(document.querySelectorAll('a[href*="execEvt"]'));
                    for (const a of links) {
                        const h = a.getAttribute('href') || '';
                        if (h.includes(name) && h.includes('.' + suffix)) {
                            a.click();
                            return true;
                        }
                    }
                    return false;
                }
                """,
                {"name": event_name, "suffix": suffix},
            )
            if found:
                return True
        except Exception:
            pass

        try:
            self.page.evaluate(
                """
                (args) => {
                    if (window.gx && gx.evt && gx.evt.execEvt) {
                        gx.evt.execEvt(args.event, null);
                        return true;
                    }
                    return false;
                }
                """,
                {"event": f"E'{event_name}'.{suffix}"},
            )
            return True
        except Exception:
            return False

    def _click_button(self, selectors: List[str]) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.click(timeout=self.ACTION_TIMEOUT)
                    self._wait_settle(1500)
                    self.memory.record_success("save", sel)
                    return True
            except Exception:
                continue
        self.memory.record_failure("save", "no_button", "Botao nao encontrado")
        return False

    @staticmethod
    def _name_similarity(a: str, b: str) -> float:
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if a_norm == b_norm:
            return 1.0
        a_tokens = set(a_norm.split())
        b_tokens = set(b_norm.split())
        if not a_tokens or not b_tokens:
            return 0.0
        inter = a_tokens & b_tokens
        return len(inter) / max(len(a_tokens), len(b_tokens))
