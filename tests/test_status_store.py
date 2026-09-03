"""Testes do StatusStore.obter_status_tolerante (busca com contexto parcial)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from status_store import StatusStore


class TestObterStatusTolerante(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fonte = os.path.join(self._tmp.name, "fonte.xlsx")
        self.store = StatusStore(self.fonte)
        # Cenario real: lancamento gravou com turno/trimestre preenchidos
        # pelos filtros, mas a linha do painel tem esses campos vazios.
        self.store.marcar_lancada(
            "Tancredo", "Matutino", "6º2", "2o Trimestre",
            "Lorrayne Vitoria Silva", "Nota N-1", 9.5,
        )
        self.store.marcar_falha(
            "Mulde", "Matutino", "6º1", "2o Trimestre",
            "arturdesouzabatalha", "Nota N-1", 3.0,
            erro="aluno nao localizado na grade",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_chave_exata_continua_funcionando(self):
        status = self.store.obter_status_tolerante(
            "tancredo", "matutino", "6º2", "2o trimestre",
            "Lorrayne Vitoria Silva", "Nota N-1",
        )
        self.assertEqual(status, "Lancada")

    def test_contexto_vazio_encontra_por_aluno_atividade(self):
        """Linha do Forms com Turno/Trimestre vazios acha o registro gravado."""
        status = self.store.obter_status_tolerante(
            "Tancredo", "", "6º2", "", "Lorrayne Vitoria Silva", "Nota N-1",
        )
        self.assertEqual(status, "Lancada")

    def test_falha_com_erro_e_refletida(self):
        status = self.store.obter_status_tolerante(
            "Mulde", "", "6º1", "", "arturdesouzabatalha", "Nota N-1",
        )
        self.assertEqual(status, "Falha")

    def test_escola_diferente_nao_casa(self):
        status = self.store.obter_status_tolerante(
            "Anna Alves", "", "6º2", "", "Lorrayne Vitoria Silva", "Nota N-1",
        )
        self.assertEqual(status, "")

    def test_turma_diferente_nao_casa(self):
        status = self.store.obter_status_tolerante(
            "Tancredo", "", "6º1", "", "Lorrayne Vitoria Silva", "Nota N-1",
        )
        self.assertEqual(status, "")

    def test_aluno_inexistente_retorna_vazio(self):
        status = self.store.obter_status_tolerante(
            "Tancredo", "", "6º2", "", "Fulano De Tal", "Nota N-1",
        )
        self.assertEqual(status, "")

    def test_atividade_vazia_retorna_vazio(self):
        status = self.store.obter_status_tolerante(
            "Tancredo", "", "6º2", "", "Lorrayne Vitoria Silva", "",
        )
        self.assertEqual(status, "")

    def test_preferencia_por_contexto_mais_completo(self):
        """Mesmo aluno+atividade em escolas diferentes: consulta com escola
        preenchida deve escolher o registro da escola informada."""
        self.store.marcar_lancada(
            "Mulde", "Matutino", "6º2", "2o Trimestre",
            "Lorrayne Vitoria Silva", "Nota N-1", 5.0,
        )
        status = self.store.obter_status_tolerante(
            "Mulde", "", "6º2", "", "Lorrayne Vitoria Silva", "Nota N-1",
        )
        self.assertEqual(status, "Lancada")


if __name__ == "__main__":
    unittest.main()
