"""Testes de filtrar_linhas_por_filtros (filtros do painel restringem linhas)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from leitor_planilhas import filtrar_linhas_por_filtros


def _linha(escola="", turno="", turma="", trimestre="", aluno="Aluno Teste"):
    return {
        "escola": escola, "turno": turno, "turma": turma,
        "trimestre": trimestre, "aluno": aluno,
        "atividade": "Nota N-1", "nota": 5.0,
    }


class TestFiltrarLinhasPorFiltros(unittest.TestCase):
    def test_sem_filtros_mantém_tudo(self):
        linhas = [_linha(escola="Mulde"), _linha(escola="Tancredo")]
        mantidas, descartadas = filtrar_linhas_por_filtros(linhas, {})
        self.assertEqual(len(mantidas), 2)
        self.assertEqual(descartadas, 0)

    def test_filtros_vazios_em_branco_ignorados(self):
        linhas = [_linha(escola="Mulde")]
        mantidas, _ = filtrar_linhas_por_filtros(
            linhas, {"escola": "", "turno": "", "turma": "", "trimestre": ""},
        )
        self.assertEqual(len(mantidas), 1)

    def test_filtro_escola_descarta_outras_escolas(self):
        linhas = [
            _linha(escola="Anna Alves", aluno="A"),
            _linha(escola="Tancredo", aluno="B"),
            _linha(escola="Mulde", aluno="C"),
        ]
        mantidas, descartadas = filtrar_linhas_por_filtros(
            linhas, {"escola": "Anna Alves"},
        )
        self.assertEqual(descartadas, 2)
        self.assertEqual([ln["aluno"] for ln in mantidas], ["A"])

    def test_caso_e_acento_insensivel(self):
        linhas = [_linha(escola="anna alves")]
        mantidas, descartadas = filtrar_linhas_por_filtros(
            linhas, {"escola": "ANNA ALVES"},
        )
        self.assertEqual(descartadas, 0)
        self.assertEqual(len(mantidas), 1)

    def test_turma_o_masculino_igual_degree(self):
        """'6º1' e '6°1' (ordinal vs grau) devem casar."""
        linhas = [_linha(turma="6°1"), _linha(turma="6º2")]
        mantidas, descartadas = filtrar_linhas_por_filtros(
            linhas, {"turma": "6º1"},
        )
        self.assertEqual(descartadas, 1)
        self.assertEqual(mantidas[0]["turma"], "6°1")

    def test_campo_vazio_na_linha_herda_filtro(self):
        """Linha sem turno + filtro Matutino: casa (mesmo comportamento do fill)."""
        linhas = [_linha(turno="")]
        mantidas, descartadas = filtrar_linhas_por_filtros(
            linhas, {"turno": "Matutino"},
        )
        self.assertEqual(descartadas, 0)
        self.assertEqual(len(mantidas), 1)

    def test_filtros_combinados(self):
        linhas = [
            _linha(escola="Anna Alves", turno="Vespertino", turma="6º1", aluno="A"),
            _linha(escola="Anna Alves", turno="Matutino", turma="6º1", aluno="B"),
            _linha(escola="Tancredo", turno="Vespertino", turma="6º1", aluno="C"),
        ]
        mantidas, descartadas = filtrar_linhas_por_filtros(
            linhas, {"escola": "Anna Alves", "turno": "Vespertino"},
        )
        self.assertEqual(descartadas, 2)
        self.assertEqual([ln["aluno"] for ln in mantidas], ["A"])

    def test_nao_mutar_entrada(self):
        linhas = [_linha(escola="Tancredo")]
        filtrar_linhas_por_filtros(linhas, {"escola": "Anna Alves"})
        self.assertEqual(len(linhas), 1)


class TestValoresDistintos(unittest.TestCase):
    def test_unifica_grafias_e_ordena(self):
        from leitor_planilhas import valores_distintos

        linhas = [
            _linha(turma="6°1"), _linha(turma="6º1"),
            _linha(turma="6º2"), _linha(turma=""),
        ]
        self.assertEqual(valores_distintos(linhas, "turma"), ["6°1", "6º2"])

    def test_campo_inexistente_retorna_vazio(self):
        from leitor_planilhas import valores_distintos

        self.assertEqual(valores_distintos([_linha()], "escola"), [])

    def test_escolas_distintas(self):
        from leitor_planilhas import valores_distintos

        linhas = [
            _linha(escola="Anna Alves"), _linha(escola="anna alves"),
            _linha(escola="Mulde"),
        ]
        self.assertEqual(valores_distintos(linhas, "escola"), ["Anna Alves", "Mulde"])


if __name__ == "__main__":
    unittest.main()
