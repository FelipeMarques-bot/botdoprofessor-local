"""Testes de homonimos na GRIDAGENDA: mesma atividade em datas diferentes.

A posicao escolhida para pular/lancar precisa casar nome + data, senao o bot
abre (ou pula) sempre a primeira ocorrencia do nome.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lancar_notas_sge as m

CTX = m.ContextoTurma(
    escola="Arapongas",
    turno="Vespertino",
    turma="6o Ano 1",
    trimestre="3o Trimestre",
)
ATIVIDADE = "21-Atividade avaliativa individual"


def _cache(itens):
    key = (CTX.escola, CTX.turno, CTX.turma, CTX.trimestre)
    m._sge_grade_order_cache[key] = itens


def test_prescan_escolhe_homonimo_pela_data():
    _cache([
        (ATIVIDADE, 1, "26/10"),
        (ATIVIDADE, 2, "23/10"),
    ])
    assert m._prescan_pode_pular(CTX, ATIVIDADE, "2026-10-23") == 2


def test_prescan_nao_usa_homonimo_com_data_divergente():
    _cache([
        (ATIVIDADE, 1, "26/10"),
        (ATIVIDADE, 2, "09/11"),
    ])
    assert m._prescan_pode_pular(CTX, ATIVIDADE, "2026-10-23") == 0


def test_prescan_sem_datas_na_grade_usa_primeira_por_nome():
    _cache([
        (ATIVIDADE, 1, ""),
        (ATIVIDADE, 2, ""),
    ])
    assert m._prescan_pode_pular(CTX, ATIVIDADE, "2026-10-23") == 1


def test_prescan_sem_data_informada_usa_primeira_por_nome():
    _cache([
        (ATIVIDADE, 1, "26/10"),
        (ATIVIDADE, 2, "23/10"),
    ])
    assert m._prescan_pode_pular(CTX, ATIVIDADE, "") == 1
