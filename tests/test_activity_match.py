class TestActivityMatch:
    """Casamento entre o nome da atividade (planilha) e o link da GRIDAGENDA."""

    def test_caso_real_bug_notas_n1(self):
        """Regressao: planilha 'Notas N-1' nao casava com 'Nota N-1' da GRIDAGENDA."""
        from lancar_notas_sge import _activity_match

        assert _activity_match("Notas N-1", "Nota N-1") is True
        assert _activity_match("Nota N-1", "Notas N-1") is True

    def test_plural_singular_geral(self):
        from lancar_notas_sge import _activity_match

        assert _activity_match("Aulas Práticas", "5-Aula Prática") is True
        assert _activity_match("Autoavaliações", "28-Autoavaliação") is True

    def test_prefixo_numerico_da_grade(self):
        from lancar_notas_sge import _activity_match

        assert _activity_match("Prova Oral", "14-Prova Oral") is True
        assert _activity_match("Ponto Extra", "Ponto Extra") is True

    def test_nao_casa_atividades_diferentes(self):
        from lancar_notas_sge import _activity_match

        assert _activity_match("Prova Oral", "Prova Escrita") is False
        assert _activity_match("Nota N-1", "Ponto Extra") is False
        assert _activity_match("Aula Prática", "14-Prova Oral") is False

    def test_numeros_diferentes_nao_casam(self):
        from lancar_notas_sge import _activity_match

        assert _activity_match("Atividade 1", "Atividade 2") is False
        assert _activity_match("Nota N-1", "Nota N-2") is False
