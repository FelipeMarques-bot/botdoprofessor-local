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


class TestSobrescreverDivergentes:
    """Padrao seguro: NAO sobrescrever nota divergente; opt-in via env var."""

    def test_padrao_e_false(self, monkeypatch):
        from lancar_notas_sge import _sobrescrever_divergentes

        monkeypatch.delenv("SGE_SOBRESCREVER_DIVERGENTES", raising=False)
        assert _sobrescrever_divergentes() is False

    def test_true_quando_env_ativo(self, monkeypatch):
        from lancar_notas_sge import _sobrescrever_divergentes

        monkeypatch.setenv("SGE_SOBRESCREVER_DIVERGENTES", "1")
        assert _sobrescrever_divergentes() is True

    def test_false_para_valor_estranho(self, monkeypatch):
        from lancar_notas_sge import _sobrescrever_divergentes

        monkeypatch.setenv("SGE_SOBRESCREVER_DIVERGENTES", "0")
        assert _sobrescrever_divergentes() is False


class TestDecisaoDivergenciaFailSafe:
    """Matriz de decisao: nota divergente nao pode ser sobrescrita sem opt-in."""

    def test_divergente_sem_override_nao_sobrescreve(self, monkeypatch):
        from lancar_notas_sge import _classificar_leitura, _sobrescrever_divergentes

        monkeypatch.delenv("SGE_SOBRESCREVER_DIVERGENTES", raising=False)
        classe = _classificar_leitura("7,5", "10,0")
        assert classe == "divergente"
        assert not _sobrescrever_divergentes()
        assert not (classe == "divergente" and _sobrescrever_divergentes())

    def test_divergente_com_override_sobrescreve(self, monkeypatch):
        from lancar_notas_sge import _classificar_leitura, _sobrescrever_divergentes

        monkeypatch.setenv("SGE_SOBRESCREVER_DIVERGENTES", "1")
        classe = _classificar_leitura("7,5", "10,0")
        assert classe == "divergente"
        assert _sobrescrever_divergentes()
        assert classe == "divergente" and _sobrescrever_divergentes()

    def test_vazio_sempre_preenche(self):
        from lancar_notas_sge import _classificar_leitura

        assert _classificar_leitura(None, "10,0") == "vazio"
        assert _classificar_leitura(None, "10,0") != "divergente"


class TestAutoCorrigirRevisao:
    """Correcao automatica na re-auditoria e ligada por padrao; so age com campo
    inequivoco + coluna detectada (as gates ficam na logica do loop)."""

    def test_padrao_e_ligado(self, monkeypatch):
        from lancar_notas_sge import _auto_corrigir_revisao

        monkeypatch.delenv("SGE_AUTO_CORRIGIR", raising=False)
        assert _auto_corrigir_revisao() is True

    def test_desligado_com_env_0(self, monkeypatch):
        from lancar_notas_sge import _auto_corrigir_revisao

        monkeypatch.setenv("SGE_AUTO_CORRIGIR", "0")
        assert _auto_corrigir_revisao() is False

    def test_ligado_com_env_1(self, monkeypatch):
        from lancar_notas_sge import _auto_corrigir_revisao

        monkeypatch.setenv("SGE_AUTO_CORRIGIR", "1")
        assert _auto_corrigir_revisao() is True
