"""Testes do parser e do adapter do Portal Professor Online (SED/SC)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.core import professor_online_parser as p
from bot.core.professor_online_adapter import ProfessorOnlineAdapter
from bot.core.portal_adapter import PortalContext
from bot.core.portal_factory import get_adapter

FIXTURES = Path(__file__).parent / "fixtures" / "professor_online"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


class TestParserLogin:
    def test_login_page(self):
        html = _html("login.html")
        assert p.is_login_page(html)
        assert not p.is_logged_in(html)
        assert p.form_action(html) == "cadloginprofcaptchacopy1.aspx"

    def test_tela_inicial_logada(self):
        html = _html("tela_inicial.html")
        assert not p.is_login_page(html)
        assert p.is_logged_in(html)

    def test_turmas_extraidas(self):
        turmas = p.extract_turmas(_html("tela_inicial.html"))
        assert len(turmas) == 8
        first = turmas[0]
        assert first["escola"] == "EEB REGENTE FEIJO"
        assert first["serie"] == "2 - SÉRIE"
        assert first["turma"] == "201"
        assert first["disciplina"] == "GESTÃO DE PESSOAS"
        assert first["suffix"] == "0001"


class TestParserAtividades:
    def test_avaliacoes(self):
        ats = p.extract_atividades(_html("avaliacoes_turma.html"))
        assert len(ats) == 6
        a1 = ats[0]
        assert a1["descricao"] == "TP1"
        assert a1["bimestre"] == "2"
        assert a1["data"].startswith("01/06/2026")
        assert a1["suffix"] == "0001"

    def test_atividade_matches(self):
        assert p.atividade_matches("TP1", "tp1")
        assert p.atividade_matches("Avaliação 2º Trimestre", "avaliacao 2o trimestre")
        assert not p.atividade_matches("Prova", "Trabalho")


class TestParserNotas:
    def test_notas_atividade(self):
        notas = p.extract_notas(_html("notas_atividade.html"))
        assert len(notas) == 18
        n0 = notas[0]
        assert n0["matricula"] == "4549489757"
        assert n0["nome"] == "AMABILE MAHARA ROSA"
        assert n0["nota"] == "10,00"
        assert n0["situacao"] == "1"
        assert n0["input_nota"] == "vALUNONOTA_0001"
        assert n0["input_situacao"] == "vATIVIDADENOTASITUACAO_0001"


class TestParserChamada:
    def test_chamada(self):
        chamada = p.extract_chamada(_html("chamada_em_sala.html"))
        assert len(chamada) == 18
        c0 = chamada[0]
        assert c0["matricula"] == "4549489757"
        assert c0["nome"] == "AMABILE MAHARA ROSA"
        assert c0["input_presenca"] == "vD1_0001"


class TestParserFaltasMes:
    def test_faltas_mes(self):
        dados = p.extract_faltas_mes(_html("faltas_por_mes.html"))
        assert dados["data_inicio"] == "28/05/2026"
        assert dados["data_fim"] == "06/09/2026"
        assert len(dados["alunos"]) == 18
        a0 = dados["alunos"][0]
        assert a0["matricula"] == "4549489757"
        assert "vD1" in a0["colunas"]
        assert a0["total_faltas"] == "3"


class TestParserDiario:
    def test_diario(self):
        diario = p.extract_diario(_html("diarios_de_classe.html"))
        assert len(diario) == 17
        d0 = diario[0]
        assert d0["data"] == "11/08/2026"
        assert d0["input_situacao"] == "AULADADA_0001"

    def test_diario_situacoes(self):
        state = p.parse_gxstate(_html("diarios_de_classe.html"))
        vals = state["AULADADA_0001_Values"]
        assert isinstance(vals, str)
        assert "Confirmada" in vals and "Agendada" in vals


class TestParserPlanejamentos:
    def test_planejamentos_semanais(self):
        plans = p.extract_planejamentos(_html("planejamentos_turma.html"))
        assert len(plans) == 2
        assert plans[0]["data_inicio"] == "03/08/2026"
        assert plans[0]["data_fim"] == "01/09/2026"
        assert plans[0]["situacao"] == "s"

    def test_planejamento_anual(self):
        plans = p.extract_planejamento_anual(_html("planejamento_anual.html"))
        assert len(plans) == 1
        assert plans[0]["data"] == "20/02/2026 19:25:03"
        assert plans[0]["situacao"] == "s"
        assert plans[0]["versao"] == "1"
        assert plans[0]["pdf_url"]


class TestParserMenu:
    def test_menu_extraido(self):
        state = p.parse_gxstate(_html("avaliacoes_turma.html"))
        menu = state["vMENUDATACOLLECTION_MPAGE"]
        assert isinstance(menu, list)
        urls = [m["Url"] for grupo in menu for m in grupo.get("Childs", [])]
        assert "cadmostraratividades.aspx" in urls
        assert "cadtodasnotasturma2.aspx" in urls
        assert "cadfaltasmesnovo.aspx" in urls

    def test_span_text_atividade_tipo(self):
        html = _html("atividade_turma.html")
        tipo = p.span_text(html, "vTIPOSATIVIDADECOD")
        assert tipo == "Trabalho prático"
        state = p.parse_gxstate(html)
        assert state["vTIPOSATIVIDADECOD"] == " 5"
        assert state["vFORMULAAVDESC"] == " 2º TRIMESTRE"
        assert state["vATIVIDADESDESCRICAO"] == "TP1"


class TestAdapterUnit:
    def test_formata_nota(self):
        a = ProfessorOnlineAdapter
        assert a._format_nota("7.5") == "7,50"
        assert a._format_nota("7,5") == "7,50"
        assert a._format_nota("10") == "10,00"
        assert a._format_nota("") == ""
        assert a._format_nota("abc") == "abc"

    def test_name_similarity(self):
        a = ProfessorOnlineAdapter
        assert a._name_similarity("AMABILE MAHARA ROSA", "AMABILE MAHARA ROSA") == 1.0
        assert a._name_similarity("AMABILE MAHARA", "AMABILE MAHARA ROSA") > 0.5
        assert a._name_similarity("JOÃO", "MARIA") == 0.0

    def test_match_turma(self):
        a = ProfessorOnlineAdapter
        turmas = [
            {"suffix": "0001", "escola": "EEB REGENTE FEIJO", "turma": "201", "disciplina": "GESTÃO DE PESSOAS"},
            {"suffix": "0005", "escola": "EEB REGENTE FEIJO", "turma": "202", "disciplina": "GESTÃO DE PESSOAS"},
        ]
        ctx = PortalContext(escola="EEB REGENTE FEIJO", turma="201")
        m = a._match_turma(turmas, ctx)
        assert m is not None and m["suffix"] == "0001"

        ctx2 = PortalContext(escola="", turma="202")
        m2 = a._match_turma(turmas, ctx2)
        assert m2 is not None and m2["suffix"] == "0005"

        ctx3 = PortalContext(escola="OUTRA ESCOLA", turma="999")
        assert a._match_turma(turmas, ctx3) is None

    def test_diario_situacoes_map(self):
        a = ProfessorOnlineAdapter
        assert a.DIARIO_SITUACOES["1"] == "Confirmada"
        assert a.DIARIO_SITUACOES["4"] == "Extra"

    def test_login_failure_reason_nao_captcha_falso(self):
        a = ProfessorOnlineAdapter()
        html = _html("login.html")
        assert p.is_login_page(html)
        motivo = a._login_failure_reason(html)
        assert "captcha" not in motivo.lower()
        assert motivo.startswith("erro_apresentado=") or motivo == "nao_logado"


class TestFactory:
    def test_get_adapter_professor_online(self):
        adapter = get_adapter("professor_online")
        assert isinstance(adapter, ProfessorOnlineAdapter)
        assert adapter.url == ProfessorOnlineAdapter.BASE_URL

    def test_get_adapter_with_url(self):
        adapter = get_adapter("professor_online", {"url": "https://exemplo.test"})
        assert adapter.url == "https://exemplo.test"


class TestAprenderNovoPortal:
    def test_slug_from_url(self):
        from aprender_novo_portal import _slug_from_url

        assert _slug_from_url("https://www.sgp.educacao.sp.gov.br/login") == "novo_portal_sgp"
        assert _slug_from_url("https://127.0.0.1:8000") == "novo_portal_127"
        assert _slug_from_url("") == "novo_portal"

    def test_sem_url_levanta_erro(self):
        from aprender_novo_portal import executar_aprendizado

        try:
            executar_aprendizado(url="", cpf="x", senha="y")
        except ValueError as exc:
            assert "URL" in str(exc)
        else:
            raise AssertionError("Deveria exigir URL")

    def test_sem_credenciais_levanta_erro(self):
        from aprender_novo_portal import executar_aprendizado

        try:
            executar_aprendizado(url="https://exemplo.test", cpf="", senha="")
        except ValueError as exc:
            assert "CPF" in str(exc)
        else:
            raise AssertionError("Deveria exigir credenciais")

    def test_registro_portal(self, tmp_path):
        from aprender_novo_portal import _register_portal

        plan = {"workflow_name": "fluxo teste", "steps": [{"step": 1, "action": "click"}]}
        outdir = tmp_path / "out"
        outdir.mkdir(parents=True, exist_ok=True)
        assert _register_portal("PortalTesteXyz", plan, outdir) is True


class TestOrquestrador:
    def test_dry_run_com_registros(self):
        from lancar_professor_online import RegistroNota, executar_lancamento

        regs = [
            RegistroNota(escola="E1", turno="Matutino", turma="1A", trimestre="2o Trimestre", aluno="Ana", atividade="TP1", nota=8.5),
            RegistroNota(escola="E1", turno="Matutino", turma="1A", trimestre="2o Trimestre", aluno="Bruno", atividade="TP1", nota=7.0),
        ]
        r = executar_lancamento(
            fonte="csv",
            fonte_path="",
            filtro=None,
            logger=None,
            dry_run=True,
            cpf="11122233344",
            senha="x",
            registros=regs,
        )
        assert r == {"blocos": 1, "notas": 2, "notas_preenchidas": 0, "ausentes": 0, "falhas": 0}

    def test_dry_run_com_filtro(self):
        from lancar_professor_online import RegistroNota, executar_lancamento

        regs = [
            RegistroNota(escola="E1", turno="Matutino", turma="1A", trimestre="2o Trimestre", aluno="Ana", atividade="TP1", nota=8.5),
            RegistroNota(escola="E2", turno="Matutino", turma="1A", trimestre="2o Trimestre", aluno="Bruno", atividade="TP1", nota=7.0),
        ]
        r = executar_lancamento(
            fonte="csv",
            fonte_path="",
            filtro={"escola": "E1"},
            logger=None,
            dry_run=True,
            cpf="11122233344",
            senha="x",
            registros=regs,
        )
        assert r["notas"] == 1

    def test_sem_credenciais_levanta_erro(self):
        import os

        from lancar_professor_online import LancamentoError, executar_lancamento

        old_cpf, old_senha = os.environ.pop("PO_CPF", None), os.environ.pop("PO_SENHA", None)
        try:
            try:
                executar_lancamento(fonte="csv", fonte_path="", logger=None, dry_run=True)
            except LancamentoError as exc:
                assert "PO_CPF" in str(exc)
            else:
                raise AssertionError("Deveria levantar LancamentoError sem credenciais")
        finally:
            if old_cpf is not None:
                os.environ["PO_CPF"] = old_cpf
            if old_senha is not None:
                os.environ["PO_SENHA"] = old_senha


class TestPlanoChamadaPo:
    def _plano(self):
        from lancar_professor_online import _montar_plano_po

        grade = [
            {"nome": "AMABILE MAHARA ROSA", "matricula": "4549489757", "presenca": "."},
            {"nome": "ANDREI NAGEL", "matricula": "4549539126", "presenca": "."},
            {"nome": "MARIA JOSE SILVA", "matricula": "0001", "presenca": "."},
        ]
        foto = [
            {"aluno": "AMABILE ROSA", "situacao": "presente", "faltas": "0"},
            {"aluno": "ANDREI NAGEL", "situacao": "falta", "faltas": "1"},
            {"aluno": "FULANO SEM REGISTRO", "situacao": "falta", "faltas": "2"},
        ]
        return _montar_plano_po(grade, foto)

    def test_montar_plano(self):
        plano, nao_encontrados = self._plano()
        por_aluno = {item["aluno"]: item for item in plano}
        assert por_aluno["AMABILE MAHARA ROSA"]["acao"] == "presenca"
        assert por_aluno["ANDREI NAGEL"]["acao"] == "falta"
        assert por_aluno["ANDREI NAGEL"]["faltas"] == 1
        assert por_aluno["MARIA JOSE SILVA"]["acao"] == "pular"
        assert nao_encontrados == ["FULANO SEM REGISTRO"]

    def test_ja_lancado_pula(self):
        from lancar_professor_online import _montar_plano_po

        grade = [{"nome": "AMABILE MAHARA ROSA", "matricula": "1", "presenca": "1F"}]
        plano, _ = _montar_plano_po(grade, [{"aluno": "AMABILE MAHARA ROSA", "situacao": "presente"}])
        assert plano[0]["acao"] == "pular"
        assert plano[0]["ja_lancado"] is True

    def test_valor_presenca_po(self):
        from lancar_professor_online import _valor_presenca_po

        assert _valor_presenca_po({"acao": "presenca"}) == "C"
        assert _valor_presenca_po({"acao": "falta", "motivo": "injustificada", "faltas": 1}) == "1F"
        assert _valor_presenca_po({"acao": "falta", "motivo": "injustificada", "faltas": 5}) == "2F"
        assert _valor_presenca_po({"acao": "falta", "motivo": "justificada", "faltas": 1}) == "1J"
        assert _valor_presenca_po({"acao": "falta", "motivo": "justificada", "faltas": 2}) == "2J"

    def test_resumo_plano(self):
        from lancar_professor_online import _resumo_plano_po

        plano = [
            {"acao": "presenca"},
            {"acao": "falta"},
            {"acao": "pular", "ja_lancado": True},
            {"acao": "pular", "ja_lancado": False},
        ]
        assert _resumo_plano_po(plano) == {"ja_lancados": 1, "presentes": 1, "faltas": 1, "pulados": 1}


class TestExecutarFaltasMes:
    def test_sem_credenciais_levanta_erro(self):
        import os

        from lancar_professor_online import LancamentoError, executar_faltas_mes

        old_cpf, old_senha = os.environ.pop("PO_CPF", None), os.environ.pop("PO_SENHA", None)
        try:
            try:
                executar_faltas_mes(filtro={"turma": "201"}, logger=None)
            except LancamentoError as exc:
                assert "PO_CPF" in str(exc)
            else:
                raise AssertionError("Deveria levantar LancamentoError sem credenciais")
        finally:
            if old_cpf is not None:
                os.environ["PO_CPF"] = old_cpf
            if old_senha is not None:
                os.environ["PO_SENHA"] = old_senha


class TestExecutarPlanejamento:
    def test_dry_run(self):
        from lancar_professor_online import executar_planejamento

        r = executar_planejamento(
            registros=[{"escola": "E1", "turma": "201", "titulo_documento": "Seq 1"}],
            logger=None,
            dry_run=True,
            cpf="11122233344",
            senha="x",
        )
        assert r["contextos"] == 1
        assert r["success"] is True
        assert r["nao_implementado"] == 0

    def test_sem_registros_levanta_erro(self):
        import os

        from lancar_professor_online import LancamentoError, executar_planejamento

        old_cpf, old_senha = os.environ.pop("PO_CPF", None), os.environ.pop("PO_SENHA", None)
        try:
            try:
                executar_planejamento(registros=[], logger=None, dry_run=True)
            except LancamentoError as exc:
                assert "PO_CPF" in str(exc)
            else:
                raise AssertionError("Deveria levantar LancamentoError sem credenciais")
        finally:
            if old_cpf is not None:
                os.environ["PO_CPF"] = old_cpf
            if old_senha is not None:
                os.environ["PO_SENHA"] = old_senha


class TestParserFaltasMes:
    def test_faltas_mes(self):
        data = p.extract_faltas_mes(_html("faltas_por_mes.html"))
        assert data["data_inicio"] == "28/05/2026"
        assert data["data_fim"] == "06/09/2026"
        assert len(data["alunos"]) == 18
        a0 = data["alunos"][0]
        assert a0["nome"] == "AMABILE MAHARA ROSA"
        assert a0["total_faltas"] == "3"
        assert a0["colunas"].get("vD7") == "1F"
        assert a0["colunas"].get("vD1") == "C"


class TestAdapterNovosMetodos:
    def test_detectar_escolas(self):
        adapter = ProfessorOnlineAdapter(base_url="https://exemplo.test")
        adapter._turmas = [
            {"escola": "EEB REGENTE FEIJO", "turma": "201"},
            {"escola": "EEB REGENTE FEIJO", "turma": "301"},
            {"escola": "EEB OUTRA ESCOLA", "turma": "101"},
        ]
        assert sorted(adapter.detectar_escolas()) == ["EEB OUTRA ESCOLA", "EEB REGENTE FEIJO"]

    def test_constant_paths(self):
        adapter = ProfessorOnlineAdapter()
        assert adapter.FALTAS_MES_PATH == "cadfaltasmesnovo.aspx"
        assert adapter.CHAMADA_PATH == "cadfaltaschamadaemsala.aspx"


class TestEscolaRegistry:
    def test_registro_e_consulta(self, monkeypatch, tmp_path):
        import bot.core.escola_registry as er
        monkeypatch.setattr(er, "REGISTRY_PATH", tmp_path / "escolas.json")

        assert er.portal_da_escola("EEB REGENTE FEIJO") is None
        assert er.registrar_escola("EEB REGENTE FEIJO", "professor_online") is True
        assert er.portal_da_escola("eeb regente feijó") == "professor_online"
        assert er.registrar_escola("EEB REGENTE FEIJO", "professor_online") is False
        assert er.escolas_do_portal("professor_online") == ["EEB REGENTE FEIJO"]

    def test_consulta_acentos(self, monkeypatch, tmp_path):
        import bot.core.escola_registry as er
        monkeypatch.setattr(er, "REGISTRY_PATH", tmp_path / "escolas.json")

        er.registrar_escola("EEB JOÃO DA SILVA", "sge")
        assert er.portal_da_escola("EEB Joao da Silva") == "sge"
