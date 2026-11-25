import lancar_notas_sge as sge
from lancar_notas_sge import ContextoTurma


class FakePage:
    pass


def test_turma_unica_do_portal_e_usada_quando_turma_da_planilha_nao_existe(monkeypatch):
    contexto = ContextoTurma(
        escola="Anna Alves", turno="Vespertino", turma="9°2", trimestre="3o Trimestre"
    )
    chamadas = []
    logs = []

    def fake_attempt(page, turma_num, trimestre_num, turno_norm, logger):
        chamadas.append(turma_num)
        return turma_num == ""

    monkeypatch.setattr(sge, "_set_filters_on_portal", lambda *a, **k: None)
    monkeypatch.setattr(sge, "_voltar_apos_pagina_errada", lambda *a, **k: None)
    monkeypatch.setattr(sge, "_attempt_open_assessment", fake_attempt)
    monkeypatch.setattr(sge, "_listar_turmas_no_grid", lambda page: ["Turma 1"])
    sge._set_aceitar_turma_unica(True)
    try:
        aberto = sge._open_assessment_for_context(
            FakePage(), contexto, logger=logs.append
        )
    finally:
        sge._set_aceitar_turma_unica(False)

    assert aberto is True
    assert chamadas == ["2", "2", ""]
    assert any("[TURMA-UNICA]" in linha for linha in logs)


def test_sem_opcao_turma_inexistente_continua_gerando_pulo(monkeypatch):
    contexto = ContextoTurma(
        escola="Anna Alves", turno="Vespertino", turma="9°2", trimestre="3o Trimestre"
    )
    monkeypatch.setattr(sge, "_set_filters_on_portal", lambda *a, **k: None)
    monkeypatch.setattr(sge, "_voltar_apos_pagina_errada", lambda *a, **k: None)
    monkeypatch.setattr(sge, "_attempt_open_assessment", lambda *a, **k: False)
    monkeypatch.setattr(sge, "_listar_turmas_no_grid", lambda page: ["Turma 1"])
    monkeypatch.setattr(sge, "_learning_store", type("FakeStore", (), {"registrar_falha": lambda *a, **k: None})())
    logs = []
    sge._set_aceitar_turma_unica(False)

    try:
        sge._open_assessment_for_context(FakePage(), contexto, logger=logs.append)
    except sge.TurmaNaoEncontradaError as exc:
        assert "Turma '9°2'" in str(exc)
        assert any("Nenhuma linha encontrada com o filtro de turma '2'" in linha for linha in logs)
    else:
        raise AssertionError("TurmaNaoEncontradaError nao foi levantado")
