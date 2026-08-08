import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lancar_notas_sge import _classificar_leitura


class TestClassificarLeitura:
    def test_vazio_quando_none(self):
        assert _classificar_leitura(None, "8,5") == "vazio"

    def test_ok_quando_valor_confere(self):
        assert _classificar_leitura("8,5", "8.5") == "ok"
        assert _classificar_leitura("8.5", "8,5") == "ok"
        assert _classificar_leitura("9", "9,0") == "ok"

    def test_divergente_quando_valor_diferente(self):
        assert _classificar_leitura("6,0", "8,5") == "divergente"

    def test_ok_quando_ambos_vazios_nao(self):
        assert _classificar_leitura("", "8,5") == "divergente"
