import threading

from lancar_notas_sge import ContextoTurma, RegistroNota, _revisar_blocos_apos_lancamento


class DummyPage:
    def __init__(self):
        self.url = "https://example.com"
        self.frames = []
        self._screenshot_count = 0

    def screenshot(self, **kwargs):
        self._screenshot_count += 1
        return b"fake-screenshot"

    def title(self):
        return "SGE"

    def evaluate(self, js, arg=None):
        return {}

    def locator(self, sel):
        return DummyLocator()

    def wait_for_selector(self, sel, timeout=None):
        return None

    def wait_for_timeout(self, ms):
        return None


class DummyLocator:
    def count(self):
        return 0

    def __getattr__(self, name):
        def _any(*args, **kwargs):
            return None
        return _any


def _make_reg(aluno, nota):
    return RegistroNota(
        escola="E1", turno="M", turma="T1", trimestre="1",
        aluno=aluno, atividade="N1S", nota=nota,
    )


def _make_bloco(itens):
    return [{
        "contexto": ContextoTurma(escola="E1", turno="M", turma="T1", trimestre="1"),
        "atividade": "N1S",
        "itens": itens,
        "data_realizacao": "01/08/2026",
    }]


def test_revisao_ok_todos_confirmados(monkeypatch):
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "N1S")
    monkeypatch.setattr(m, "_read_existing_grade_for_student", lambda *a, **k: "8,5")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: False)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["ok"] == 1
    assert res["falhas"] == 0
    assert res["ai_usada"] == 0


def test_revisao_divergente_sem_ia_marca_falha(monkeypatch):
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "N1S")
    monkeypatch.setattr(m, "_read_existing_grade_for_student", lambda *a, **k: "6,0")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: False)
    monkeypatch.setattr(m, "_fill_grade_for_student", lambda *a, **k: "")
    monkeypatch.setattr(m, "threading", threading)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["ok"] == 0
    assert res["falhas"] == 1
    assert res["corrigidos"] == 0


def test_revisao_divergente_ia_nao_confirma_nao_regrava(monkeypatch):
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "N1S")
    monkeypatch.setattr(m, "_read_existing_grade_for_student", lambda *a, **k: "6,0")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: True)

    def fake_verify_grade(shot, nota, aluno, logger=None):
        return {"found": True, "confirmed": False, "read_value": "6,0", "notes": "valor difere"}
    monkeypatch.setattr(m, "verify_grade_on_screen", fake_verify_grade)
    monkeypatch.setattr(m, "threading", threading)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["corrigidos"] == 0
    assert res["falhas"] == 1
    assert res["ai_usada"] == 1


def test_revisao_ia_confirma_mesmo_sem_ler_deterministico(monkeypatch):
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "")
    monkeypatch.setattr(m, "_read_existing_grade_for_student", lambda *a, **k: None)
    monkeypatch.setattr(m, "ai_is_enabled", lambda: True)

    def fake_verify_grade(shot, nota, aluno, logger=None):
        return {"found": True, "confirmed": True, "read_value": "8,5", "notes": "confirma"}
    monkeypatch.setattr(m, "verify_grade_on_screen", fake_verify_grade)
    monkeypatch.setattr(m, "threading", threading)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["ok"] == 1
    assert res["falhas"] == 0
    assert res["ai_usada"] == 1


def test_verify_grade_on_screen_sem_ia():
    from ai_assist import verify_grade_on_screen
    res = verify_grade_on_screen(b"x", "8,5", "ALUNO A")
    assert res["found"] is False
    assert res["confirmed"] is False
