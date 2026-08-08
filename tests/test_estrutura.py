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
        monkeypatch.setattr(m, "_verify_fill_js", lambda *a, **k: True)

        class P:
            pass

        ok = m._verify_fill_just_made(P(), "ANA", "8,5", None, coluna_sge="N2S", filled_suffix="0001")
        assert ok is True

    def test_verificacao_nao_confia_sem_filtro_de_coluna(self, monkeypatch):
        import lancar_notas_sge as m

        # _read_grade_value_js retorna None (campo nao relido na coluna) -> falha
        class NoReadScope:
            def evaluate(self, js, arg=None):
                return None

        monkeypatch.setattr(m, "_iter_scopes", lambda page: [NoReadScope()])
        monkeypatch.setattr(m, "_wait_student_slots", lambda scope, attempts=4, delay_ms=200: [{"suffix": "0001", "aluno": "ANA"}])
        monkeypatch.setattr(m, "_candidate_suffixes_for_student", lambda expected, slots: ["0001"])
        monkeypatch.setattr(m, "_verify_fill_js", lambda *a, **k: True)

        class P:
            pass

        ok = m._verify_fill_just_made(P(), "ANA", "8,5", None, coluna_sge="N2S", filled_suffix="0001")
        assert ok is False
