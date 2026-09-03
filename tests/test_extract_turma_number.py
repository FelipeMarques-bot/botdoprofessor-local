class TestExtractTurmaNumber:
    """Numero da turma a partir do campo turma da planilha/contexto."""

    def test_formato_canonico_pipe(self):
        from lancar_notas_sge import _extract_turma_number

        assert _extract_turma_number("6º Ano|1") == "1"
        assert _extract_turma_number("9o Ano | 2") == "2"

    def test_formato_turma_prefixada(self):
        from lancar_notas_sge import _extract_turma_number

        assert _extract_turma_number("Turma 3") == "3"
        assert _extract_turma_number("7º Ano - VESPERTINO - Turma 1 - 2º Trimestre") == "1"

    def test_formato_ano_colado(self):
        from lancar_notas_sge import _extract_turma_number

        assert _extract_turma_number("6º Ano1") == "1"
        assert _extract_turma_number("7o ano2") == "2"

    def test_formato_compacto_planilha(self):
        from lancar_notas_sge import _extract_turma_number

        assert _extract_turma_number("7°2") == "2"
        assert _extract_turma_number("6º1") == "1"
        assert _extract_turma_number("8-3") == "3"
        assert _extract_turma_number("9.2") == "2"
        assert _extract_turma_number("7o2") == "2"
        assert _extract_turma_number("5 4") == "4"
        assert _extract_turma_number("72") == "2"

    def test_sem_numero_de_turma(self):
        from lancar_notas_sge import _extract_turma_number

        assert _extract_turma_number("") == ""
        assert _extract_turma_number("7º Ano") == ""
        assert _extract_turma_number("7") == ""
        assert _extract_turma_number("6º Ano A") == ""

    def test_caso_real_bug_7grau2(self):
        """Regressao: planilha '7°2' abria a grade da Turma 1 (aluno ausente)."""
        from lancar_notas_sge import _extract_first_number, _extract_turma_number

        turma = "7°2"
        assert _extract_first_number(turma) == "7"
        assert _extract_turma_number(turma) == "2"


class TestSuggestSimilarStudents:
    def test_sugere_nome_parecido(self):
        from lancar_notas_sge import _suggest_similar_students

        grade = [
            "AGATHA SOPHIA NASCIMENTO SANTOS",
            "BRENO ANTUNES",
            "EMANUELLE CARDOSO SILVEIRA",
            "ENRIC RUAN FOGAÇA",
        ]
        sugestoes = _suggest_similar_students("Emanuel Cardoso Silveira", grade)
        assert sugestoes
        assert any("EMANUELLE" in s for s in sugestoes)

    def test_sem_sugestao_para_nome_alienigena(self):
        from lancar_notas_sge import _suggest_similar_students

        grade = ["AGATHA SOPHIA NASCIMENTO SANTOS", "BRENO ANTUNES"]
        assert _suggest_similar_students("Xqwz Krxmvl", grade) == []

    def test_acentos_e_maiusculas(self):
        from lancar_notas_sge import _suggest_similar_students

        grade = ["ÉRIKA SCHMITZ PINTO"]
        sugestoes = _suggest_similar_students("Erika Schmitz Pinto", grade)
        assert sugestoes == ["ÉRIKA SCHMITZ PINTO"]
