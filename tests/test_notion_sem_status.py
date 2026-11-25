"""Testes de notas do Notion em colunas sem 'Status lancamento N' pareado."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lancar_notas_sge as mod


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.databases = self

    def retrieve(self, database_id):
        return {}


def _row(props):
    return {"id": "page-1", "properties": props}


def _props():
    return {
        "Nome": {"type": "title", "title": [{"plain_text": "Aluno A"}]},
        "13-Projeto": {"type": "number", "number": 8.5},
        "21-Atividade Avaliativa Individual": {"type": "number", "number": 9.0},
        "Total": {"type": "number", "number": 10},
        "Nota 2": {"type": "number", "number": 7.0},
    }


def _monkeypatch_notion(monkeypatch, props):
    monkeypatch.setattr(mod, "NOTION_TOKEN", "token")
    monkeypatch.setattr(mod, "ROOT_PAGE_ID", "root")
    monkeypatch.setattr(mod, "_normalize_notion_id", lambda value: "root-id")
    monkeypatch.setattr(mod, "_is_placeholder_env", lambda value: False)
    monkeypatch.setattr(mod, "Client", _FakeClient)
    monkeypatch.setattr(
        mod,
        "_search_databases_by_name",
        lambda *args, **kwargs: [("db", [], "Notas Escolas - Teste")],
    )
    monkeypatch.setattr(mod, "_db_metadata_cache", {"db": {}})
    monkeypatch.setattr(mod, "_database_title", lambda db: "Notas Escolas - Teste")
    monkeypatch.setattr(
        mod,
        "_infer_context",
        lambda texts: mod.ContextoTurma("Escola", "Vespertino", "9°1", "3o Trimestre"),
    )
    monkeypatch.setattr(mod, "_query_database_rows", lambda *args, **kwargs: [_row(props)])


def test_coluna_de_atividade_sem_status_continua_gerando_nota(monkeypatch):
    _monkeypatch_notion(monkeypatch, _props())

    registros = mod.carregar_notas_notion(logger=lambda msg: None)

    assert [(r.atividade, r.nota) for r in registros] == [
        ("13-Projeto", 8.5),
        ("21-Atividade Avaliativa Individual", 9.0),
    ]
    assert {r.notion_status_prop for r in registros} == {""}


def test_coluna_generica_sem_status_continua_sendo_ignorada(monkeypatch):
    props = {
        "Nome": {"type": "title", "title": [{"plain_text": "Aluno A"}]},
        "Total": {"type": "number", "number": 10},
    }
    _monkeypatch_notion(monkeypatch, props)

    try:
        mod.carregar_notas_notion(logger=lambda msg: None)
    except mod.LancamentoError:
        return
    raise AssertionError("coluna generica sem status nao deveria virar nota")
