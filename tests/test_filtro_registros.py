"""Testes de _filtrar_registros: fallback quando a data informada nao casa."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lancar_notas_sge import RegistroNota, _filtrar_registros


def _reg(atividade, data, aluno="Aluno"):
    return RegistroNota(
        escola="Maria Helena",
        turno="Vespertino",
        turma="6° ano",
        trimestre="3o Trimestre",
        aluno=aluno,
        atividade=atividade,
        nota=10.0,
        data_realizacao=data,
    )


def _filtro(**extra):
    base = {
        "escola": "Maria Helena",
        "turno": "Vespertino",
        "turma": "6° ano",
        "trimestre": "3o Trimestre",
    }
    base.update(extra)
    return base


def test_filtro_exato_atividade_e_data():
    regs = [
        _reg("21-Atividade avaliativa individual", "06/11/2026", "A"),
        _reg("5 - Aula Prática", "23/10/2026", "B"),
    ]
    out = _filtrar_registros(
        regs,
        _filtro(atividade="21-Atividade avaliativa individual", data_realizacao="06/11/2026"),
    )
    assert [r.aluno for r in out] == ["A"]


def test_data_errada_cai_para_filtro_por_atividade():
    """Caso real: data 23/10 pertence a outra atividade; nao deve zerar."""
    regs = [
        _reg("21-Atividade avaliativa individual", "06/11/2026", "A"),
        _reg("21-Atividade avaliativa individual", "06/11/2026", "B"),
        _reg("5 - Aula Prática", "23/10/2026", "C"),
    ]
    out = _filtrar_registros(
        regs,
        _filtro(atividade="21-Atividade avaliativa individual", data_realizacao="23/10/2026"),
    )
    assert [r.aluno for r in out] == ["A", "B"]


def test_data_informada_prevalece_sobre_a_do_notion():
    """Caso real (6o vespertino): Notion tem as datas invertidas entre as
    atividades; a data digitada pelo usuario e a que vale na validacao."""
    regs = [
        _reg("21-Atividade avaliativa individual", "2026-11-06", "A"),
        _reg("21-Atividade avaliativa individual", "2026-11-06", "B"),
        _reg("5 - Aula Prática", "2026-10-23", "C"),
    ]
    out = _filtrar_registros(
        regs,
        _filtro(atividade="21-Atividade avaliativa individual", data_realizacao="23/10/2026"),
    )
    assert [r.aluno for r in out] == ["A", "B"]
    assert {r.data_realizacao for r in out} == {"2026-10-23"}


def test_registro_sem_data_recebe_a_data_informada():
    """Notion sem 'Data realizacao': a data do filtro alimenta o cruzamento
    nome+data da GRIDAGENDA (homonimos com mesmo nome e datas diferentes)."""
    regs = [_reg("21-Atividade avaliativa individual", "", "A")]
    out = _filtrar_registros(
        regs,
        _filtro(atividade="21-Atividade avaliativa individual", data_realizacao="23/10/2026"),
    )
    assert [r.aluno for r in out] == ["A"]
    assert out[0].data_realizacao == "2026-10-23"


def test_atividade_inexistente_continua_vazio():
    regs = [_reg("5 - Aula Prática", "23/10/2026", "C")]
    out = _filtrar_registros(
        regs,
        _filtro(atividade="21-Atividade avaliativa individual", data_realizacao="23/10/2026"),
    )
    assert out == []
