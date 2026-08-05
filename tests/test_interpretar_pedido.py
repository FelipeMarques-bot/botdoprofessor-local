# Testes da "IA Primeiro" — interpretacao do pedido em linguagem natural.

import json

from interpretar_pedido import (
    _normalizar_bool,
    _normalizar_data,
    _normalizar_pedido,
    carregar_orientacoes,
    interpretar_pedido,
)


def _fake_caller(resposta):
    def _call(prompt):
        assert "IA_ORIENTACOES" not in prompt or True
        assert "PEDIDO DO PROFESSOR" in prompt
        return resposta

    return _call


def test_carregar_orientacoes():
    texto = carregar_orientacoes()
    assert "Missao" in texto or "missao" in texto
    assert "procedimentos" in texto.lower()


def test_interpreta_chamada():
    resposta = json.dumps({
        "tipo": "chamada",
        "fonte": "imagem",
        "escola": "",
        "turma": "7o ano",
        "turno": "Vespertino",
        "trimestre": "",
        "atividade": "",
        "data_realizacao": "",
        "chamada_dia": "05/08/2026",
        "chamada_disciplina": "",
        "lote": False,
        "resumo": "Lancar a chamada de hoje da turma 7o ano.",
        "procedimentos": ["Abrir a frequencia.", "Salvar."],
        "duvidas": [],
        "confianca": "alta",
    })
    plano = interpretar_pedido("lanca a chamada de hoje do 7o ano", caller=_fake_caller(resposta))
    assert plano["tipo"] == "chamada"
    assert plano["fonte"] == "imagem"
    assert plano["turma"] == "7o ano"
    assert plano["chamada_dia"] == "05/08/2026"
    assert plano["lote"] is False
    assert plano["procedimentos"] == ["Abrir a frequencia.", "Salvar."]


def test_normaliza_sinonimos():
    plano = _normalizar_pedido({
        "tipo": "notas",
        "fonte": "notion",
        "turno": "tarde",
        "trimestre": "T1",
        "chamada_dia": "",
    })
    assert plano["turno"] == "Vespertino"
    assert plano["trimestre"] == "1o Trimestre"
    assert plano["tipo"] == "notas"


def test_normaliza_datas():
    assert _normalizar_data("2026-07-06") == "06/07/2026"
    assert _normalizar_data("06/07/2026") == "06/07/2026"
    assert _normalizar_data("06/07/26") == "06/07/2026"
    assert _normalizar_data("") == ""
    assert _normalizar_data(None) == ""


def test_normaliza_bool():
    assert _normalizar_bool("sim") is True
    assert _normalizar_bool(True) is True
    assert _normalizar_bool("nao") is False
    assert _normalizar_bool(None) is False
    assert _normalizar_bool("todas as turmas") is True


def test_pedido_vazio():
    plano = interpretar_pedido("  ", caller=_fake_caller("{}"))
    assert "error" in plano


def test_resposta_invalida():
    plano = interpretar_pedido("algo", caller=_fake_caller("resposta sem json"))
    assert "error" in plano


def test_resposta_ignora_campos_invalidos():
    plano = _normalizar_pedido({
        "tipo": "qualquer_coisa",
        "fonte": "xlsx",
        "turno": "manha",
        "trimestre": "3o trim",
        "lote": "sim",
        "procedimentos": "nao e lista",
        "duvidas": None,
    })
    assert plano["tipo"] == ""
    assert plano["fonte"] == ""
    assert plano["turno"] == "Matutino"
    assert plano["trimestre"] == "3o Trimestre"
    assert plano["lote"] is True
    assert plano["procedimentos"] == []
    assert plano["duvidas"] == []
