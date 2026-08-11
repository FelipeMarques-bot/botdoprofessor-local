class TestImageGradesAlphabeticSort:
    def test_sort_alunos_alphabetically(self):
        from bot.utils.image_grade_extractor import _sort_alunos_alphabetically

        alunos = [
            {"aluno": "Maria Silva", "nota": "8.5"},
            {"aluno": "Álvaro Souza", "nota": "7.0"},
            {"aluno": "ana oliveira", "nota": "9.2"},
            {"aluno": "Beatriz Lima", "nota": "6.0"},
        ]
        ordenado = _sort_alunos_alphabetically(alunos)
        nomes = [a["aluno"] for a in ordenado]
        assert nomes == ["ana oliveira", "Álvaro Souza", "Beatriz Lima", "Maria Silva"]

    def test_extract_grades_returns_sorted(self, monkeypatch):
        import ai_assist
        from bot.utils import image_grade_extractor as ige

        def fake_ai(prompt, image_bytes, logger=None, deadline=None):
            return (
                '{"alunos":[{"aluno":"Maria Silva","nota":"8.5"},'
                '{"aluno":"Joao Santos","nota":"7.0"},'
                '{"aluno":"Ana Oliveira","nota":"9.2"}],'
                '"total_encontrados":3,"confianca":"alta"}'
            )

        monkeypatch.setattr(ai_assist, "_call_ai_with_fallback", fake_ai)
        result = ige.extract_grades_from_image(b"fake-image-bytes")
        nomes = [a["aluno"] for a in result["alunos"]]
        assert nomes == ["Ana Oliveira", "Joao Santos", "Maria Silva"]
        assert result["total_encontrados"] == 3

    def test_prompt_asks_for_alphabetic_order(self):
        from bot.utils.image_grade_extractor import EXTRACT_GRADES_PROMPT

        assert "ORDEM ALFABETICA" in EXTRACT_GRADES_PROMPT
        assert "A-Z" in EXTRACT_GRADES_PROMPT
