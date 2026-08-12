from lancar_notas_sge import _build_grade_status_map


def _props(keys):
    return {k: {} for k in keys}


def test_mapa_tancredo_mat_8_atividade3_nao_vaza_para_status2():
    props = _props([
        "Observações 2", "Status Fluxo", "Observações 1", "Data realização 1",
        "24-Resolução de Problemas", "Atividade 3", "Data realização 2",
        "Última Atualização", "17-Simulado", "Observações 3",
        "Status lancamento 3", "Status lancamento 2", "Status lancamento 1",
        "Data realização 3", "Name",
    ])
    mapa = _build_grade_status_map(props)
    assert mapa["24-Resolução de Problemas"] == "Status lancamento 1"
    assert mapa["17-Simulado"] == "Status lancamento 2"
    assert mapa["Atividade 3"] == "Status lancamento 3"


def test_mapa_maria_helena_mat_6():
    props = _props([
        "14 - Prova Oral", "Data realização 1", "Observações 1", "Última Atualização",
        "Atividade 3", "Status lancamento 2", "Data realização 3", "Observações 3",
        "Status lancamento 1", "Observações 2", "Status Fluxo", "Data realização 2",
        "Status lancamento 3", "5 - Aula Prática", "Name",
    ])
    mapa = _build_grade_status_map(props)
    assert mapa["14 - Prova Oral"] == "Status lancamento 1"
    assert mapa["5 - Aula Prática"] == "Status lancamento 2"
    assert mapa["Atividade 3"] == "Status lancamento 3"


def test_mapa_pesquisa_nao_vaza_para_status1():
    props = _props([
        "21-Atividade Avaliativa Individua", "3-Pesquisa", "Atividade 3",
        "Data realização 1", "Data realização 2", "Data realização 3",
        "Name", "Observações 1", "Observações 2", "Observações 3",
        "Status Fluxo", "Status lancamento 1", "Status lancamento 2",
        "Status lancamento 3", "Última Atualização",
    ])
    mapa = _build_grade_status_map(props)
    assert mapa["21-Atividade Avaliativa Individua"] == "Status lancamento 1"
    assert mapa["3-Pesquisa"] == "Status lancamento 2"
    assert mapa["Atividade 3"] == "Status lancamento 3"


def test_mapa_juvenal_9ano_ordem_real_api():
    props = _props([
        "21-Atividade Avaliativa Individua", "Observações 1", "Observações 3",
        "3-Pesquisa", "Data realização 3", "Status lancamento 2",
        "Data realização 2", "Status lancamento 3", "Data realização 1",
        "Status Fluxo", "Status lancamento 1", "Última Atualização",
        "Atividade 3", "Observações 2", "Name",
    ])
    mapa = _build_grade_status_map(props)
    assert mapa["21-Atividade Avaliativa Individua"] == "Status lancamento 1"
    assert mapa["3-Pesquisa"] == "Status lancamento 2"
    assert mapa["Atividade 3"] == "Status lancamento 3"
