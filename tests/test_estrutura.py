"""Testes do PONTO 3 — blindagem do SGE contra mudancas de estrutura.

Cobre:
- 3.1 Cadeia de fallback de seletores (CSS -> atributo via JS -> linha por texto).
- 3.3 Alarme [ESTRUTURA-CHANGED]: deteccao + evidencia + NAO grava.
- 3.4 Leitura de volta (verificacao pos-preenchimento).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeScope:
    """Scope com locator Fake simples + evaluate controlado."""

    def __init__(self, evaluate_result=None, locator_count=0):
        self._eval_result = evaluate_result
        self._locator_count = locator_count
        self._attr_scan = {}

    def evaluate(self, js, arg=None):
        if "document.querySelectorAll('input[type=\"text\"], input[type=\"number\"]').length" in js:
            return 12
        if "estrutura_changed" not in js and "suffix" in str(arg or ""):
            if self._eval_result is not None:
                return self._eval_result
        return {}

    def eval_on_selector_all(self, selector, js):
        return []

    def locator(self, selector):
        return FakeLocator(self._locator_count)

    def get_by_text(self, text, exact=False):
        return []


class FakeLocator:
    def __init__(self, count=0):
        self._count = count

    def count(self):
        return self._count

    def first(self):
        return self

    def nth(self, idx):
        return self

    def is_disabled(self):
        return False

    def get_attribute(self, name):
        return None

    def click(self, timeout=None):
        return None

    def fill(self, value, timeout=None):
        return None

    def dispatch_event(self, name):
        return None

    def screenshot(self, path=None):
        return None

    def locator(self, sel):
        return FakeLocator(self._count)


class FakePage:
    def __init__(self, scopes, url="https://www.sge8147.com.br/hdiscturalunonota.aspx"):
        self._scopes = scopes
        self.url = url
        self.frames = []

    def _iter_scopes_helper(self):
        return self._scopes

    def locator(self, selector):
        return FakeLocator(0)

    def evaluate(self, js):
        return {}

    def content(self):
        return "<html><body><table id='GRIDAGENDA'></table></body></html>"

    def screenshot(self, path=None, full_page=False):
        with open(path, "wb") as f:
            f.write(b"fake-png")
        return None


class TestGradeInputSelectorsChain:
    def test_coluna_gera_chain_com_sufixo(self):
        from lancar_notas_sge import _grade_input_selectors_chain
        chain = _grade_input_selectors_chain("0001", coluna_sge="N2S")
        assert any("_N2S_0001" in s for s in chain)

    def test_sem_coluna_tem_nome_id_nota(self):
        from lancar_notas_sge import _grade_input_selectors_chain
        chain = _grade_input_selectors_chain("0001")
        joined = " | ".join(chain)
        assert "input[name='_NOTA_0001']" in joined
        assert "NOTA" in joined and "AVAL" in joined

    def test_override_local_entra_no_inicio(self, monkeypatch, tmp_path):
        import lancar_notas_sge as m
        override_file = tmp_path / "estrutura_override.json"
        override_file.write_text(json.dumps({"grade_selectors": ["input[name*='AVALIACAO_{suffix}']"]}), encoding="utf-8")
        monkeypatch.setattr(m, "ESTRUTURA_OVERRIDE_PATH", str(override_file))
        chain = m._grade_input_selectors_chain("0007", coluna_sge="")
        assert chain[0] == "input[name*='AVALIACAO_0007']"


class TestLocateGradeInputFallback:
    def test_attributo_descoberto_via_js(self, monkeypatch):
        import lancar_notas_sge as m

        class AttrScope:
            def evaluate(self, js, arg=None):
                if arg and arg.get("suffix"):
                    return "name=_NOTA_0001"
                return {}

            def locator(self, selector):
                if "NOTA_0001" in selector:
                    return FakeLocator(1)
                return FakeLocator(0)

        loc = m._locate_grade_input(AttrScope(), "0001")
        assert loc is not None and loc.count() == 1

    def test_sem_nada_retorna_none(self):
        import lancar_notas_sge as m
        assert m._locate_grade_input(FakeScope(), "0001") is None

    def test_row_text_fallback_sem_coluna_exige_um_campo(self):
        import lancar_notas_sge as m

        class RowScope:
            def get_by_text(self, text, exact=False):
                return [self._hit]

            class _Hit:
                def locator(self, sel):
                    if "ancestor::tr" in sel:
                        return FakeLocator(1)
                    return FakeLocator(1)

            _hit = _Hit()

        loc = m._locate_grade_input_by_row_text(RowScope(), "MARIA DA SILVA")
        assert loc is not None


class TestCollectStudentSlotsFallback:
    def test_fallback_amplo_descobre_slots(self):
        import lancar_notas_sge as m

        class BroadScope:
            def eval_on_selector_all(self, selector, js):
                return []

            def evaluate(self, js, arg=None):
                return [
                    {"suffix": "0001", "aluno": "MARIA DA SILVA"},
                    {"suffix": "0002", "aluno": "JOAO PEREIRA"},
                ]

        slots = m._collect_student_slots(BroadScope())
        assert len(slots) == 2
        assert slots[0]["aluno"] == "MARIA DA SILVA"

    def test_primeiro_seletor_ganha(self):
        import lancar_notas_sge as m

        class GoodScope:
            def eval_on_selector_all(self, selector, js):
                return [{"suffix": "0003", "aluno": "ANA"}] if "_ALUMATNOM_" in selector else []

            def evaluate(self, js, arg=None):
                return [{"suffix": "9999", "aluno": "ERRADO"}]

        slots = m._collect_student_slots(GoodScope())
        assert [s["suffix"] for s in slots] == ["0003"]


class TestCheckEstruturaSge:
    def test_grade_reconhecida_ok(self, monkeypatch):
        import lancar_notas_sge as m

        class GridScope(FakeScope):
            def evaluate(self, js, arg=None):
                return 12

            def eval_on_selector_all(self, selector, js):
                return [{"suffix": "0001", "aluno": "MARIA"}]

        page = FakePage([GridScope()])
        monkeypatch.setattr(m, "_iter_scopes", lambda page: page._scopes)
        res = m._check_estrutura_sge(page, None)
        assert res["ok"] is True
        assert res["slots"] == 1

    def test_estrutura_mudou_gera_evidencia_e_alarme(self, monkeypatch, tmp_path):
        import lancar_notas_sge as m

        class EmptyScope:
            def evaluate(self, js, arg=None):
                return 0

            def eval_on_selector_all(self, selector, js):
                return []

        page = FakePage([EmptyScope()])
        monkeypatch.setattr(m, "_iter_scopes", lambda page: page._scopes)
        monkeypatch.setattr(m, "ESTRUTURA_DIR", str(tmp_path))

        class GridVisible:
            def locator(self, selector):
                return FakeLocator(1)

        monkeypatch.setattr(m, "_grade_entry_indicators_visible", lambda page: True)

        logs = []
        res = m._check_estrutura_sge(page, logs.append)
        assert res["ok"] is False
        assert res["slots"] == 0
        shot = res["evidencia"]["screenshot"]
        assert os.path.exists(shot)
        assert os.path.exists(res["evidencia"]["html"])
        assert os.path.exists(res["evidencia"]["info"])
        assert any("[ESTRUTURA-CHANGED]" in line for line in logs)

    def test_fora_da_grade_sem_alarme(self, monkeypatch, tmp_path):
        import lancar_notas_sge as m

        class EmptyScope:
            def evaluate(self, js, arg=None):
                return 5

            def eval_on_selector_all(self, selector, js):
                return []

        page = FakePage([EmptyScope()])
        monkeypatch.setattr(m, "_iter_scopes", lambda page: page._scopes)
        monkeypatch.setattr(m, "ESTRUTURA_DIR", str(tmp_path))
        monkeypatch.setattr(m, "_grade_entry_indicators_visible", lambda page: False)

        res = m._check_estrutura_sge(page, None)
        assert res["ok"] is True
        assert not os.path.exists(tmp_path / "estrutura_changed.png")


class TestLeituraDeVoltaObrigatoria:
    def test_verificacao_retorna_true_quando_relido_confere(self, monkeypatch):
        import lancar_notas_sge as m

        scope = FakeScope("8,5")
        monkeypatch.setattr(m, "_iter_scopes", lambda page: [scope])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ANA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="": ("8,5", 1))

        class P:
            pass

        ok = m._verify_fill_just_made(P(), "ANA", "8,5", None, coluna_sge="N2S", filled_suffix="0001")
        assert ok is True

    def test_verificacao_nao_confia_sem_filtro_de_coluna(self, monkeypatch):
        import lancar_notas_sge as m

        # _read_grade_value_anchored_js retorna None (campo nao relido/ancorado) -> falha
        class NoReadScope:
            def evaluate(self, js, arg=None):
                return None

        monkeypatch.setattr(m, "_iter_scopes", lambda page: [NoReadScope()])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ANA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="": None)

        class P:
            pass

        ok = m._verify_fill_just_made(P(), "ANA", "8,5", None, coluna_sge="N2S", filled_suffix="0001")
        assert ok is False

    def test_verificacao_linha_ambigua_nao_confirma(self, monkeypatch):
        import lancar_notas_sge as m

        # Linha com mais de um campo do suffix (coluna indefinida) -> NAO confirma.
        monkeypatch.setattr(m, "_iter_scopes", lambda page: [FakeScope()])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ANA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="": ("8,5", 2))

        class P:
            pass

        ok = m._verify_fill_just_made(P(), "ANA", "8,5", None, filled_suffix="0001")
        assert ok is False

    def test_verificacao_zero_so_confirma_com_leitura_ancorada(self, monkeypatch):
        import lancar_notas_sge as m

        # Nota alvo 0,0 NAO e auto-confirmada: exige releitura ancorada igual.
        casos = [
            (("0,0", 1), True),      # releu 0,0 na linha do aluno -> confirma
            (("", 1), False),        # campo vazio na linha -> nao confirma 0,0
            (("7,5", 1), False),     # valor diferente -> nao confirma
            ((None, None), False),   # sem ancora -> nao confirma
        ]
        for releitura, esperado in casos:
            monkeypatch.setattr(m, "_iter_scopes", lambda page: [FakeScope()])
            monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ANA"}])
            monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
            monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="", _r=releitura: _r)

            class P:
                pass

            ok = m._verify_fill_just_made(P(), "ANA", "0,0", None, filled_suffix="0001")
            assert ok is esperado


class TestLeituraAncorada:
    def test_ancorada_converte_dict_do_js(self, monkeypatch):
        import lancar_notas_sge as m

        class Scope:
            def evaluate(self, js, arg=None):
                return {"value": "0,0", "count": 1}

        res = m._read_grade_value_anchored_js(Scope(), "VALESKA FRANCA DA SILVA", "0001", "")
        assert res == ("0,0", 1)

    def test_ancorada_none_quando_js_retorna_null(self, monkeypatch):
        import lancar_notas_sge as m

        class Scope:
            def evaluate(self, js, arg=None):
                return None

        assert m._read_grade_value_anchored_js(Scope(), "ALUNO", "0001", "") is None

    def test_ancorada_linha_ambigua_retorna_count_maior_que_1(self, monkeypatch):
        import lancar_notas_sge as m

        class Scope:
            def evaluate(self, js, arg=None):
                return {"value": "8,5", "count": 2}

        res = m._read_grade_value_anchored_js(Scope(), "ALUNO", "0001", "")
        assert res == ("8,5", 2)

    def test_releitura_bruta_inclui_zero(self, monkeypatch):
        import lancar_notas_sge as m

        # A releitura bruta (usada na re-auditoria) PRECISA ler '0,0' como valor,
        # ao contrario de _read_existing_grade_for_student que descarta zeros.
        monkeypatch.setattr(m, "_iter_scopes", lambda page: [FakeScope()])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "VALESKA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="": ("0,0", 1))

        val = m._read_grade_value_for_student_raw(FakePage([]), "VALESKA", "")
        assert val == "0,0"

    def test_releitura_bruta_none_sem_ancora(self, monkeypatch):
        import lancar_notas_sge as m

        monkeypatch.setattr(m, "_iter_scopes", lambda page: [FakeScope()])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "VALESKA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_read_grade_value_anchored_js", lambda scope, aluno, suffix, cols="": None)

        val = m._read_grade_value_for_student_raw(FakePage([]), "VALESKA", "")
        assert val is None


class TestColetaNaoConfirmado:
    def test_item_nao_confirmado_tem_formato_da_fila(self, monkeypatch, tmp_path):
        import lancar_notas_sge as m
        from lancar_notas_sge import ContextoTurma

        monkeypatch.setattr(m, "REVISAO_DIR", str(tmp_path / "revisao"))
        monkeypatch.setattr(m, "_capturar_evidencia_divergencia", lambda *a, **k: None)

        ctx = ContextoTurma(escola="E1", turno="V", turma="T2", trimestre="2")
        item = m._coletar_nao_confirmado(None, ctx, "24-Resolucao de Problemas", "VALESKA FRANCA DA SILVA", "0,0", "7,5", "")
        assert item["aluno"] == "VALESKA FRANCA DA SILVA"
        assert item["nota_esperada"] == "0,0"
        assert item["nota_lida"] == "7,5"
        assert item["decisao"] is None
        assert item["id"]
        assert item["screenshot"].endswith(".png")

    def test_ids_iguais_entre_modulos(self):
        import lancar_notas_sge as m

        id1 = m._revisao_item_id("E1", "T1", "1", "N1S", "ALUNO A")
        assert id1 == m._revisao_item_id("e1", "t1", "1", "n1s", "aluno a")
