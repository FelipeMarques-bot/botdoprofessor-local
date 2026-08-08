import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from leitor_planilhas import (
    RegistroNota,
    linhas_para_registros,
    registros_para_linhas,
)
from status_store import StatusStore


def _linha(**kw):
    base = {
        "escola": "Juvenal", "turno": "Matutino", "turma": "6º Ano",
        "trimestre": "2º Trimestre", "aluno": "Ana", "atividade": "Prova 1",
        "nota": 8.5, "data_realizacao": "01/03/2026", "status": "",
    }
    base.update(kw)
    return base


class TestRegistrosParaLinhas:
    def test_converte_todos_os_campos(self):
        registros = [
            RegistroNota(
                escola="Juvenal", turno="Matutino", turma="6º Ano",
                trimestre="2º Trimestre", aluno="Ana", atividade="Atividade 1",
                nota=8.5, data_realizacao="01/03/2026",
            )
        ]
        linhas = registros_para_linhas(registros)
        assert len(linhas) == 1
        ln = linhas[0]
        assert ln["aluno"] == "Ana"
        assert ln["atividade"] == "Atividade 1"
        assert ln["nota"] == 8.5
        assert ln["data_realizacao"] == "01/03/2026"
        assert ln["status"] == ""

    def test_varios_registros(self):
        registros = [
            RegistroNota(escola="A", turno="", turma="", trimestre="",
                         aluno="Ana", atividade="P1", nota=9.0),
            RegistroNota(escola="A", turno="", turma="", trimestre="",
                         aluno="Bia", atividade="P1", nota=7.5),
        ]
        assert len(registros_para_linhas(registros)) == 2


class TestLinhasParaRegistros:
    def test_linha_valida_com_nota_virgula(self):
        regs = linhas_para_registros([_linha(nota="8,5")])
        assert len(regs) == 1
        assert regs[0].nota == 8.5
        assert regs[0].aluno == "Ana"
        assert regs[0].data_realizacao == "01/03/2026"

    def test_ignora_linha_sem_aluno(self):
        assert linhas_para_registros([_linha(aluno="")]) == []

    def test_ignora_linha_sem_atividade(self):
        assert linhas_para_registros([_linha(atividade="")]) == []

    def test_ignora_nota_fora_de_0_10(self):
        assert linhas_para_registros([_linha(nota=15.0)]) == []
        assert linhas_para_registros([_linha(nota=-1.0)]) == []

    def test_ignora_nota_nao_numerica(self):
        assert linhas_para_registros([_linha(nota="abc")]) == []
        assert linhas_para_registros([_linha(nota="")]) == []

    def test_usa_defaults_dos_filtros(self):
        regs = linhas_para_registros(
            [_linha(escola="", turno="", turma="", trimestre="")],
            defaults={
                "escola": "Juvenal", "turno": "Vespertino",
                "turma": "8º Ano", "trimestre": "3º Trimestre",
            },
        )
        assert regs[0].escola == "Juvenal"
        assert regs[0].turno == "Vespertino"
        assert regs[0].turma == "8º Ano"
        assert regs[0].trimestre == "3º Trimestre"

    def test_sem_defaults_usa_nao_informado(self):
        regs = linhas_para_registros([_linha(escola="", turno="", turma="", trimestre="")])
        assert regs[0].escola == "Nao informado"
        assert regs[0].turno == "Nao informado"
        assert regs[0].turma == "Nao informado"
        assert regs[0].trimestre == "Nao informado"

    def test_mistura_linhas_validas_e_invalidas(self):
        linhas = [
            _linha(aluno="Ana", nota=8.5),
            _linha(aluno="", nota=8.5),
            _linha(aluno="Bia", nota=12.0),
            _linha(aluno="Ceo", nota="7,0"),
        ]
        regs = linhas_para_registros(linhas)
        assert [r.aluno for r in regs] == ["Ana", "Ceo"]


class TestStatusPainel:
    def test_obter_status_roundtrip(self, tmp_path):
        store = StatusStore(str(tmp_path / "painel.xlsx"))
        assert store.obter_status("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 1") == ""
        store.marcar_lancada("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 1", 8.5)
        assert store.obter_status("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 1") == "Lancada"
        store.marcar_falha("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 2", 5.0, erro="x")
        assert store.obter_status("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 2") == "Falha"

    def test_obter_status_ignora_caixa_e_espacos(self, tmp_path):
        store = StatusStore(str(tmp_path / "painel.xlsx"))
        store.marcar_lancada("Escola A", "Matutino", "6o Ano", "2o Trimestre", "Ana", "Prova 1", 7.0)
        assert store.obter_status("  escola a ", "MATUTINO", "6o ANO", "2o TRIMESTRE", "ANA", "prova 1") == "Lancada"

    def test_status_persiste_entre_instancias(self, tmp_path):
        caminho = str(tmp_path / "painel.xlsx")
        StatusStore(caminho).marcar_lancada("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 1", 8.5)
        novo = StatusStore(caminho)
        assert novo.obter_status("A", "Matutino", "6º Ano", "2º Trimestre", "Ana", "Prova 1") == "Lancada"
