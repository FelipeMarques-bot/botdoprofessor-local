import threading

from lancar_notas_sge import (
    ContextoTurma,
    RegistroNota,
    _aplicar_pendentes_ausentes,
    _aplicar_pendentes_revisao,
    _revisar_blocos_apos_lancamento,
)


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
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: "8,5")
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
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: "6,0")
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
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: "6,0")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: True)
    # Correcao automatica tentada e falhando (campo nao preenchido): cai na fila.
    monkeypatch.setattr(m, "_fill_grade_for_student", lambda *a, **k: "")

    def fake_verify_grade(shot, nota, aluno, logger=None):
        return {"found": True, "confirmed": False, "read_value": "6,0", "notes": "valor difere"}
    monkeypatch.setattr(m, "verify_grade_on_screen", fake_verify_grade)
    monkeypatch.setattr(m, "threading", threading)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["corrigidos"] == 0
    assert res["falhas"] == 1
    assert res["ai_usada"] == 1


def test_revisao_divergente_sem_coluna_nao_regrava(monkeypatch):
    """Sem coluna detectada (ambiguidade tipo 2a avaliacao), NAO corrige no lugar:
    o item vai para a fila manual — nunca regrava as cegas."""
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "")
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: "6,0")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: False)
    monkeypatch.setattr(m, "threading", threading)

    def assert_nao_chamado(*a, **k):
        raise AssertionError("nao deveria ter chamado _fill_grade_for_student sem coluna")
    monkeypatch.setattr(m, "_fill_grade_for_student", assert_nao_chamado)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["corrigidos"] == 0
    assert res["falhas"] == 1


def test_revisao_divergente_auto_corrige_com_coluna(monkeypatch):
    """Com coluna detectada e campo inequivoco, a nota errada e corrigida no lugar
    (so as notas erradas), confirmada e salva."""
    import lancar_notas_sge as m
    page = DummyPage()
    reg = _make_reg("ALUNO A", 8.5)
    blo = _make_bloco([reg])

    monkeypatch.setattr(m, "_select_context", lambda *a, **k: None)
    monkeypatch.setattr(m, "_open_assessment_for_context", lambda *a, **k: True)
    monkeypatch.setattr(m, "_handle_assessment_period_page", lambda *a, **k: False)
    monkeypatch.setattr(m, "_select_activity", lambda *a, **k: (True, "", 1))
    monkeypatch.setattr(m, "_detect_coluna_from_page", lambda *a, **k: "N1S")
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: "6,0")
    monkeypatch.setattr(m, "ai_is_enabled", lambda: False)
    monkeypatch.setattr(m, "_fill_grade_for_student", lambda *a, **k: "0001")
    monkeypatch.setattr(m, "_verify_fill_just_made", lambda *a, **k: True)
    monkeypatch.setattr(m, "threading", threading)

    res = _revisar_blocos_apos_lancamento(page, blo)
    assert res["revisados"] == 1
    assert res["corrigidos"] == 1
    assert res["ok"] == 1
    assert res["falhas"] == 0
    assert res["ai_usada"] == 0
    assert len(res["regs_corrigidos"]) == 1
    assert res["regs_corrigidos"][0].aluno == "ALUNO A"


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
    monkeypatch.setattr(m, "_read_grade_value_for_student_raw", lambda *a, **k: None)
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


def _pend(id_, aluno, decisao="confirmar", valor="", esperada="7,5"):
    return {
        "escola": "E1", "turno": "M", "turma": "T1", "trimestre": "1",
        "atividade": "N1S", "aluno": aluno,
        "decisao": decisao, "valor_corrigido": valor, "nota_esperada": esperada,
    }


def test_aplicar_pendentes_mantem_lote_quando_fila_antiga_nao_bate():
    regs = [_make_reg("ALUNO A", 8.5), _make_reg("ALUNO B", 7.0)]
    pendentes = [_pend("x", "ALUNO NAO EXISTE", esperada="9,0")]
    res, forcar = _aplicar_pendentes_revisao(regs, pendentes)
    assert forcar is False
    assert len(res) == 2
    assert res[0].nota == 8.5


def test_aplicar_pendentes_ignora_decisao_pular_e_vazio():
    regs = [_make_reg("ALUNO A", 8.5)]
    pendentes = [
        _pend("x", "ALUNO A", decisao="pular"),
        _pend("y", "ALUNO A", decisao=None),
        _pend("z", "ALUNO A", decisao=""),
    ]
    res, forcar = _aplicar_pendentes_revisao(regs, pendentes)
    assert forcar is False
    assert len(res) == 1
    assert res[0].nota == 8.5


def test_aplicar_pendentes_filtra_e_forca_nota_corrigida():
    regs = [_make_reg("ALUNO A", 8.5), _make_reg("ALUNO B", 7.0)]
    pendentes = [_pend("x", "ALUNO A", decisao="corrigir", valor="9,0")]
    res, forcar = _aplicar_pendentes_revisao(regs, pendentes)
    assert forcar is True
    assert len(res) == 1
    assert res[0].aluno == "ALUNO A"
    assert res[0].nota == 9.0


def test_aplicar_pendentes_confirmar_usa_nota_esperada():
    regs = [_make_reg("ALUNO A", 8.5)]
    pendentes = [_pend("x", "ALUNO A", decisao="confirmar", valor="", esperada="7,5")]
    res, forcar = _aplicar_pendentes_revisao(regs, pendentes)
    assert forcar is True
    assert res[0].nota == 7.5


def test_aplicar_pendentes_sem_fila_mantem_tudo():
    regs = [_make_reg("ALUNO A", 8.5)]
    res, forcar = _aplicar_pendentes_revisao(regs, [])
    assert forcar is False
    assert len(res) == 1


def _aus(id_, aluno, corrigido, decisao="retentar", esperada="9,5"):
    return {
        "tipo": "ausente",
        "escola": "E1", "turno": "M", "turma": "T1", "trimestre": "1",
        "atividade": "N1S", "aluno": aluno, "aluno_corrigido": corrigido,
        "nota_esperada": esperada, "data_realizacao": "01/08/2026",
        "decisao": decisao,
    }


def test_aplicar_ausentes_retenta_com_nome_corrigido():
    res = _aplicar_pendentes_ausentes([_aus("x", "ANTENOR ATZ I?", "ANTENOR ATZ")])
    assert len(res) == 1
    assert res[0].aluno == "ANTENOR ATZ"
    assert res[0].nota == 9.5
    assert res[0].atividade == "N1S"
    assert res[0].data_realizacao == "01/08/2026"


def test_aplicar_ausentes_usa_nome_original_sem_correcao():
    res = _aplicar_pendentes_ausentes([_aus("x", "MARIA S", "  ")])
    assert len(res) == 1
    assert res[0].aluno == "MARIA S"


def test_aplicar_ausentes_ignora_pular_vazio_e_divergencia():
    pend = [
        _aus("x", "Y", "Y2", decisao="pular"),
        _aus("y", "Z", "", decisao=None),
        _aus("z", "W", "", decisao=""),
        {
            "tipo": "divergencia", "escola": "E1", "aluno": "V",
            "aluno_corrigido": "V2", "nota_esperada": "8",
            "decisao": "retentar",
        },
    ]
    res = _aplicar_pendentes_ausentes(pend)
    assert len(res) == 0


def test_coletar_ausente_tem_campos_de_revisao(monkeypatch, tmp_path):
    import lancar_notas_sge as m

    monkeypatch.setattr(m, "REVISAO_DIR", str(tmp_path / "revisao"))
    monkeypatch.setattr(m, "_capturar_evidencia_divergencia", lambda *a, **k: None)

    ctx = ContextoTurma(escola="E1", turno="V", turma="T2", trimestre="2")
    item = m._coletar_ausente(None, ctx, "24-Resolucao de Problemas", "ANTENOR ATZ I?", "9,5", "", "01/08/2026")
    assert item["tipo"] == "ausente"
    assert item["aluno"] == "ANTENOR ATZ I?"
    assert item["aluno_corrigido"] == ""
    assert item["nova_imagem"] == ""
    assert item["nota_esperada"] == "9,5"
    assert item["data_realizacao"] == "01/08/2026"
    assert item["decisao"] is None
    assert item["id"]
    assert item["screenshot"].endswith(".png")

