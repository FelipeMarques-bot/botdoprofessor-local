import pytest


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

        def fake_call(prompt, image_bytes, logger=None, deadline=None):
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

        def fake_call(prompt, image_bytes, logger=None, deadline=None):
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


class TestModelLoadError:
    def test_detects_arch_marker(self):
        from ai_assist import _is_model_load_error

        assert _is_model_load_error("error loading model: unknown model architecture: 'mllama'")
        assert _is_model_load_error("failed to load model llama3.2-vision")
        assert _is_model_load_error("HTTP 500: cannot allocate memory")

    def test_ignores_unrelated_errors(self):
        from ai_assist import _is_model_load_error

        assert not _is_model_load_error("connection refused")
        assert not _is_model_load_error("HTTP 500: internal server error")
        assert not _is_model_load_error("")


class TestPickOllamaModelBroken:
    def test_skips_broken_primary_and_uses_fallback(self, monkeypatch):
        import ai_assist

        monkeypatch.setenv("OLLAMA_MODEL", "llama3.2-vision")
        monkeypatch.setattr(ai_assist, "_ollama_active_model", None)
        monkeypatch.setattr(ai_assist, "_get_available_ram_gb", lambda: 12.0)
        monkeypatch.setattr(ai_assist, "_is_model_available", lambda name, logger=None: True)
        monkeypatch.setattr(ai_assist, "_ollama_broken_models", {"llama3.2-vision"})

        chosen = ai_assist._pick_ollama_model()
        assert chosen == ai_assist.OLLAMA_FALLBACK_MODEL

    def test_disables_ai_when_ram_too_low(self, monkeypatch):
        import ai_assist

        monkeypatch.setattr(ai_assist, "_ollama_active_model", None)
        monkeypatch.setattr(ai_assist, "_get_available_ram_gb", lambda: 1.5)
        monkeypatch.setattr(ai_assist, "_ollama_broken_models", set())

        assert ai_assist._pick_ollama_model() == ""


class TestCallOllamaBrokenModel:
    def test_marks_broken_model_and_falls_back_to_working_model(self, monkeypatch):
        import ai_assist

        seen = []

        class FakeResp:
            def __init__(self, model, is_ok):
                self.model = model
                self.is_ok = is_ok
                self.status_code = 200 if is_ok else 500
                self.text = ""

            def json(self):
                if self.is_ok:
                    return {"message": {"content": '[{"aluno": "Ana", "nota": "9"}]'}}
                return {"error": "error loading model: unknown model architecture: 'mllama'"}

        def fake_post(endpoint, json=None, timeout=None):
            seen.append(json["model"])
            is_ok = json["model"] != "llama3.2-vision"
            return FakeResp(json["model"], is_ok)

        monkeypatch.setattr(ai_assist, "_ollama_broken_models", set())
        monkeypatch.setattr(ai_assist, "_ollama_active_model", None)
        monkeypatch.setattr(ai_assist, "_ollama_consecutive_errors", 0)
        monkeypatch.setattr(ai_assist, "_ollama_disabled_until", 0.0)
        monkeypatch.setattr(ai_assist, "_is_ollama_running", lambda: True)
        monkeypatch.setattr(ai_assist, "_pick_ollama_model", lambda logger=None: "llama3.2-vision")
        monkeypatch.setattr(ai_assist, "_is_model_available", lambda name, logger=None: True)
        monkeypatch.setattr(ai_assist, "http_requests", type("R", (), {"post": staticmethod(fake_post)})())

        text = ai_assist._call_ollama("prompt", image_bytes=b"\x89PNG\r\n\x1a\nfake")
        assert '[{"aluno": "Ana", "nota": "9"}]' in text
        assert seen == ["llama3.2-vision", ai_assist.OLLAMA_FALLBACK_MODEL]
        assert "llama3.2-vision" in ai_assist._ollama_broken_models

    def test_raises_when_all_models_broken(self, monkeypatch):
        import ai_assist

        class FakeResp:
            status_code = 500
            text = ""

            def json(self):
                return {"error": "failed to load model: cannot allocate memory"}

        def fake_post(endpoint, json=None, timeout=None):
            return FakeResp()

        monkeypatch.setattr(ai_assist, "_ollama_broken_models", set())
        monkeypatch.setattr(ai_assist, "_ollama_active_model", None)
        monkeypatch.setattr(ai_assist, "_ollama_consecutive_errors", 0)
        monkeypatch.setattr(ai_assist, "_ollama_disabled_until", 0.0)
        monkeypatch.setattr(ai_assist, "_is_ollama_running", lambda: True)
        monkeypatch.setattr(ai_assist, "_pick_ollama_model", lambda logger=None: "llama3.2-vision")
        monkeypatch.setattr(ai_assist, "_is_model_available", lambda name, logger=None: True)
        monkeypatch.setattr(ai_assist, "http_requests", type("R", (), {"post": staticmethod(fake_post)})())

        from ai_assist import AIAssistError

        with pytest.raises(AIAssistError):
            ai_assist._call_ollama("prompt", image_bytes=b"\x89PNG\r\n\x1a\nfake")
        assert ai_assist.OLLAMA_FALLBACK_MODEL in ai_assist._ollama_broken_models
