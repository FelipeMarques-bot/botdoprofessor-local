class TestNormalizeNota:
    def test_comma_and_dot(self):
        from ai_assist import _normalize_nota

        assert _normalize_nota("8,5") == "8.5"
        assert _normalize_nota("7.0") == "7"
        assert _normalize_nota("10") == "10"
        assert _normalize_nota(9.75) == "9.75"
        assert _normalize_nota(6) == "6"

    def test_invalid_values(self):
        from ai_assist import _normalize_nota

        assert _normalize_nota("abc") is None
        assert _normalize_nota("") is None
        assert _normalize_nota(None) is None
        assert _normalize_nota(-3) is None
        assert _normalize_nota(9999) is None


class TestExtractGradeRecords:
    def test_plain_array(self):
        from ai_assist import _extract_grade_records

        resposta = '[{"aluno": "Ana Oliveira", "nota": "9,2"}, {"aluno": "Joao Santos", "nota": "7.0"}]'
        recs = _extract_grade_records(resposta)
        assert len(recs) == 2
        assert recs[0] == {"aluno": "Ana Oliveira", "nota": "9.2"}

    def test_code_fence_and_surrounding_text(self):
        from ai_assist import _extract_grade_records

        resposta = 'Aqui estao as notas:\n```json\n[{"aluno": "Maria", "nota": "8,5"}]\n```\nFim.'
        recs = _extract_grade_records(resposta)
        assert recs == [{"aluno": "Maria", "nota": "8.5"}]

    def test_object_with_alunos_key(self):
        from ai_assist import _extract_grade_records

        resposta = '{"alunos": [{"aluno": "Ana", "nota": "9"}, {"aluno": "Bia", "nota": "7"}], "total_encontrados": 2}'
        recs = _extract_grade_records(resposta)
        assert len(recs) == 2
        assert recs[1]["aluno"] == "Bia"

    def test_skips_invalid_items(self):
        from ai_assist import _extract_grade_records

        resposta = '[{"aluno": "", "nota": "8"}, {"nota": "7"}, {"aluno": "Valido", "nota": "x"}, {"aluno": "Ok", "nota": "6"}]'
        recs = _extract_grade_records(resposta)
        assert recs == [{"aluno": "Ok", "nota": "6"}]

    def test_empty_or_garbage(self):
        from ai_assist import _extract_grade_records

        assert _extract_grade_records("") == []
        assert _extract_grade_records("nao consegui ler nada") == []
        assert _extract_grade_records("[]") == []


class TestExtrairNotasImagem:
    def test_returns_alphabetical_sorted(self, monkeypatch):
        from ai_assist import extrair_notas_imagem

        calls = []

        def fake_call(prompt, image_bytes, logger=None):
            calls.append(prompt)
            return (
                '[{"aluno": "Maria Silva", "nota": "8,5"},'
                '{"aluno": "Álvaro Souza", "nota": "7.0"},'
                '{"aluno": "ana oliveira", "nota": "9,2"},'
                '{"aluno": "Beatriz Lima", "nota": "6"}]'
            )

        monkeypatch.setattr("ai_assist._call_ai_with_fallback", fake_call)
        result = extrair_notas_imagem(b"fake-image")
        nomes = [r["aluno"] for r in result]
        assert nomes == ["ana oliveira", "Álvaro Souza", "Beatriz Lima", "Maria Silva"]
        assert calls and "JSON array" in calls[0]

    def test_retries_when_first_read_empty(self, monkeypatch):
        from ai_assist import extrair_notas_imagem

        calls = []

        def fake_call(prompt, image_bytes, logger=None):
            calls.append(prompt)
            if len(calls) == 1:
                return "nao encontrei nada"
            return '[{"aluno": "Joao", "nota": "8,0"}]'

        monkeypatch.setattr("ai_assist._call_ai_with_fallback", fake_call)
        result = extrair_notas_imagem(b"fake-image", retries=1)
        assert len(calls) == 2
        assert result == [{"aluno": "Joao", "nota": "8"}]

    def test_empty_image_returns_empty(self):
        from ai_assist import extrair_notas_imagem

        assert extrair_notas_imagem(b"") == []


class TestProviderFallback:
    def test_fallback_to_configured_web_provider(self, monkeypatch):
        import ai_assist

        monkeypatch.setenv("AI_PROVIDER", "local")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")

        monkeypatch.setattr(ai_assist, "_is_ollama_running", lambda: False)

        def fake_openai(prompt, image_bytes, images=None):
            return '[{"aluno": "Via Web", "nota": "9"}]'

        monkeypatch.setattr(ai_assist, "_call_openai", fake_openai)
        recs = ai_assist.extrair_notas_imagem(b"fake-image")
        assert recs == [{"aluno": "Via Web", "nota": "9"}]
